"""/api/rough-cut - 自动化粗切"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..store import (
    ClipCandidate,
    Task,
    TaskStatus,
    TaskType,
    get_store,
)
from ..config import get_config
from ..pipelines import RoughCutEngine, CandidateClip
from ..utils import file_path_to_url
from backend.pipeline_registry import get_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class RoughCutRunRequest(BaseModel):
    video_id: str
    min_duration_sec: float = 5.0
    min_score: float = 0.4
    max_frames: Optional[int] = None
    # 新版粗切流水线：可选地把候选流式裁剪到文件
    cut_to_files: bool = False
    output_dir: Optional[str] = None  # 默认 ./outputs/rough/<video_id>


@router.post("/run")
def run_rough_cut(req: RoughCutRunRequest) -> dict:
    """运行自动化粗切。"""
    store = get_store()
    video = store.get_video(req.video_id)
    if video is None:
        raise HTTPException(404, "Video not found")
    if not video.file_path or not Path(video.file_path).exists():
        raise HTTPException(400, "Video file not available")

    # 创建任务
    task = Task(
        type=TaskType.PROCESS_VIDEO,
        video_id=video.id,
        status=TaskStatus.ROUGH_CUTTING,
        current_stage="rough_cutting",
    )
    store.create_task(task)

    # 引擎
    cfg = get_config()
    engine: RoughCutEngine = get_pipeline("rough_cut")
    engine.min_duration_sec = req.min_duration_sec
    engine.min_score = req.min_score

    # 运行检测
    candidates: list[CandidateClip] = engine.detect(
        video.file_path, max_frames=req.max_frames
    )

    # 可选：流式裁剪（ffmpeg -c copy）
    if req.cut_to_files and candidates:
        out_dir = req.output_dir or str(
            Path(cfg.runtime.output_dir) / "rough" / video.id
        )
        candidates = engine.cut_candidates_to_files(
            video.file_path, candidates, output_dir=out_dir
        )

    # 持久化候选
    models = [
        ClipCandidate(
            video_id=video.id,
            start_frame=c.start_frame,
            end_frame=c.end_frame,
            score=c.score,
            meta={
                "motion_score": c.motion_score,
                "person_score": c.person_score,
            },
        )
        for c in candidates
    ]
    store.add_candidates(models)

    # 更新任务
    store.update_task(
        task.id,
        status=TaskStatus.ROUGH_CUT,
        progress=1.0,
        current_stage="rough_cut",
        message=f"Found {len(candidates)} candidates",
    )

    return {
        "task_id": task.id,
        "video_id": video.id,
        "candidates": [_cand_to_dict(c, video.fps) for c in candidates],
        "total": len(candidates),
    }


@router.get("/candidates/{video_id}")
def list_candidates(video_id: str) -> dict:
    """列出某个视频的粗切候选。"""
    store = get_store()
    candidates = store.list_candidates(video_id)
    video = store.get_video(video_id)
    fps = video.fps if video else 30.0
    return {
        "candidates": [_cand_to_dict_model(c, fps) for c in candidates],
        "total": len(candidates),
    }


@router.get("/queue")
def get_rough_cut_queue() -> dict:
    """获取粗切队列状态 - 复现 HTML 模块「自动粗切中」实时面板。

    返回所有视频及其粗切状态：
      - pending: 等待粗切 (DOWNLOADED 但还没跑)
      - processing: 正在粗切 (ROUGH_CUTTING)
      - done: 粗切完成 (ROUGH_CUT)
      - failed: 粗切失败
    """
    store = get_store()
    videos = store.list_videos(limit=100)
    queue = []
    for v in videos:
        # 找对应的粗切任务
        tasks = store.list_tasks(limit=1000)
        rough_task = None
        for t in tasks:
            if t.video_id == v.id and t.current_stage in ("rough_cutting", "rough_cut") and t.status != "completed":
                rough_task = t
                break
            if t.video_id == v.id and t.status == "completed" and t.current_stage in ("rough_cutting", "rough_cut"):
                rough_task = t
                break

        # 计算候选数
        cands = store.list_candidates(v.id)
        total = len(cands)
        approved = sum(1 for c in cands if c.approved)

        if rough_task and rough_task.status.value == "rough_cutting":
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "processing",
                "progress": rough_task.progress, "candidates": total, "approved": approved,
            })
        elif rough_task and rough_task.status.value == "failed":
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "failed",
                "progress": 0, "candidates": 0, "approved": 0, "error": rough_task.error,
            })
        elif rough_task and rough_task.status.value in ("rough_cut", "completed"):
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "done",
                "progress": 1.0, "candidates": total, "approved": approved,
            })
        elif total > 0:
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "done",
                "progress": 1.0, "candidates": total, "approved": approved,
            })
        else:
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "pending",
                "progress": 0, "candidates": 0, "approved": 0,
            })
    return {"queue": queue, "total": len(queue)}


@router.get("/approved")
def get_approved_candidates() -> dict:
    """获取所有「已通过粗切、待精切」的候选列表。

    返回按 video 分组的 approved 候选，精切工作台用此列表显示在右侧。
    """
    store = get_store()
    videos = store.list_videos(limit=1000)
    groups = []
    for v in videos:
        cands = store.list_candidates(v.id)
        approved = [c for c in cands if c.approved]
        if not approved:
            continue
        groups.append({
            "video_id": v.id,
            "video_name": v.guid or v.id,
            "video_url": file_path_to_url(v.file_path),
            "fps": v.fps,
            "duration": v.duration,
            "candidates": [
                {
                    "id": c.id,
                    "start_frame": c.start_frame,
                    "end_frame": c.end_frame,
                    "start_sec": c.start_frame / max(v.fps, 1),
                    "end_sec": c.end_frame / max(v.fps, 1),
                    "score": c.score,
                    "duration_sec": (c.end_frame - c.start_frame) / max(v.fps, 1),
                }
                for c in approved
            ],
        })
    return {"groups": groups, "total": sum(len(g["candidates"]) for g in groups)}
    """获取粗切队列状态 - 复现 HTML 模块「自动粗切中」实时面板。

    返回所有视频及其粗切状态：
      - pending: 等待粗切 (DOWNLOADED 但还没跑)
      - processing: 正在粗切 (ROUGH_CUTTING)
      - done: 粗切完成 (ROUGH_CUT)
      - failed: 粗切失败
    """
    store = get_store()
    videos = store.list_videos(limit=100)
    queue = []
    for v in videos:
        # 找对应的粗切任务
        tasks = store.list_tasks(limit=1000)
        rough_task = None
        for t in tasks:
            if t.video_id == v.id and t.current_stage in ("rough_cutting", "rough_cut") and t.status != "completed":
                rough_task = t
                break
            if t.video_id == v.id and t.status == "completed" and t.current_stage in ("rough_cutting", "rough_cut"):
                rough_task = t
                break

        # 计算候选数
        cands = store.list_candidates(v.id)
        total = len(cands)
        approved = sum(1 for c in cands if c.approved)

        if rough_task and rough_task.status.value == "rough_cutting":
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "processing",
                "progress": rough_task.progress, "candidates": total, "approved": approved,
            })
        elif rough_task and rough_task.status.value == "failed":
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "failed",
                "progress": 0, "candidates": 0, "approved": 0, "error": rough_task.error,
            })
        elif rough_task and rough_task.status.value in ("rough_cut", "completed"):
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "done",
                "progress": 1.0, "candidates": total, "approved": approved,
            })
        elif total > 0:
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "done",
                "progress": 1.0, "candidates": total, "approved": approved,
            })
        else:
            queue.append({
                "video_id": v.id, "name": v.guid or v.id, "status": "pending",
                "progress": 0, "candidates": 0, "approved": 0,
            })
    return {"queue": queue, "total": len(queue)}


@router.post("/approve/{candidate_id}")
def approve_candidate(candidate_id: str, approved: bool = True) -> dict:
    """通过/撤销候选片段。

    - approved=True: 通过 (approved=True, rejected=False) - 互斥
    - approved=False: 撤销通过 (approved=False；rejected 字段不变)
    """
    store = get_store()
    if approved:
        # 通过时同时清掉 rejected，保证互斥
        store.update_candidate(candidate_id, approved=True, rejected=False)
    else:
        store.update_candidate(candidate_id, approved=False)
    return {"ok": True, "approved": approved}


@router.post("/reject/{candidate_id}")
def reject_candidate(candidate_id: str, rejected: bool = True) -> dict:
    """拒绝/撤销拒绝候选片段。

    - rejected=True: 拒绝 (rejected=True, approved=False)
    - rejected=False: 撤销拒绝（回到 pending）
    """
    store = get_store()
    # 拒绝时同时清掉 approved，避免状态机不一致
    if rejected:
        store.update_candidate(candidate_id, approved=False, rejected=True)
    else:
        store.update_candidate(candidate_id, rejected=False)
    return {"ok": True, "rejected": rejected}


def _cand_to_dict(c: CandidateClip, fps: float) -> dict:
    return {
        "id": "",
        "start_frame": c.start_frame,
        "end_frame": c.end_frame,
        "start_sec": c.start_frame / fps,
        "end_sec": c.end_frame / fps,
        "duration_sec": (c.end_frame - c.start_frame) / fps,
        "score": c.score,
        "motion_score": c.motion_score,
        "person_score": c.person_score,
        "cut_path": c.cut_path,
    }


def _cand_to_dict_model(c: ClipCandidate, fps: float) -> dict:
    return {
        "id": c.id,
        "start_frame": c.start_frame,
        "end_frame": c.end_frame,
        "start_sec": c.start_frame / fps,
        "end_sec": c.end_frame / fps,
        "duration_sec": (c.end_frame - c.start_frame) / fps,
        "score": c.score,
        "approved": c.approved,
        "rejected": c.rejected,
        "reason": c.reason,
    }
