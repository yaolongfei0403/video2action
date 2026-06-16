"""Visualization utilities (rebuilt from app.py usage).

原 app.py 引用：draw_point_marker, draw_keypoints_with_index
"""
from __future__ import annotations

from typing import Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def draw_point_marker(
    image: Image.Image,
    x: int,
    y: int,
    point_type: str = "positive",
    radius: int = 6,
) -> Image.Image:
    """在 PIL Image 上绘制 + / - 标记点。"""
    image = image.convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    point_type = point_type.lower()
    if point_type == "positive":
        color_edge = (16, 185, 129, 255)   # brand-green
        color_fill = (16, 185, 129, 90)
        sign_color = (255, 255, 255, 255)
    else:
        color_edge = (239, 68, 68, 255)    # brand-red
        color_fill = (239, 68, 68, 90)
        sign_color = (255, 255, 255, 255)

    # outer ring
    draw.ellipse(
        (x - radius * 2, y - radius * 2, x + radius * 2, y + radius * 2),
        outline=color_edge,
        width=2,
    )
    # inner fill
    draw.ellipse(
        (x - radius, y - radius, x + radius, y + radius),
        fill=color_fill,
    )

    # sign
    if point_type == "positive":
        draw.line((x - radius + 2, y, x + radius - 2, y), fill=sign_color, width=2)
        draw.line((x, y - radius + 2, x, y + radius - 2), fill=sign_color, width=2)
    else:
        draw.line((x - radius + 2, y, x + radius - 2, y), fill=sign_color, width=2)

    out = Image.alpha_composite(image, overlay)
    return out.convert("RGB")


def draw_keypoints_with_index(
    image: np.ndarray,
    keypoints,
    radius: int = 3,
    point_color=(0, 255, 0),
    text_color=(255, 255, 255),
    text_scale: float = 0.4,
    text_thickness: int = 1,
    offset=(5, -5),
) -> np.ndarray:
    """在 numpy image 上绘制带索引的关键点（OpenCV 字体）。

    与 app.py 中实现保持完全一致。
    """
    out = image.copy()
    H, W = out.shape[:2]

    if hasattr(keypoints, "detach"):
        kps = keypoints.detach().cpu().float().numpy()
    else:
        kps = np.asarray(keypoints, dtype=np.float32)

    if kps.ndim != 2 or kps.shape[1] != 2:
        raise ValueError(f"keypoints must be (N,2), got {kps.shape}")

    for i, (x, y) in enumerate(kps):
        if not np.isfinite(x) or not np.isfinite(y):
            continue
        xi, yi = int(round(float(x))), int(round(float(y)))
        if 0 <= xi < W and 0 <= yi < H:
            cv2.circle(out, (xi, yi), radius, point_color, -1, cv2.LINE_AA)
            cv2.putText(
                out, str(i),
                (xi + offset[0], yi + offset[1]),
                cv2.FONT_HERSHEY_SIMPLEX,
                text_scale, text_color, text_thickness,
                cv2.LINE_AA,
            )
    return out
