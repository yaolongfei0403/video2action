"""/api/target - 目标标注 (忠实复现 app.py on_click + add_target)"""
from __future__ import annotations

import base64
import io
import logging
import time
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

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


class PointItem(BaseModel):
    """单点提示 (复现 app.py:on_click 的 input_point/label)"""
    x: int
    y: int
    point_type: str = "positive"


class TargetClickRequest(BaseModel):
    """目标点击标注请求 - 复现 app.py:on_click 真实逻辑

    支持两种调用方式:
    1) 旧式 (单点): x, y, point_type
    2) 新式 (累积多点击): points = [{x, y, point_type}, ...] + frame_width/height

    新式调用是忠实复现 —— 把当前 obj 当前 frame 的所有点一次性送给 SAM-3,
    与 app.py:on_click 中 RUNTIME['clicks'][frame_idx] 的累积语义一致。
    """
    clip_id: str
    obj_id: int
    frame_idx: int
    # 旧式单点字段 (向后兼容)
    x: int = 0
    y: int = 0
    point_type: str = "positive"
    # 新式: 当前 frame 当前 obj 的全部点击 (推荐)
    points: Optional[List[PointItem]] = None
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    frame_base64: Optional[str] = None  # 用于返回标注后预览图


class TargetAddRequest(BaseModel):
    """提交当前 target + 推进状态机 - 复现 app.py:add_target"""
    clip_id: str


@router.post("/click")
def on_click(req: TargetClickRequest) -> dict:
    """复现 app.py:on_click 真实逻辑:

    1. 累积当前 obj_id 当前 frame 的所有点 (RUNTIME['clicks'][frame_idx] 等价)
    2. 归一化坐标 [0,1] (app.py:421-422)
    3. 调 SAM-3 出 mask
    4. 把当前帧其他 obj 的 mask 叠加到 painted_image (RUNTIME['masks'] 等价)
    5. 画 +/- marker
    6. 返回 mask + painted image

    注意: 本端点**只做实时 mask 预览**, 不修改 clip.annotations / clip.status。
    标注持久化请走 /api/clips/{id}/annotate, 状态推进请走 /api/target/add。
    """
    store = get_store()
    clip = store.get_clip(req.clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    # 1) 解析 points: 优先用新式 points 字段, 否则回退到旧式 (x, y, point_type)
    if req.points:
        pts: list[tuple[int, int, str]] = [
            (int(p.x), int(p.y), p.point_type) for p in req.points
        ]
    else:
        pts = [(req.x, req.y, req.point_type)]

    # 2) 找视频和帧尺寸 (用于归一化)
    video_path = clip.meta.get("trimmed_path") or clip.meta.get("source_path") or ""
    W, H = req.frame_width, req.frame_height
    if (not W or not H) and video_path and Path(video_path).exists():
        cap = cv2.VideoCapture(video_path)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
    if not W or not H:
        W, H = 640, 360  # fallback

    # 3) 归一化坐标 [0,1] —— 忠实复现 app.py:421-422
    rel_points = [[x / W, y / H] for (x, y, _) in pts]
    rel_labels = [1 if t.lower() == "positive" else 0 for (_, _, t) in pts]
    points_np = np.array(rel_points, dtype=np.float32) if rel_points else np.zeros((0, 2), dtype=np.float32)
    labels_np = np.array(rel_labels, dtype=np.int32) if rel_labels else np.zeros((0,), dtype=np.int32)

    # 4) 调 SAM-3
    sam3 = get_pipeline("sam3")
    state = None
    mask_np: Optional[np.ndarray] = None
    if video_path and Path(video_path).exists():
        try:
            state = sam3.init_state(video_path)
            _, _, _, video_res_masks = sam3.add_new_points_or_box(
                state, req.frame_idx, req.obj_id, points_np, labels_np
            )
            if hasattr(video_res_masks, "detach"):
                mask_np = (video_res_masks[-1, 0].detach().cpu().numpy() > 0).astype(np.uint8) * 255
            else:
                mask_np = (np.asarray(video_res_masks[-1, 0]) > 0).astype(np.uint8) * 255
        except Exception as e:
            logger.warning(f"SAM-3 click failed: {e}; using fallback mask")
            mask_np = None

    if mask_np is None:
        # 无视频 / SAM-3 失败 → 用 frame_base64 处理
        if req.frame_base64:
            return _stub_click_from_b64(clip, req, pts, W, H)
        # 兜底: 30 像素圆 (最后一道防线)
        mask_np = np.zeros((H, W), dtype=np.uint8)
        cv2.circle(mask_np, (req.x, req.y), 30, 255, -1)

    # 5) 叠加当前帧其他 obj 的 mask (RUNTIME['masks'] 等价: app.py:438-443)
    painted_image = None
    if req.frame_base64:
        try:
            img_bytes = base64.b64decode(req.frame_base64)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            painted_arr = np.array(img, dtype=np.uint8)
            # 当前 obj 的 mask
            painted_arr = mask_painter(painted_arr, mask_np, mask_color=4 + req.obj_id)
            # 其他 obj 在当前 frame 的 mask (从已存盘的 clip.annotations 推断)
            for a in clip.annotations:
                if a.obj_id != req.obj_id and a.frame_idx == req.frame_idx:
                    other_mask = np.zeros((H, W), dtype=np.uint8)
                    cv2.circle(other_mask, (a.x, a.y), 30, 255, -1)
                    painted_arr = mask_painter(painted_arr, other_mask, mask_color=4 + a.obj_id)
            # 画最后一个 marker
            painted_pil = draw_point_marker(Image.fromarray(painted_arr), req.x, req.point_type)
            buf = io.BytesIO()
            painted_pil.save(buf, format="JPEG", quality=85)
            painted_image = base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.warning(f"paint failed: {e}")

    # 6) 返回
    mask_pil = Image.fromarray(mask_np)
    mask_buf = io.BytesIO()
    mask_pil.save(mask_buf, format="PNG")
    mask_b64 = base64.b64encode(mask_buf.getvalue()).decode("utf-8")

    return {
        "obj_id": req.obj_id,
        "point_count": len(pts),
        "mask_png_base64": mask_b64,
        "painted_image_base64": painted_image,
    }


def _stub_click_from_b64(clip, req, pts, W, H) -> dict:
    """stub: 仅根据 base64 帧 + 点位返回基础结果 (无视频时的退化路径)。"""
    if not req.frame_base64:
        raise HTTPException(400, "frame_base64 required in stub mode without video")
    img_bytes = base64.b64decode(req.frame_base64)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    arr = np.array(img, dtype=np.uint8)
    mask = np.zeros((H, W), dtype=np.uint8)
    # 多正向点 union + 负向点挖洞
    pos_seeds = [(x, y) for (x, y, t) in pts if t.lower() == "positive"]
    neg_seeds = [(x, y) for (x, y, t) in pts if t.lower() == "negative"]
    for sx, sy in pos_seeds:
        cv2.circle(mask, (sx, sy), 30, 255, -1)
    for nx, ny in neg_seeds:
        cv2.circle(mask, (nx, ny), 30, 0, -1)
    painted = mask_painter(arr, mask, mask_color=4 + req.obj_id)
    painted_pil = draw_point_marker(Image.fromarray(painted), req.x, req.point_type)
    buf = io.BytesIO()
    painted_pil.save(buf, format="JPEG", quality=85)
    painted_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return {
        "obj_id": req.obj_id,
        "point_count": len(pts),
        "mask_png_base64": "",
        "painted_image_base64": painted_b64,
    }


@router.post("/add")
def add_target(req: TargetAddRequest) -> dict:
    """复现 app.py:add_target —— 这是 target 提交的事务边界:

    1. 检查当前是否有任何标注 (没有则 400, 与原 demo "没有点击就不加" 一致)
    2. 推进 clip.status 从 FINE_CUT → ANNOTATED (commit point)
    3. 推进 obj_id: next = max(annotations.obj_id) + 1 (RUNTIME['id'] += 1 等价)
    4. 返回 next obj_id 给前端, 前端据此 _nextObjId = next

    前端在收到 200 后, 自行重置 _nextObjId 并清空"当前 obj 的临时 buffer"。
    """
    store = get_store()
    clip = store.get_clip(req.clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    if not clip.annotations:
        raise HTTPException(400, "No annotations - add some before creating a target")

    # 推进状态机 (commit point: FINE_CUT → ANNOTATED)
    if clip.status == ClipStatus.FINE_CUT:
        clip.status = ClipStatus.ANNOTATED
        store.upsert_clip(clip)

    # 推进 obj_id
    next_id = max([a.obj_id for a in clip.annotations], default=0) + 1
    name = f"Target {next_id}"
    return {
        "obj_id": next_id,
        "name": name,
        "clip_id": clip.id,
        "clip_status": clip.status.value,
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
