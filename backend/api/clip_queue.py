"""/api/clips - 片段队列管理 (精切→Target→4D→标签 全流程).

剪切入队 → Target Studio 选帧 + 标注 → 4D 队列 → 自动处理
"""
from __future__ import annotations

import base64
import io
import logging
import re
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from PIL import Image
from pydantic import BaseModel

from ..config import get_config
from ..store import (
    Clip,
    ClipStatus,
    MaskAnnotation,
    get_store,
)
from ..utils import file_path_to_url

logger = logging.getLogger(__name__)
# 注意：不要在这里加 prefix="/clips"，main.py 里 register_routes 已经加了 /api/clips
router = APIRouter(tags=["clip-queue"])


# ============== 待标注列表 ==============


@router.get("/pending-targets")
def list_pending_target_clips(limit: int = 100) -> dict:
    """列出「精切完成 + 待添加 target」的所有 clip。

    Target Studio 右侧列表用。
    """
    store = get_store()
    all_clips = store.list_clips(limit=limit)
    # 状态过滤：精切完成 或 已标注但未进入 4D
    pending_statuses = {ClipStatus.FINE_CUT.value, ClipStatus.ANNOTATED.value}
    pending = [c for c in all_clips if c.status in pending_statuses]
    # 按 updated_at 倒序
    pending.sort(key=lambda c: c.updated_at, reverse=True)
    return {
        "clips": [
            {
                "id": c.id,
                "task_id": c.task_id,
                "video_id": c.video_id,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "duration": c.duration,
                "status": c.status,
                "kept_path": c.meta.get("kept_path", ""),
                "annotation_count": len(c.annotations),
                "updated_at": c.updated_at.isoformat() if c.updated_at else "",
            }
            for c in pending
        ],
        "total": len(pending),
    }


# ============== 抽帧 ==============


@router.get("/{clip_id}/frames")
def extract_frames(
    clip_id: str,
    count: int = 8,
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
) -> dict:
    """从 clip 对应的视频中抽帧 (默认 8 张均匀帧), 返回 base64 JPEG。

    用于 Target Studio 显示候选帧让用户选择 target。
    """
    store = get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    # 找视频路径
    video_path = clip.meta.get("trimmed_path") or clip.meta.get("source_path") or ""
    if not video_path or not Path(video_path).exists():
        # 回退到原视频 + 时间范围
        video = store.get_video(clip.video_id) if clip.video_id else None
        if video and video.file_path and Path(video.file_path).exists():
            video_path = video.file_path
        else:
            raise HTTPException(404, "No video file available for this clip")

    s = start_sec if start_sec is not None else clip.start_sec
    e = end_sec if end_sec is not None else clip.end_sec

    # 如果用 trimmed_path，文件本身已从 clip.start_sec 开始 → 帧号要重置为 0
    if video_path and "trimmed_path" in clip.meta and video_path == clip.meta.get("trimmed_path"):
        s_rel = 0.0
        e_rel = e - s
        s, e = s_rel, e_rel

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    start_f = int(s * fps)
    end_f = int(e * fps)
    end_f = min(end_f, total)

    # 均匀采样 count 帧
    frames_b64: List[str] = []
    timestamps: List[float] = []
    if end_f > start_f:
        for i in range(count):
            t_pct = (i + 0.5) / count
            frame_idx = start_f + int((end_f - start_f) * t_pct)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            ts = frame_idx / fps
            timestamps.append(ts)
            # 缩放到 480 宽 (节省带宽)
            h, w = frame.shape[:2]
            if w > 480:
                scale = 480 / w
                frame = cv2.resize(frame, (480, int(h * scale)))
            # JPEG 编码
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            frames_b64.append(base64.b64encode(buf.tobytes()).decode("ascii"))
    cap.release()

    return {
        "clip_id": clip_id,
        "start_sec": s,
        "end_sec": e,
        "fps": fps,
        "count": len(frames_b64),
        "frames": frames_b64,        # base64 字符串数组
        "timestamps": timestamps,    # 对应时间戳
    }


# ============== 状态推进 ==============


class AnnotationItem(BaseModel):
    obj_id: int
    frame_idx: int
    point_type: str = "positive"
    x: int
    y: int


class AnnotateRequest(BaseModel):
    """Target Studio → 确认标注入队 (待 4D)"""
    annotations: List[AnnotationItem]


@router.post("/{clip_id}/annotate")
def annotate_clip(clip_id: str, req: AnnotateRequest) -> dict:
    """Target Studio 提交标注 → 替换 clip.annotations。

    前端发来的是全量列表 (Source of Truth 在前端, 与 app.py 的 RUNTIME['clicks']
    由前端 Gradio state 管理一致), 所以这里是**替换**而不是**追加**。

    状态推进由 /api/target/add 负责 (FINE_CUT → ANNOTATED), 本端点不动 status。
    """
    store = get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    # 替换为前端发来的全量列表 (Source of Truth = 前端 _annotations)
    clip.annotations = [
        MaskAnnotation(
            obj_id=a.obj_id,
            frame_idx=a.frame_idx,
            point_type=a.point_type,
            x=a.x,
            y=a.y,
        )
        for a in req.annotations
    ]
    store.upsert_clip(clip)

    return {
        "ok": True,
        "clip_id": clip.id,
        "status": clip.status.value,
        "annotation_count": len(clip.annotations),
    }


# ============== 4D 队列 ==============


@router.get("/queue")
def get_processing_queue() -> dict:
    """获取待 4D 处理的片段队列 (status=annotated)."""
    store = get_store()
    clips = store.list_clips(limit=200)
    pending = [c for c in clips if c.status == ClipStatus.ANNOTATED]

    return {
        "queue": [
            {
                "clip_id": c.id,
                "video_id": c.video_id,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
                "duration": c.duration,
                "annotation_count": len(c.annotations),
                "obj_ids": sorted({a.obj_id for a in c.annotations}),
            }
            for c in pending
        ],
        "total": len(pending),
    }


@router.get("/queue/all")
def get_all_processing_stages() -> dict:
    """获取所有处理阶段队列 (用于前端 Dashboard 状态显示).

    返回四组:
      - fine_cut: 刚精切完，待标注
      - annotating: 正在标注
      - 4d_pending: 已标注，待 4D
      - 4d_done: 4D 完成，待打标
    """
    store = get_store()
    clips = store.list_clips(limit=200)
    by_status: dict[str, list] = {
        ClipStatus.FINE_CUT.value: [],
        ClipStatus.ANNOTATED.value: [],
        ClipStatus.FOUR_D_DONE.value: [],
    }
    for c in clips:
        if c.status.value in by_status:
            by_status[c.status.value].append({
                "clip_id": c.id,
                "video_id": c.video_id,
                "duration": c.duration,
                "start_sec": c.start_sec,
                "end_sec": c.end_sec,
            })
    return {stage: {"total": len(items), "items": items} for stage, items in by_status.items()}


@router.post("/{clip_id}/start-4d")
def start_4d_for_clip(clip_id: str) -> dict:
    """从队列取一个 clip 启动 4D 处理 (POST /clips/{id}/start-4d).

    实际 4D 重建由 /api/4d/reconstruct 完成 (clip_id 必传).
    此接口仅做状态推进 + 返回待处理任务信息.
    """
    store = get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    if clip.status != ClipStatus.ANNOTATED:
        raise HTTPException(400, f"Clip not ready for 4D: status={clip.status.value}")

    # 找关联的 video 信息
    video = store.get_video(clip.video_id) if clip.video_id else None
    return {
        "clip_id": clip.id,
        "video_id": clip.video_id,
        "video_url": (f"/api/outputs/{video.file_path[len('outputs/'):]}"
                      if video and video.file_path and video.file_path.startswith("outputs/")
                      else (video.file_path if video else "")),
        "trimmed_path": clip.meta.get("trimmed_path", ""),
        "start_sec": clip.start_sec,
        "end_sec": clip.end_sec,
        "duration": clip.duration,
        "fps": video.fps if video else 30.0,
        "obj_ids": sorted({a.obj_id for a in clip.annotations}),
    }
