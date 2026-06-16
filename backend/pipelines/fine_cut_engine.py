"""Fine Cut Engine - 精切裁剪

对应 PRD 3.1.3 人工精切。

优化要点（参照原始 processor.py 思路）：
  1. **相对偏移 → 源片绝对时间**：前端发的是相对 clip/candidate 起点的 offset，
     后端换算成 `candidate.start_time + relative_offset` 后在源片上 ffmpeg -c copy。
  2. **ffprobe 真实时长做上界**：兼容 -c copy 关键帧对齐导致文件比声明时长多几十毫秒。
  3. **0.05s 容忍**：用户没怎么动 trim 点时直接复用原文件，省一次 ffmpeg 调用。
  4. **源片优先 / 当前文件兜底**：源片在就用源片（最准、最快）；不在则用当前已切文件。
  5. **产物落 kept/**：不触碰 raw（浏览器可能正占用播放）。
  6. **ffmpeg -c copy 优先**，失败时回退 OpenCV 重新编码。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, Optional

import cv2

logger = logging.getLogger(__name__)


# ============== 常量 ==============

# 精切后产物的最小长度 - 与粗切保持一致
MIN_DURATION = 5.0

# 用户"几乎没动"的容忍度（秒）：start/tolerance 与 end/tolerance 都在这个范围内时跳过重切
TRIM_TOLERANCE = 0.05


# ============== 引擎 ==============


class FineCutEngine:
    """精切引擎。

    输出目录布局：
        <output_dir>/
            kept/         # 精切最终产物（用户点头的最终素材）
            {task_id}/    # 旧版/trim 接口的 per-task 输出（向后兼容）
                clips/
    """

    def __init__(self, output_dir: str = "./outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.kept_dir = self.output_dir / "kept"
        self.kept_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 工具：ffprobe 真实时长 ----------

    @staticmethod
    def ffprobe_duration(path: str) -> float:
        """用 ffprobe 取真实时长（秒）。

        比 cv2.VideoCapture 准：cv2 拿到的是封装层声明的帧数 / fps，
        实际解码后的最后一帧可能略超出，ffprobe 拿到的是容器真实时长。
        """
        if not Path(path).exists():
            return 0.0
        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            try:
                out = subprocess.check_output(
                    [
                        ffprobe, "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        path,
                    ],
                    stderr=subprocess.DEVNULL, timeout=10,
                )
                return float(out.decode().strip())
            except Exception:
                pass
        # 兜底：cv2
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return 0.0
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()
        return total / fps if fps > 0 else 0.0

    # ---------- 旧版接口：trim()（保留向后兼容）----------

    def trim(
        self,
        src: str,
        start_sec: float,
        end_sec: float,
        out_name: Optional[str] = None,
        use_copy: bool = True,
    ) -> dict[str, Any]:
        """裁剪视频片段（绝对时间，旧版 API）。"""
        if not os.path.exists(src):
            raise FileNotFoundError(f"Source video not found: {src}")

        out_name = out_name or f"clip_{int(start_sec * 1000)}_{int(end_sec * 1000)}.mp4"
        dst = str(self.output_dir / out_name)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start_sec:.3f}", "-i", src,
                "-t", f"{max(0.001, end_sec - start_sec):.3f}",
            ]
            if use_copy:
                cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
            else:
                cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac"]
            cmd += [dst]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                return {
                    "path": dst,
                    "start": start_sec,
                    "end": end_sec,
                    "duration": end_sec - start_sec,
                }
            except subprocess.CalledProcessError as e:
                logger.warning(
                    f"ffmpeg failed ({e.stderr[:200] if e.stderr else e}); fallback to re-encode"
                )

        # 兜底 OpenCV 重新编码
        return self._trim_opencv(src, start_sec, end_sec, dst)

    def _trim_opencv(
        self, src: str, start_sec: float, end_sec: float, dst: str
    ) -> dict[str, Any]:
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open source: {src}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        start_f = int(start_sec * fps)
        end_f = int(end_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(dst, fourcc, fps, (w, h))
        for _ in range(end_f - start_f):
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)
        cap.release()
        writer.release()
        return {
            "path": dst,
            "start": start_sec,
            "end": end_sec,
            "duration": end_sec - start_sec,
        }

    # ---------- 新版：keep_clip()（精切决策主入口）----------

    def keep_clip(
        self,
        source_video: str,         # 源片（原始长视频）绝对路径
        source_duration: float,    # 源片总时长（秒），来自 VideoSource.duration
        candidate_start: float,    # 粗切候选的绝对起点（源片中）
        candidate_end: float,      # 粗切候选的绝对终点（源片中）
        relative_start: float,     # 精切起点（相对粗切起点的偏移，秒）
        relative_end: float,       # 精切终点（相对粗切起点的偏移，秒）
        clip_id: str = "",         # 用于命名（candidate_id 或 clip_id）
        fallback_path: str = "",   # 源片不可用时兜底（粗切产物文件）
    ) -> dict[str, Any]:
        """精切：把「相对偏移」换算成「源片绝对时间」，在源片上 ffmpeg -c copy。

        Parameters
        ----------
        source_video : 源片路径（原始长视频）。优先在此文件上裁剪。
        source_duration : 源片总时长（用于边界校验）。
        candidate_start / candidate_end : 粗切候选在源片中的绝对时间区间。
        relative_start / relative_end : 精切相对粗切起点的偏移（必须 0 <= rel < candidate_duration）。
        clip_id : 命名时携带，便于追溯 candidate 或 clip。
        fallback_path : source_video 不可用时的兜底（一般是粗切产物 .mp4）。

        Returns
        -------
        dict with keys:
            trimmed, skipped, output_path, start_time, end_time, duration,
            relative_start, relative_end, source, candidate

        Raises
        ------
        ValueError : 边界/参数非法
        FileNotFoundError : 源片与兜底都不可用
        """
        # 1) 边界校验
        if relative_start < 0 or relative_end <= relative_start:
            raise ValueError(
                f"非法 trim 范围: [{relative_start:.2f}, {relative_end:.2f}]"
            )
        candidate_duration = candidate_end - candidate_start
        if relative_start > candidate_duration + TRIM_TOLERANCE:
            raise ValueError(
                f"trim 起点 {relative_start:.2f} 超出候选长度 {candidate_duration:.2f}"
            )
        if relative_end > candidate_duration + TRIM_TOLERANCE:
            raise ValueError(
                f"trim 终点 {relative_end:.2f} 超出候选长度 {candidate_duration:.2f}"
            )

        # 2) 相对 → 绝对
        abs_start = candidate_start + relative_start
        abs_end = candidate_start + relative_end
        duration = abs_end - abs_start

        # 3) 源片上界校验（用源片 duration 兜底；ffprobe 真实值可选）
        if source_duration > 0 and abs_end > source_duration + TRIM_TOLERANCE:
            raise ValueError(
                f"裁剪后超出源片: [{abs_start:.2f}, {abs_end:.2f}] / {source_duration:.2f}"
            )
        if duration < MIN_DURATION:
            raise ValueError(
                f"裁剪后时长 {duration:.2f}s < 最小 {MIN_DURATION}s"
            )

        # 4) 容忍检查：用户没怎么动 → 不重切，kept/ 下不落新文件
        within_tolerance = (
            relative_start <= TRIM_TOLERANCE
            and relative_end >= candidate_duration - TRIM_TOLERANCE
        )

        # 5) 命名：{stem}__trim{start_ms}-{end_ms}[_{clip_id8}]{.mp4}
        src = Path(source_video)
        suffix = src.suffix or ".mp4"
        suffix_tag = f"_{clip_id[:8]}" if clip_id else ""
        new_name = (
            f"{src.stem}__trim{int(relative_start * 1000):06d}-"
            f"{int(relative_end * 1000):06d}{suffix_tag}{suffix}"
        )
        new_path = self.kept_dir / new_name

        base = {
            "trimmed": False,
            "skipped": True,
            "output_path": str(new_path),
            "start_time": abs_start,
            "end_time": abs_end,
            "duration": duration,
            "relative_start": relative_start,
            "relative_end": relative_end,
            "source": str(src),
            "candidate": {"start": candidate_start, "end": candidate_end},
        }

        if within_tolerance:
            logger.info(
                f"keep_clip: within tolerance ({TRIM_TOLERANCE}s), skip re-cut "
                f"rel=[{relative_start:.2f}, {relative_end:.2f}]"
            )
            return base

        # 6) 源片选择：源片优先 → 当前文件兜底
        if src.exists():
            ffmpeg_src, cut_start, cut_end = str(src), abs_start, abs_end
        elif fallback_path and Path(fallback_path).exists():
            logger.info(
                f"keep_clip: source missing ({src}), fallback to {fallback_path}"
            )
            ffmpeg_src = fallback_path
            # 兜底时偏移就是文件自身的时间
            cut_start, cut_end = relative_start, relative_end
        else:
            raise FileNotFoundError(
                f"源片不可用: {source_video} (fallback: {fallback_path or '无'})"
            )

        # 7) 写到 kept/，不触碰 raw
        self._ffmpeg_copy(ffmpeg_src, cut_start, cut_end, str(new_path))

        return {**base, "trimmed": True, "skipped": False, "ffmpeg_src": ffmpeg_src}

    # ---------- 内部：ffmpeg -c copy ----------

    @staticmethod
    def _ffmpeg_copy(src: str, start: float, end: float, dst: str) -> None:
        """ffmpeg -c copy 流式裁剪（毫秒级）。失败时回退 OpenCV 重新编码。"""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start:.3f}", "-i", src,
                "-t", f"{max(0.001, end - start):.3f}",
                "-c", "copy", "-avoid_negative_ts", "make_zero",
                dst,
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                return
            except subprocess.CalledProcessError as e:
                logger.warning(
                    f"ffmpeg -c copy failed ({e.stderr[:200] if e.stderr else e}); "
                    "fallback to re-encode"
                )
        # 兜底 OpenCV
        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open source: {src}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * fps))
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(dst, fourcc, fps, (w, h))
        end_f = int(end * fps)
        for _ in range(end_f - int(start * fps)):
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)
        cap.release()
        writer.release()

    # ---------- 工具：抽帧 ----------

    def extract_frames(
        self,
        src: str,
        start_sec: float,
        end_sec: float,
        out_dir: str,
        stride: int = 1,
    ) -> list[str]:
        """抽帧到 out_dir。"""
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        cap = cv2.VideoCapture(src)
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_f = int(start_sec * fps)
        end_f = int(end_sec * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_f)
        paths: list[str] = []
        idx = 0
        for f in range(start_f, end_f):
            ok, frame = cap.read()
            if not ok:
                break
            if (f - start_f) % stride == 0:
                p = os.path.join(out_dir, f"{idx:08d}.jpg")
                cv2.imwrite(p, frame)
                paths.append(p)
                idx += 1
        cap.release()
        return paths
