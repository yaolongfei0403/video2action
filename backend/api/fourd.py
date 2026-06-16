"""/api/4d - 4D 重建 (编排 SAM-3 + Diffusion-VAS + SAM-3D-Body)"""
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
from ..utils import read_video_metadata
from backend.pipeline_registry import get_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class MaskPropagationRequest(BaseModel):
    """Mask 传播请求 - 复现 app.py:on_mask_generation"""
    clip_id: str
    start_frame_idx: int = 0
    max_frames: int = 1800


class FourDReconstructRequest(BaseModel):
    """4D 重建请求 - 复现 app.py:on_4d_generation"""
    clip_id: str


@router.post("/mask")
def propagate_masks(req: MaskPropagationRequest) -> dict:
    """执行 SAM-3 视频 mask 传播。

    返回中间产物路径与状态。
    """
    store = get_store()
    clip = store.get_clip(req.clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    # 创建任务
    task = Task(
        type=TaskType.PROCESS_VIDEO,
        video_id=clip.video_id,
        clip_id=clip.id,
        status=TaskStatus.MASK_PROPAGATING,
        current_stage="mask_propagating",
    )
    store.create_task(task)

    # stub 模式下：四维 pipeline 内部一站式处理；这里仅做状态推进
    store.update_task(
        task.id,
        status=TaskStatus.FOUR_D_RECONSTRUCTING,
        progress=0.3,
        current_stage="4d_reconstructing",
        message="Mask 传播完成（stub 模式自动执行于 4D 重建内）",
    )

    return {
        "task_id": task.id,
        "clip_id": clip.id,
        "status": "mask_propagated",
        "stub": True,
    }


@router.post("/reconstruct")
def reconstruct_4d(req: FourDReconstructRequest) -> dict:
    """执行完整 4D 重建 + 渲染视频导出。

    真实模式：调用 FourDPipeline.run()
    stub 模式：四维 pipeline 内部一站式处理
    """
    store = get_store()
    clip = store.get_clip(req.clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    if not clip.annotations:
        raise HTTPException(400, "No annotations - run /api/target/click first")
    if clip.status == ClipStatus.FINE_CUT:
        raise HTTPException(400, "Clip needs annotation first (status=fine_cut)")
    if clip.status == ClipStatus.FOUR_D_DONE:
        # 重复 4D 视为重跑, 允许
        pass

    # 任务
    task = Task(
        type=TaskType.FOUR_D_RECONSTRUCT,
        video_id=clip.video_id,
        clip_id=clip.id,
        status=TaskStatus.FOUR_D_RECONSTRUCTING,
        current_stage="4d_reconstructing",
    )
    store.create_task(task)

    # 找视频路径
    video = store.get_video(clip.video_id) if clip.video_id else None
    video_path = ""
    if clip.meta.get("trimmed_path") and Path(clip.meta["trimmed_path"]).exists():
        video_path = clip.meta["trimmed_path"]
    elif video and video.file_path and Path(video.file_path).exists():
        video_path = video.file_path
    if not video_path:
        raise HTTPException(400, "Source video not available for clip")

    fps = video.fps if video else 30.0
    obj_ids = sorted({a.obj_id for a in clip.annotations})

    # 推进入度
    store.update_task(task.id, progress=0.1, message="开始 4D 重建")

    # 执行
    fourd = get_pipeline("fourd")
    try:
        result = fourd.run(
            task_id=task.id,
            video_id=clip.video_id or "",
            clip_id=clip.id,
            video_path=video_path,
            obj_ids=obj_ids,
            fps=fps,
            start_sec=clip.start_sec,
            end_sec=clip.end_sec,
        )
    except Exception as e:
        logger.exception("4D reconstruction failed")
        store.update_task(task.id, status=TaskStatus.FAILED, error=str(e))
        raise HTTPException(500, f"4D reconstruction failed: {e}")

    return {
        "task_id": task.id,
        "clip_id": clip.id,
        "output_video": result.output_video,
        "output_video_url": f"/api/outputs/{task.id}/{Path(result.output_video).name}",
        "total_frames": result.total_frames,
        "duration": result.duration,
        "obj_ids": result.obj_ids,
        "mode": "real" if fourd.sam3d.mode == "real" else "stub",
    }


@router.get("/status/{task_id}")
def get_4d_status(task_id: str) -> dict:
    """查询 4D 重建任务状态。"""
    store = get_store()
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return {
        "task_id": task.id,
        "status": task.status.value,
        "progress": task.progress,
        "message": task.message,
        "error": task.error,
        "current_stage": task.current_stage,
    }


@router.post("/process-next")
def process_next_from_queue() -> dict:
    """自动从 4D 队列取下一个待处理 clip 并触发重建.

    这是 4D Studio "自动模式" 的核心入口:
    - 如果有 status=annotated 的 clip, 调 /reconstruct 启动
    - 否则返回 status=idle
    """
    from .clip_queue import start_4d_for_clip
    store = get_store()
    clips = store.list_clips(limit=200)
    next_clip = next(
        (c for c in clips if c.status == ClipStatus.ANNOTATED),
        None,
    )
    if next_clip is None:
        return {"status": "idle", "message": "队列为空", "next_clip_id": None}

    # 准备重建参数
    info = start_4d_for_clip(next_clip.id)
    if not info.get("trimmed_path") and not info.get("video_url"):
        raise HTTPException(400, f"Clip {next_clip.id} has no video")

    return {
        "status": "ready",
        "next_clip_id": next_clip.id,
        "info": info,
    }
