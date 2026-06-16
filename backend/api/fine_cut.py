"""/api/fine-cut - 精切裁剪"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_config
from ..store import (
    Clip,
    ClipStatus,
    Task,
    TaskStatus,
    TaskType,
    get_store,
)
from ..utils import file_path_to_url
from backend.pipeline_registry import get_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class FineCutRequest(BaseModel):
    """精切裁剪请求（绝对时间，旧版接口，保留向后兼容）。"""
    video_id: str
    candidate_id: Optional[str] = None  # 可选 - 从粗切候选继承
    start_sec: float
    end_sec: float
    name: Optional[str] = None


class FineCutDecideRequest(BaseModel):
    """精切决策请求（相对偏移新版接口）。

    必传二选一：candidate_id（从粗切候选精切） 或 clip_id（重切已有 clip）。
    传 trim_start/trim_end 时为「保留并精切」；只传 action=reject 时为「拒绝」。
    """
    candidate_id: Optional[str] = None
    clip_id: Optional[str] = None
    trim_start: Optional[float] = None   # 相对候选/clip 起点的偏移
    trim_end: Optional[float] = None
    action: str = "keep"  # keep | reject
    fallback_path: Optional[str] = None  # 源片不可用时的兜底文件


@router.post("/trim")
def trim_clip(req: FineCutRequest) -> dict:
    """执行精切。"""
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
        status=TaskStatus.FINE_CUT,
        current_stage="fine_cut",
    )
    store.create_task(task)

    # 执行裁剪
    engine = get_pipeline("fine_cut")
    cfg = get_config()
    out_dir = Path(cfg.runtime.output_dir) / task.id / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    engine.output_dir = out_dir
    name = req.name or f"clip_{int(req.start_sec * 1000):08d}_{int(req.end_sec * 1000):08d}.mp4"
    result = engine.trim(
        src=video.file_path,
        start_sec=req.start_sec,
        end_sec=req.end_sec,
        out_name=name,
    )

    # 创建 Clip
    clip = Clip(
        task_id=task.id,
        video_id=video.id,
        start_frame=int(req.start_sec * video.fps),
        end_frame=int(req.end_sec * video.fps),
        start_sec=req.start_sec,
        end_sec=req.end_sec,
        duration=req.end_sec - req.start_sec,
        status=ClipStatus.FINE_CUT,
    )
    clip.meta["candidate_id"] = req.candidate_id or ""
    clip.meta["trimmed_path"] = result["path"]
    store.upsert_clip(clip)

    store.update_task(
        task.id,
        progress=1.0,
        current_stage="fine_cut_done",
        message=f"Trimmed to {result['path']}",
        meta_update={"clip_id": clip.id},
    )

    return {
        "task_id": task.id,
        "clip": _clip_to_dict(clip, video),
        "trim_result": result,
    }


@router.get("/clips")
def list_clips(video_id: Optional[str] = None, limit: int = 100) -> dict:
    """列出精切片段。"""
    store = get_store()
    clips = store.list_clips(video_id=video_id, limit=limit)
    return {
        "clips": [_clip_to_dict_min(c) for c in clips],
        "total": len(clips),
    }


@router.get("/clip/{clip_id}")
def get_clip(clip_id: str) -> dict:
    """获取片段详情。"""
    store = get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    video = store.get_video(clip.video_id) if clip.video_id else None
    return _clip_to_dict(clip, video)


@router.post("/decide")
def decide_clip(req: FineCutDecideRequest) -> dict:
    """精切决策（优化版）：接受相对偏移，后端换算绝对时间并 ffmpeg -c copy。

    Flow:
      1) candidate_id → 取 source video + candidate 的绝对区间
         clip_id      → 取 source video + clip 的绝对区间
      2) action=reject → 标记 candidate approved=False，结束
      3) keep_clip() → 相对 → 绝对 → ffprobe 校验 → 0.05s 容忍 → kept/...
      4) 写 clip 行（status=FINE_CUT），更新 candidate approved=True
    """
    store = get_store()
    if not req.candidate_id and not req.clip_id:
        raise HTTPException(400, "candidate_id or clip_id required")

    # 1) 解析源片 / 区间
    if req.candidate_id:
        cand = store.get_candidate(req.candidate_id)
        if cand is None:
            raise HTTPException(404, f"Candidate not found: {req.candidate_id}")
        video = store.get_video(cand.video_id)
        if video is None or not video.file_path:
            raise HTTPException(400, "Source video unavailable for this candidate")
        cand_start_sec = cand.start_frame / max(video.fps, 1.0)
        cand_end_sec = cand.end_frame / max(video.fps, 1.0)
        identifier = req.candidate_id
    else:  # clip_id
        clip = store.get_clip(req.clip_id)
        if clip is None:
            raise HTTPException(404, f"Clip not found: {req.clip_id}")
        video = store.get_video(clip.video_id) if clip.video_id else None
        if video is None or not video.file_path:
            raise HTTPException(400, "Source video unavailable for this clip")
        cand_start_sec = clip.start_sec
        cand_end_sec = clip.end_sec
        identifier = req.clip_id

    candidate_duration = cand_end_sec - cand_start_sec

    # 2) reject 路径
    if req.action == "reject":
        if req.candidate_id:
            store.update_candidate(req.candidate_id, False)
        return {"ok": True, "rejected": True}

    # 3) 默认 relative 范围：用户没传 → 整段保留
    rel_start = req.trim_start if req.trim_start is not None else 0.0
    rel_end = (
        req.trim_end
        if req.trim_end is not None
        else candidate_duration
    )

    # 4) 引擎
    engine = get_pipeline("fine_cut")
    try:
        result = engine.keep_clip(
            source_video=video.file_path,
            source_duration=video.duration,
            candidate_start=cand_start_sec,
            candidate_end=cand_end_sec,
            relative_start=rel_start,
            relative_end=rel_end,
            clip_id=identifier,
            fallback_path=req.fallback_path or "",
        )
    except ValueError as e:
        raise HTTPException(400, f"trim 范围非法: {e}")
    except FileNotFoundError as e:
        raise HTTPException(400, f"源片不可用: {e}")

    # 5) 写 clip（status = FINE_CUT）
    kept_path = result["output_path"]
    if req.candidate_id:
        # 在 candidate 基础上精切 → 新建 clip
        clip = Clip(
            task_id=identifier,  # 关联到 candidate id
            video_id=video.id,
            start_frame=int(result["start_time"] * max(video.fps, 1.0)),
            end_frame=int(result["end_time"] * max(video.fps, 1.0)),
            start_sec=result["start_time"],
            end_sec=result["end_time"],
            duration=result["duration"],
            status=ClipStatus.FINE_CUT,
        )
        clip.meta["candidate_id"] = req.candidate_id
        clip.meta["kept_path"] = kept_path
        clip.meta["trimmed"] = result.get("trimmed", False)
        clip.meta["trim_skipped"] = result.get("skipped", False)
        clip.meta["relative_start"] = result["relative_start"]
        clip.meta["relative_end"] = result["relative_end"]
        store.upsert_clip(clip)
        # 标记 candidate 已通过
        store.update_candidate(req.candidate_id, True)
    else:
        # 重切已有 clip
        clip = store.get_clip(req.clip_id)
        clip.video_id = video.id
        clip.start_frame = int(result["start_time"] * max(video.fps, 1.0))
        clip.end_frame = int(result["end_time"] * max(video.fps, 1.0))
        clip.start_sec = result["start_time"]
        clip.end_sec = result["end_time"]
        clip.duration = result["duration"]
        clip.status = ClipStatus.FINE_CUT
        clip.meta["kept_path"] = kept_path
        clip.meta["trimmed"] = result.get("trimmed", False)
        clip.meta["trim_skipped"] = result.get("skipped", False)
        clip.meta["relative_start"] = result["relative_start"]
        clip.meta["relative_end"] = result["relative_end"]
        store.upsert_clip(clip)

    return {
        "ok": True,
        "clip": _clip_to_dict(clip, video),
        "trim_result": {
            "trimmed": result.get("trimmed", False),
            "skipped": result.get("skipped", False),
            "output_path": kept_path,
            "start_time": result["start_time"],
            "end_time": result["end_time"],
            "duration": result["duration"],
            "source": result.get("ffmpeg_src") or result.get("source"),
        },
    }


def _clip_to_dict(c: Clip, video) -> dict:
    return {
        "id": c.id,
        "task_id": c.task_id,
        "video_id": c.video_id,
        "start_frame": c.start_frame,
        "end_frame": c.end_frame,
        "start_sec": c.start_sec,
        "end_sec": c.end_sec,
        "duration": c.duration,
        "status": c.status.value,
        "video_name": Path(video.file_path).name if video and video.file_path else "",
        "video_url": file_path_to_url(video.file_path) if video and video.file_path else "",
        "meta": c.meta,
        "rendered_video_url": c.rendered_video_url,
    }


def _clip_to_dict_min(c: Clip) -> dict:
    return {
        "id": c.id,
        "video_id": c.video_id,
        "task_id": c.task_id,
        "start_sec": c.start_sec,
        "end_sec": c.end_sec,
        "duration": c.duration,
        "status": c.status.value,
        "rendered_video_url": c.rendered_video_url,
    }
