"""Rough Cut Engine - 自动化粗切

流水线（与原始 processor.py 同构，对应 PRD 3.1.2）：
    1. PySceneDetect 镜头分割（ContentDetector）
    2. 时长过滤：MIN_DURATION (5s) ≤ 时长 ≤ MAX_DURATION (600s)
    3. OpenCV 像素帧差：缩到 320×180 灰度 + 高斯模糊 + 二值化 + 变动占比
    4. 动静双门限：< 0.02 静态丢弃，> 0.85 剧烈抖动丢弃，0.02-0.85 为「甜区」
    5. 可选：FFmpeg -c copy 流式裁剪（不改写原片）

设计取舍：
- 镜头分割：先按镜头切再判动作，单镜头内动作最稳定；整段无切点时 fallback 为整段。
- 像素帧差：用「缩图 + 灰度 + 模糊 + 二值化」中位数代替 Farneback 光流，单帧 < 1ms。
- 抽帧：MOTION_SAMPLE_FPS=2，平衡速度与覆盖率。
- 聚合：取中位数而非均值，抗首尾异常。
- 裁剪：FFmpeg -c copy，毫秒级完成；产物按 `{stem}__{start}-{end}__{uuid12}.mp4` 命名。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ============== 常量 ==============

# 动静双门限 - 甜区在 [0.02, 0.85]
DEFAULT_MOTION_LOW = 0.02   # 低于此 → 静态（PPT / 定格 / 黑屏）
DEFAULT_MOTION_HIGH = 0.85  # 高于此 → 剧烈抖动 / 转场风暴

# 镜头分割
DEFAULT_SCENE_THRESHOLD = 27.0
DEFAULT_MIN_SCENE_DURATION = 2.0  # 秒

# 时长边界
DEFAULT_MIN_DURATION = 5.0
DEFAULT_MAX_DURATION = 600.0

# 抽帧
DEFAULT_MOTION_SAMPLE_FPS = 2.0
DEFAULT_RESIZE_W = 320
DEFAULT_RESIZE_H = 180
DEFAULT_DIFF_THRESHOLD = 25

# SceneManager 使用 `min_scene_len` 帧数
_FRAME_RATE_FOR_SCENE_LEN = 15.0  # 镜头最小帧数 = min_scene_duration * 15


# ============== 数据结构 ==============


@dataclass
class CandidateClip:
    """粗切候选片段。

    字段与旧版保持完全一致，保证 store/api/前端不破坏：
      - start_frame / end_frame: 帧号
      - score: 0~1 综合分（= 动静归一化分）
      - motion_score: 像素变动占比 [0, 1]
      - person_score: 保留字段（人体检测被取消后置 0.0，前端仍可读）
    """
    start_frame: int
    end_frame: int
    score: float
    motion_score: float
    person_score: float = 0.0
    # 内部元数据，不写进 dataclass 序列化以保持与旧版兼容
    cut_path: str = ""
    source_start_sec: float = 0.0
    source_end_sec: float = 0.0


@dataclass
class _Scene:
    """一个镜头的帧区间与时间区间。"""
    start_frame: int
    end_frame: int
    start_sec: float
    end_sec: float


# ============== 引擎 ==============


class RoughCutEngine:
    """自动粗切引擎（detect → cut）。"""

    def __init__(
        self,
        # 镜头分割
        scene_threshold: float = DEFAULT_SCENE_THRESHOLD,
        min_scene_duration: float = DEFAULT_MIN_SCENE_DURATION,
        # 时长过滤
        min_duration_sec: float = DEFAULT_MIN_DURATION,
        max_duration_sec: float = DEFAULT_MAX_DURATION,
        # 动态检测
        motion_sample_fps: float = DEFAULT_MOTION_SAMPLE_FPS,
        motion_low_threshold: float = DEFAULT_MOTION_LOW,
        motion_high_threshold: float = DEFAULT_MOTION_HIGH,
        diff_threshold: int = DEFAULT_DIFF_THRESHOLD,
        resize_w: int = DEFAULT_RESIZE_W,
        resize_h: int = DEFAULT_RESIZE_H,
        # 输出
        output_dir: str = "./outputs/rough",
    ):
        self.scene_threshold = scene_threshold
        self.min_scene_duration = min_scene_duration
        self.min_duration_sec = min_duration_sec
        self.max_duration_sec = max_duration_sec
        self.motion_sample_fps = motion_sample_fps
        self.motion_low_threshold = motion_low_threshold
        self.motion_high_threshold = motion_high_threshold
        self.diff_threshold = diff_threshold
        self.resize_w = resize_w
        self.resize_h = resize_h
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # SceneDetector 延迟导入
        self._scene_detector = None
        self._try_init_scene_detector()

    # ---------- 兼容性字段（旧版 API 在实例上改这两个属性）----------

    @property
    def min_score(self) -> float:
        return self.motion_low_threshold

    @min_score.setter
    def min_score(self, value: float) -> None:
        # 旧版「综合分 ≥ 0.4」等价于「动静 ≥ low_threshold」
        # 旧 API 传的是 [0,1] 综合分，这里用线性映射近似保留语义
        self.motion_low_threshold = max(0.0, min(1.0, value))

    # ---------- 内部工具 ----------

    def _try_init_scene_detector(self) -> None:
        """尝试加载 PySceneDetect；不可用时退化为「整段一个镜头」。"""
        try:
            from scenedetect import SceneManager, ContentDetector  # type: ignore

            self._scene_detector = (SceneManager, ContentDetector)
            logger.info("PySceneDetect ContentDetector loaded")
        except Exception as e:  # pragma: no cover - 依赖缺失
            logger.warning(f"PySceneDetect unavailable ({e}); fallback to single-shot mode")
            self._scene_detector = None

    @staticmethod
    def _ffprobe_duration(video_path: str) -> float:
        """用 ffprobe 取总时长（秒）。失败时返回 0。"""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return 0.0
        try:
            out = subprocess.check_output(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", video_path],
                stderr=subprocess.DEVNULL, timeout=10,
            )
            return float(out.decode().strip())
        except Exception:
            return 0.0

    @staticmethod
    def _video_meta(video_path: str) -> tuple[float, int, int]:
        """返回 (fps, total_frames, duration_sec)。"""
        cap = cv2.VideoCapture(video_path)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total <= 0:
                total = 0
        finally:
            cap.release()
        if total <= 0:
            duration = RoughCutEngine._ffprobe_duration(video_path)
            total = int(duration * fps) if duration > 0 else 0
        duration = total / fps if total > 0 else 0.0
        return fps, total, duration

    # ---------- 1. 镜头分割 ----------

    def detect_scenes(self, video_path: str) -> list[_Scene]:
        """基于 PySceneDetect 把视频切成镜头。

        兜底：整段没有切点 → 把整段视作 1 个镜头（前提是时长合法）。
        """
        fps, total, duration = self._video_meta(video_path)
        if total <= 0 or fps <= 0:
            return []

        if self._scene_detector is None:
            # 无 scenedetect → 单镜头
            return [_Scene(0, total, 0.0, duration)]

        SceneManager, ContentDetector = self._scene_detector
        sm = SceneManager()
        sm.add_detector(ContentDetector(
            threshold=self.scene_threshold,
            min_scene_len=int(self.min_scene_duration * _FRAME_RATE_FOR_SCENE_LEN),
        ))
        try:
            from scenedetect import open_video  # type: ignore
            sm.detect_scenes(open_video(video_path), show_progress=False)
            scene_list = sm.get_scene_list(start_in_scene=True)
        except Exception as e:
            logger.warning(f"SceneDetect failed ({e}); fallback to single-shot mode")
            return [_Scene(0, total, 0.0, duration)]

        if not scene_list:
            # 没有明显切点 → 兜底为整段
            return [_Scene(0, total, 0.0, duration)]

        scenes: list[_Scene] = []
        for (s_tc, e_tc) in scene_list:
            # scenedetect 0.7+ 推荐 frame_num；旧版回退到 get_frames()
            if hasattr(s_tc, "frame_num"):
                s_frame = int(s_tc.frame_num)
                e_frame = int(e_tc.frame_num)
            else:
                s_frame = int(s_tc.get_frames())
                e_frame = int(e_tc.get_frames())
            s_sec = s_frame / fps
            e_sec = e_frame / fps
            scenes.append(_Scene(s_frame, e_frame, s_sec, e_sec))
        return scenes

    # ---------- 2+3+4. 时长过滤 + 像素帧差 + 动静双门限 ----------

    def measure_motion(
        self,
        video_path: str,
        scene: _Scene,
    ) -> float:
        """对单个镜头计算「像素变动占比」中位数。

        算法：
        1) 按 motion_sample_fps 抽帧
        2) 缩到 (resize_w, resize_h) 灰度
        3) 高斯模糊降噪
        4) 帧差 → 二值化（diff_threshold）→ 变动像素占比
        5) 取中位数（抗首尾异常）
        """
        if scene.end_frame <= scene.start_frame:
            return 0.0
        fps, _, _ = self._video_meta(video_path)
        if fps <= 0:
            fps = 30.0

        cap = cv2.VideoCapture(video_path)
        try:
            # 抽帧策略：固定步长跳帧
            stride = max(int(round(fps / max(self.motion_sample_fps, 0.1))), 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, scene.start_frame)

            ratios: list[float] = []
            prev_gray: Optional[np.ndarray] = None
            cur = scene.start_frame
            while cur < scene.end_frame:
                ok, frame = cap.read()
                if not ok:
                    break
                small = cv2.resize(
                    frame, (self.resize_w, self.resize_h), interpolation=cv2.INTER_AREA
                )
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (5, 5), 0)
                if prev_gray is not None:
                    diff = cv2.absdiff(prev_gray, gray)
                    _, th = cv2.threshold(
                        diff, self.diff_threshold, 255, cv2.THRESH_BINARY
                    )
                    ratio = float(np.count_nonzero(th)) / float(th.size)
                    ratios.append(ratio)
                prev_gray = gray
                cur += stride
                # 跳跃式抽帧：把 cap 拨到下一采样点（比逐帧 read 快得多）
                if stride > 1 and cur < scene.end_frame:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, cur)
        finally:
            cap.release()

        if not ratios:
            return 0.0
        return float(np.median(ratios))

    # ---------- 编排：detect ----------

    def detect(
        self,
        video_path: str,
        max_frames: Optional[int] = None,  # 保留参数以兼容旧 API
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> list[CandidateClip]:
        """对一段视频返回粗切候选。

        与旧 API 兼容：返回 list[CandidateClip]，字段不变。
        `max_frames` 仅作为截断提示；流水线主体是 detect_scenes + measure_motion。
        """
        del max_frames  # 当前实现不再使用，未来可加 hard cap

        scenes = self.detect_scenes(video_path)
        if not scenes:
            return []

        fps, total, _ = self._video_meta(video_path)
        candidates: list[CandidateClip] = []
        for i, sc in enumerate(scenes):
            duration = sc.end_sec - sc.start_sec
            # 时长过滤：5-600s
            if duration < self.min_duration_sec or duration > self.max_duration_sec:
                if progress_cb:
                    progress_cb(i + 1, len(scenes))
                continue

            motion = self.measure_motion(video_path, sc)
            # 动静双门限
            if motion < self.motion_low_threshold or motion > self.motion_high_threshold:
                if progress_cb:
                    progress_cb(i + 1, len(scenes))
                continue

            # score：把 motion 映射到 [0, 1]（甜区内单调递增）
            score = min(1.0, max(0.0, motion / 0.5))
            cand = CandidateClip(
                start_frame=sc.start_frame,
                end_frame=sc.end_frame,
                score=score,
                motion_score=motion,
                person_score=0.0,  # 旧字段，已弃用
            )
            cand.source_start_sec = sc.start_sec
            cand.source_end_sec = sc.end_sec
            candidates.append(cand)

            if progress_cb:
                progress_cb(i + 1, len(scenes))

        logger.info(
            f"RoughCut: {len(scenes)} scenes → {len(candidates)} candidates "
            f"(sweet zone [{self.motion_low_threshold}, {self.motion_high_threshold}])"
        )
        return candidates

    # ---------- 5. FFmpeg 流式裁剪 ----------

    def cut_clip_ffmpeg(
        self,
        source: str,
        start_sec: float,
        end_sec: float,
        dst: str,
    ) -> str:
        """用 ffmpeg -c copy 把 [start, end] 裁出来。毫秒级完成。

        命名约定（调用方可覆盖 dst）：`{stem}__{start}-{end}__{uuid12}.mp4`
        """
        if not os.path.exists(source):
            raise FileNotFoundError(f"Source video not found: {source}")
        duration = max(0.001, end_sec - start_sec)

        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            cmd = [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{start_sec:.3f}", "-i", source,
                "-t", f"{duration:.3f}",
                "-c", "copy", "-avoid_negative_ts", "make_zero",
                dst,
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=120)
                return dst
            except subprocess.CalledProcessError as e:
                logger.warning(
                    f"ffmpeg -c copy failed ({e.stderr[:200] if e.stderr else e}); "
                    "fallback to re-encode"
                )

        # Fallback: 重新编码（保持产物可用）
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open source: {source}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_sec * fps))
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(dst, fourcc, fps, (w, h))
        end_f = int(end_sec * fps)
        cur_f = int(start_sec * fps)
        while cur_f < end_f:
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)
            cur_f += 1
        cap.release()
        writer.release()
        return dst

    def cut_candidates_to_files(
        self,
        video_path: str,
        candidates: list[CandidateClip],
        output_dir: Optional[str] = None,
    ) -> list[CandidateClip]:
        """把每个候选用 ffmpeg -c copy 裁出来，并把路径写回 cand.cut_path。

        命名：`{stem}__{start_frame}-{end_frame}__{uuid12}.mp4`
        """
        out_dir = Path(output_dir) if output_dir else self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(video_path).stem
        for cand in candidates:
            start = cand.source_start_sec or (cand.start_frame / 30.0)
            end = cand.source_end_sec or (cand.end_frame / 30.0)
            name = f"{stem}__{start:.2f}-{end:.2f}__{uuid.uuid4().hex[:12]}.mp4"
            dst = str(out_dir / name)
            try:
                self.cut_clip_ffmpeg(video_path, start, end, dst)
                cand.cut_path = dst
            except Exception as e:
                logger.error(f"Failed to cut {start}-{end}: {e}")
                cand.cut_path = ""
        return candidates
