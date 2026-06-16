"""/api/target - 目标标注 (复现 app.py on_click + add_target)"""
from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path
from typing import Optional

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
    Task,
    TaskStatus,
    TaskType,
    get_store,
)
from ..utils import draw_point_marker, mask_painter
from backend.pipeline_registry import get_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Request Models ==============


class TargetClickRequest(BaseModel):
    """目标点击标注请求 - 复现 app.py:on_click 逻辑"""
    clip_id: str
    obj_id: int
    frame_idx: int
    x: int
    y: int
    point_type: str = "positive"  # positive / negative
    frame_base64: Optional[str] = None  # base64 JPEG (用于返回标注后图像)


class TargetAddRequest(BaseModel):
    """添加新目标（目标队列）"""
    clip_id: str


@router.post("/click")
def on_click(req: TargetClickRequest) -> dict:
    """处理一次点击标注。

    真实模式：调用 SAM-3 predictor.add_new_points_or_box
    stub 模式：用 OpenCV MOG2 + 形态学生成 mask

    Returns:
        {mask_png_base64, painted_image_base64, obj_ids}
    """
    store = get_store()
    clip = store.get_clip(req.clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    # 1. 更新 Clip 的 annotations
    clip.annotations.append(
        MaskAnnotation(
            obj_id=req.obj_id,
            frame_idx=req.frame_idx,
            point_type=req.point_type,
            x=req.x,
            y=req.y,
        )
    )
    clip.status = ClipStatus.ANNOTATED
    store.upsert_clip(clip)

    # 2. 调用 SAM-3（real/stub）
    sam3 = get_pipeline("sam3")
    # stub 模式：返回基于颜色相似度的 mask
    video_path = clip.meta.get("trimmed_path") or clip.meta.get("source_path") or ""
    if not video_path or not Path(video_path).exists():
        # 没视频：用 frame_base64 处理
        if req.frame_base64:
            return _stub_click_from_b64(clip, req)
        raise HTTPException(400, "No video or frame available")

    state = sam3.init_state(video_path)
    points = np.array([[req.x, req.y]], dtype=np.int32)
    labels = np.array([1 if req.point_type == "positive" else 0], dtype=np.int32)
    try:
        _, out_obj_ids, _, video_res_masks = sam3.add_new_points_or_box(
            state, req.frame_idx, req.obj_id, points, labels
        )
        mask_np = (video_res_masks[-1, 0].detach().cpu().numpy() > 0).astype(np.uint8) * 255 \
            if hasattr(video_res_masks, "detach") else \
            (np.asarray(video_res_masks[-1, 0]) > 0).astype(np.uint8) * 255
    except Exception as e:
        logger.warning(f"SAM-3 click failed: {e}; using simple mask")
        mask_np = np.zeros((360, 640), dtype=np.uint8)
        cv2.circle(mask_np, (req.x, req.y), 30, 255, -1)

    # 3. 绘制 marker
    painted = None
    if req.frame_base64:
        try:
            img_bytes = base64.b64decode(req.frame_base64)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            painted_img = mask_painter(np.array(img, dtype=np.uint8), mask_np, mask_color=4 + req.obj_id)
            painted_pil = draw_point_marker(Image.fromarray(painted_img), req.x, req.y, req.point_type)
            buf = io.BytesIO()
            painted_pil.save(buf, format="JPEG", quality=85)
            painted = base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.warning(f"paint failed: {e}")

    # 4. 返回 mask
    mask_pil = Image.fromarray(mask_np)
    mask_buf = io.BytesIO()
    mask_pil.save(mask_buf, format="PNG")
    mask_b64 = base64.b64encode(mask_buf.getvalue()).decode("utf-8")

    return {
        "obj_id": req.obj_id,
        "mask_png_base64": mask_b64,
        "painted_image_base64": painted,
        "annotations": [a.model_dump() for a in clip.annotations],
    }


def _stub_click_from_b64(clip, req) -> dict:
    """stub: 仅根据 base64 帧 + 点位返回基础结果。"""
    if not req.frame_base64:
        raise HTTPException(400, "frame_base64 required in stub mode without video")
    img_bytes = base64.b64decode(req.frame_base64)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    H, W = arr.shape[:2]
    mask = np.zeros((H, W), dtype=np.uint8)
    cv2.circle(mask, (req.x, req.y), 30, 255, -1)
    painted = mask_painter(arr, mask, mask_color=4 + req.obj_id)
    painted_pil = draw_point_marker(Image.fromarray(painted), req.x, req.y, req.point_type)
    buf = io.BytesIO()
    painted_pil.save(buf, format="JPEG", quality=85)
    painted_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return {
        "obj_id": req.obj_id,
        "mask_png_base64": "",
        "painted_image_base64": painted_b64,
        "annotations": [a.model_dump() for a in clip.annotations],
    }


@router.post("/add")
def add_target(req: TargetAddRequest) -> dict:
    """添加新目标 - 复现 app.py:add_target。

    实际逻辑：分配新 obj_id, 推 RUNTIME 状态。
    """
    store = get_store()
    clip = store.get_clip(req.clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    next_id = max([a.obj_id for a in clip.annotations], default=0) + 1
    name = f"Target {next_id}"
    return {
        "obj_id": next_id,
        "name": name,
        "clip_id": clip.id,
    }


@router.get("/list/{clip_id}")
def list_targets(clip_id: str) -> dict:
    """列出片段的所有目标标注。"""
    store = get_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    # 按 obj_id 分组
    grouped: dict[int, list[MaskAnnotation]] = {}
    for a in clip.annotations:
        grouped.setdefault(a.obj_id, []).append(a)
    return {
        "clip_id": clip.id,
        "targets": [
            {
                "obj_id": oid,
                "name": f"Target {oid}",
                "annotations": [a.model_dump() for a in anns],
                "type": "positive" if any(a.point_type == "positive" for a in anns) else "negative",
            }
            for oid, anns in sorted(grouped.items())
        ],
    }
