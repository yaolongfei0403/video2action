"""Mask processing utilities (rebuilt from app.py usage).

原 app.py 引用：keep_largest_component, is_super_long_or_wide,
is_skinny_mask, bbox_from_mask, resize_mask_with_unique_label
"""
from __future__ import annotations

from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image


def keep_largest_component(mask: np.ndarray) -> np.ndarray:
    """保留二值 mask 中最大连通分量，其余清零。"""
    if mask.sum() == 0:
        return mask
    mask_u8 = (mask > 0).astype(np.uint8)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if num_labels <= 1:
        return mask
    # 找到面积最大的 label (排除 background=0)
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = 1 + int(np.argmax(areas))
    out = (labels == largest).astype(mask.dtype)
    return out


def bbox_from_mask(mask: np.ndarray) -> dict:
    """计算 mask 的归一化 bbox 比例字典 {x, y, w, h} (相对值 0-1)。"""
    ys, xs = np.where(mask > 0)
    if len(ys) == 0:
        return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    H, W = mask.shape[:2]
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    return {
        "x": float(x0) / W,
        "y": float(y0) / H,
        "w": float(x1 - x0 + 1) / W,
        "h": float(y1 - y0 + 1) / H,
    }


def is_super_long_or_wide(mask: np.ndarray, obj_id: int, ratio: float = 4.0) -> bool:
    """若 mask 的 bbox 宽高比超过 ratio，判定为"超长/超宽"伪补全。"""
    bbox = bbox_from_mask(mask)
    if bbox["w"] == 0 or bbox["h"] == 0:
        return True
    ar = max(bbox["w"] / max(bbox["h"], 1e-6), bbox["h"] / max(bbox["w"], 1e-6))
    return ar > ratio


def is_skinny_mask(mask: np.ndarray, threshold: int = 5) -> bool:
    """mask 主体过窄（连通分量最窄处 < threshold 像素）时判定为 skinny。"""
    if mask.sum() == 0:
        return True
    coords = np.column_stack(np.where(mask > 0))
    if len(coords) < 20:
        return True
    ys = coords[:, 0]
    xs = coords[:, 1]
    # 用每个 y 行的宽度估计
    widths = []
    for y in np.unique(ys):
        row = xs[ys == y]
        widths.append(row.max() - row.min() + 1)
    return min(widths) < threshold


def resize_mask_with_unique_label(
    mask: np.ndarray,
    target_h: int,
    target_w: int,
    obj_id: int,
) -> np.ndarray:
    """将 mask resize 到 (target_h, target_w) 并填充为 obj_id。"""
    if mask.ndim == 3:
        mask = mask[..., 0]
    resized = cv2.resize(
        (mask > 0).astype(np.uint8),
        (target_w, target_h),
        interpolation=cv2.INTER_NEAREST,
    )
    return (resized * obj_id).astype(np.uint8)


def mask_to_pil(mask: np.ndarray) -> Image.Image:
    """mask -> 带 DAVIS 调色板的 P 模式 PIL Image。"""
    from .mask_painter import DAVIS_PALETTE
    pil = Image.fromarray(mask.astype(np.uint8)).convert("P")
    pil.putpalette(DAVIS_PALETTE)
    return pil
