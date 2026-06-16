"""SAM-3 Video Tracking Pipeline (含 stub 降级).

真实模式：调用外部 SAM-3 模型（predictor.add_new_points_or_box / propagate_in_video）
降级模式：基于 OpenCV MOG2 背景减除 + 形态学后处理
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class SAM3Pipeline:
    """视频目标追踪与 Mask 传播。

    真实模式接口（与 app.py 保持一致）：
        - add_new_points_or_box(inference_state, frame_idx, obj_id, points, labels)
        - propagate_in_video(inference_state, start_frame_idx, max_frame_num_to_track, reverse)
    """

    def __init__(self) -> None:
        self.cfg = None
        self._predictor = None
        self._model = None
        self.mode = "stub"
        self._try_load_real_model()

    def _try_load_real_model(self) -> None:
        try:
            from ..config import get_config
            self.cfg = get_config().sam3
            if not os.path.exists(self.cfg.ckpt_path):
                raise FileNotFoundError(f"SAM-3 checkpoint not found: {self.cfg.ckpt_path}")
            # 真实加载路径（保留接口，依赖外部 SDK）
            from models.sam3.sam3.model_builder import build_sam3_video_model  # type: ignore

            logger.info(f"Loading SAM-3 from {self.cfg.ckpt_path}")
            self._model = build_sam3_video_model(checkpoint_path=self.cfg.ckpt_path)
            self._predictor = self._model.tracker
            self._predictor.backbone = self._model.detector.backbone
            self.mode = "real"
            logger.info("SAM-3 loaded (real mode)")
        except Exception as e:
            logger.warning(
                f"SAM-3 unavailable: {e}; using OpenCV MOG2 fallback"
            )
            self._model = None
            self._predictor = None
            self.mode = "stub"

    # ============== 真实 API ==============

    def init_state(self, video_path: str) -> dict[str, Any]:
        """初始化 video inference state。"""
        if self.mode == "real":
            return self._predictor.init_state(video_path=video_path)
        # stub: 加载视频元信息
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return {
            "video_path": video_path,
            "fps": fps,
            "total_frames": total,
            "video_width": w,
            "video_height": h,
            "frames": [],  # 缓存所有帧
            "points": {},  # {obj_id: [(frame, x, y, type)]}
            "bg_subtractor": cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=32),
        }

    def add_new_points_or_box(
        self,
        inference_state: dict[str, Any],
        frame_idx: int,
        obj_id: int,
        points: np.ndarray,
        labels: np.ndarray,
    ) -> tuple[Any, list[int], Any, np.ndarray]:
        """注册一次点击标注，返回当前帧 mask。

        Returns: (_, out_obj_ids, low_res_masks, video_res_masks)
        """
        if self.mode == "real":
            return self._predictor.add_new_points_or_box(
                inference_state, frame_idx=frame_idx, obj_id=obj_id,
                points=points, labels=labels,
            )
        return self._stub_click(inference_state, frame_idx, obj_id, points, labels)

    def propagate_in_video(
        self,
        inference_state: dict[str, Any],
        start_frame_idx: int = 0,
        max_frame_num_to_track: int = 1800,
        reverse: bool = False,
        propagate_preflight: bool = True,
    ) -> Any:
        """视频传播，返回 (frame_idx, obj_ids, low_res, video_res, scores, iou) 的迭代器。"""
        if self.mode == "real":
            return self._predictor.propagate_in_video(
                inference_state, start_frame_idx=start_frame_idx,
                max_frame_num_to_track=max_frame_num_to_track,
                reverse=reverse, propagate_preflight=propagate_preflight,
            )
        return self._stub_propagate(inference_state, start_frame_idx, max_frame_num_to_track, reverse)

    def clear_all_points_in_video(self, inference_state: dict[str, Any]) -> None:
        if self.mode == "real":
            self._predictor.clear_all_points_in_video(inference_state)
        inference_state["points"] = {}

    # ============== Stub 实现 ==============

    def _stub_click(
        self,
        state: dict[str, Any],
        frame_idx: int,
        obj_id: int,
        points: np.ndarray,
        labels: np.ndarray,
    ) -> tuple[None, list[int], None, np.ndarray]:
        """stub: 用背景减除 + 颜色相似度做多提示点 flood fill。

        忠实复现 app.py:on_click 的累积语义:
        - points 可能是归一化 [0,1] (来自 on_click 归一化) 或绝对像素
        - 多个正向点都作为种子, 对每个种子独立 flood fill 后取并集
        - 多个负向点都作为"挖洞"点
        - 形态学后处理 (闭 + 开)
        """
        H, W = state["video_height"], state["video_width"]
        if not state.get("frames"):
            self._load_all_frames(state)
        frame = state["frames"][frame_idx]
        bg_mask = state["bg_subtractor"].apply(frame)

        # 1) 解析 points: 支持 [0,1] 归一化和绝对像素两种
        pts_arr = np.asarray(points)
        lbs_arr = np.asarray(labels, dtype=np.int32)
        if pts_arr.size > 0 and float(pts_arr.max()) <= 1.5:
            # 归一化坐标 → 像素
            pts_arr = (pts_arr.astype(np.float32) * np.array([W, H], dtype=np.float32)).astype(np.int32)
        else:
            # 已经是像素坐标 → 强制 int32 (下游 _flood_grow 用作 numpy 索引)
            pts_arr = pts_arr.astype(np.int32)

        seeds_pos = [(int(p[0]), int(p[1])) for p, l in zip(pts_arr, lbs_arr) if int(l) == 1]
        seeds_neg = [(int(p[0]), int(p[1])) for p, l in zip(pts_arr, lbs_arr) if int(l) == 0]

        # 2) 多正向点: 每个种子独立 flood fill, 取并集
        mask = np.zeros((H, W), dtype=np.uint8)
        for seed in seeds_pos:
            if not (0 <= seed[0] < W and 0 <= seed[1] < H):
                continue
            sub = self._flood_grow(frame, bg_mask, seed, [])
            mask = cv2.bitwise_or(mask, sub)

        # 3) 负向点: 挖洞 (排除区域)
        for nx, ny in seeds_neg:
            if 0 <= nx < W and 0 <= ny < H:
                cv2.circle(mask, (nx, ny), 30, 0, -1)

        # 4) 形态学后处理
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        # 5) 存 obj -> prompts 历史 (供 propagate 使用)
        state["points"].setdefault(obj_id, {})[frame_idx] = (
            [tuple(p) for p in pts_arr.tolist()],
            [int(l) for l in lbs_arr.tolist()],
        )

        return None, [obj_id], None, mask[None, None, :, :].astype(np.float32)

    def _stub_propagate(
        self,
        state: dict[str, Any],
        start_frame_idx: int,
        max_frames: int,
        reverse: bool,
    ):
        """stub: 简单向前/向后传播 mask 跟踪 bg。

        与 on_click 的新结构对齐: state["points"][obj_id][frame_idx] = (pts, lbs)
        """
        if not state.get("frames"):
            self._load_all_frames(state)

        H, W = state["video_height"], state["video_width"]
        total = min(state["total_frames"], start_frame_idx + max_frames)
        prev_mask = None
        obj_id = next(iter(state["points"].keys()), 1)
        # 找出该 obj 的首个有 prompts 的 frame (作为种子)
        first_prompt_frame = None
        if obj_id in state["points"]:
            for fi in sorted(state["points"][obj_id].keys()):
                if state["points"][obj_id][fi]:
                    first_prompt_frame = fi
                    break

        for idx in range(start_frame_idx, total):
            frame = state["frames"][idx]
            bg_mask = state["bg_subtractor"].apply(frame)

            if idx == start_frame_idx and first_prompt_frame is not None and obj_id in state["points"]:
                # 第一次: 从首个有 prompts 的 frame 拿到所有正向点, flood fill
                pts_lbs = state["points"][obj_id][first_prompt_frame]
                pts, lbs = pts_lbs
                pos_seeds = [p for p, l in zip(pts, lbs) if int(l) == 1]
                neg_seeds = [p for p, l in zip(pts, lbs) if int(l) == 0]
                mask = np.zeros((H, W), dtype=np.uint8)
                for seed in pos_seeds:
                    if not (0 <= seed[0] < W and 0 <= seed[1] < H):
                        continue
                    sub = self._flood_grow(frame, bg_mask, tuple(seed), [])
                    mask = cv2.bitwise_or(mask, sub)
                for nx, ny in neg_seeds:
                    if 0 <= nx < W and 0 <= ny < H:
                        cv2.circle(mask, (nx, ny), 30, 0, -1)
            else:
                # 跟踪: 用 prev_mask + 帧间相关性
                mask = self._track_mask(frame, bg_mask, prev_mask)

            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
            prev_mask = mask.copy()

            yield (
                idx, [obj_id],
                None,
                mask[None, None, :, :].astype(np.float32),
                np.array([0.85]),
                np.array([0.85]),
            )

    def _load_all_frames(self, state: dict[str, Any]) -> None:
        """缓存所有帧到内存（stub 模式）。"""
        cap = cv2.VideoCapture(state["video_path"])
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(f)
        cap.release()
        state["frames"] = frames
        state["total_frames"] = len(frames)

    def _flood_grow(
        self,
        frame: np.ndarray,
        bg_mask: np.ndarray,
        seed: tuple[int, int],
        neg_seeds: list[tuple[int, int]],
    ) -> np.ndarray:
        """基于颜色相似度 + 背景 mask 的 flood fill。"""
        H, W = frame.shape[:2]
        x, y = seed
        if not (0 <= x < W and 0 <= y < H):
            return np.zeros((H, W), dtype=np.uint8)

        seed_color = frame[y, x].astype(np.int32)
        diff = np.linalg.norm(frame.astype(np.int32) - seed_color, axis=2)
        color_mask = (diff < 60).astype(np.uint8) * 255

        # 与背景 mask 取交集
        fg_mask = cv2.bitwise_and(color_mask, 255 - bg_mask)

        # floodFill from seed
        ff_mask = np.zeros((H + 2, W + 2), dtype=np.uint8)
        cv2.floodFill(fg_mask, ff_mask, (x, y), 255)
        out = ff_mask[1:-1, 1:-1]

        # 排除负向点
        for nx, ny in neg_seeds:
            cv2.circle(out, (nx, ny), 30, 0, -1)
        return out

    def _track_mask(
        self,
        frame: np.ndarray,
        bg_mask: np.ndarray,
        prev_mask: Optional[np.ndarray],
    ) -> np.ndarray:
        """基于光流的简单 mask 跟踪。"""
        if prev_mask is None or prev_mask.sum() == 0:
            return np.zeros_like(bg_mask)

        H, W = frame.shape[:2]
        # 形态学 + 重采样
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        # 简单：保留 prev_mask 与 bg 前景的交集
        fg_only = cv2.bitwise_and(255 - bg_mask, np.ones_like(bg_mask) * 255)
        out = cv2.bitwise_and(prev_mask, fg_only)
        out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, kernel)
        return out
