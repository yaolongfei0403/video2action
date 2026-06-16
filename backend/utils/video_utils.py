"""Video I/O utilities (rebuilt from app.py usage).

原 app.py 引用：read_video_metadata, images_to_mp4, jpg_folder_to_mp4
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image


def read_video_metadata(path: str) -> Tuple[float, int]:
    """读取视频 FPS 与总帧数。"""
    cap = cv2.VideoCapture(path)
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, total


def read_frame_at(path: str, idx: int) -> Optional[Image.Image]:
    """读取视频指定 idx 帧，返回 PIL RGB Image。"""
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(frame)


def get_thumb(path: str) -> Optional[Image.Image]:
    if not os.path.exists(path):
        return None
    return read_frame_at(path, 0)


def images_to_mp4(
    images: List[Union[np.ndarray, Image.Image]],
    output_path: str,
    fps: float = 30.0,
    codec: str = "mp4v",
) -> str:
    """将一组图像序列合成 MP4 视频。"""
    if not images:
        raise ValueError("images list is empty")

    first = images[0]
    if isinstance(first, Image.Image):
        first = np.array(first.convert("RGB"))
    h, w = first.shape[:2]

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*codec)
    writer = cv2.VideoWriter(output_path, fourcc, float(fps), (w, h))
    for img in images:
        if isinstance(img, Image.Image):
            img = np.array(img.convert("RGB"))
        if img.shape[:2] != (h, w):
            img = cv2.resize(img, (w, h))
        writer.write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    writer.release()
    return output_path


def jpg_folder_to_mp4(
    folder: str,
    output_path: str,
    fps: float = 30.0,
    codec: str = "mp4v",
) -> str:
    """将一个 jpg 目录合成 MP4。"""
    jpgs = sorted(Path(folder).glob("*.jpg"))
    if not jpgs:
        # 兼容 png
        jpgs = sorted(Path(folder).glob("*.png"))
    if not jpgs:
        raise FileNotFoundError(f"No images in {folder}")

    images = [np.array(Image.open(p).convert("RGB")) for p in jpgs]
    return images_to_mp4(images, output_path, fps=fps, codec=codec)


def video_duration_str(path: str) -> str:
    """返回 mm:ss 格式时长。"""
    fps, total = read_video_metadata(path)
    if fps <= 0:
        return "00:00"
    sec = total / fps
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def ffmpeg_trim(
    src: str,
    dst: str,
    start: float,
    end: float,
    use_copy: bool = True,
) -> str:
    """用 ffmpeg 精确裁剪视频片段。"""
    import subprocess
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    cmd = ["ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", src]
    if use_copy:
        cmd += ["-c", "copy"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "23"]
    cmd += [dst]
    subprocess.run(cmd, check=True, capture_output=True)
    return dst
