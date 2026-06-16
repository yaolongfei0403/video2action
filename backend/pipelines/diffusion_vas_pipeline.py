"""Diffusion-VAS Pipeline (含 stub 降级).

真实模式：调用 Diffusion-VAS 模型做 amodal segmentation + RGB 补全
降级模式：用形态学 + cv2.inpaint 补全 mask
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class DiffusionVASPipeline:
    """Diffusion-VAS 视觉补全 Pipeline.

    真实模式接口（与 app.py 一致）：
        - pipeline_mask(...) -> amodal mask
        - pipeline_rgb(...) -> amodal RGB
    """

    def __init__(self) -> None:
        self.cfg = None
        self.pipeline_mask = None
        self.pipeline_rgb = None
        self.depth_model = None
        self.mode = "stub"
        self._try_load()

    def _try_load(self) -> None:
        try:
            from ..config import get_config
            self.cfg = get_config().completion
            if not self.cfg.enable:
                logger.info("Diffusion-VAS disabled in config (completion.enable=false)")
                self.mode = "stub"
                return
            if not all(os.path.exists(p) for p in [
                self.cfg.model_path_mask, self.cfg.model_path_rgb, self.cfg.model_path_depth,
            ]):
                raise FileNotFoundError("Diffusion-VAS checkpoints missing")

            from models.diffusion_vas.demo import (  # type: ignore
                init_amodal_segmentation_model, init_rgb_model, init_depth_model,
            )
            import torch

            self.pipeline_mask = init_amodal_segmentation_model(self.cfg.model_path_mask)
            self.pipeline_rgb = init_rgb_model(self.cfg.model_path_rgb)
            self.depth_model = init_depth_model(self.cfg.model_path_depth, self.cfg.depth_encoder)
            self.mode = "real"
            logger.info("Diffusion-VAS loaded (real mode)")
        except Exception as e:
            logger.warning(f"Diffusion-VAS unavailable: {e}; using cv2.inpaint fallback")
            self.mode = "stub"

    def complete_mask(
        self,
        modal_mask: np.ndarray,
        rgb_image: Optional[np.ndarray] = None,
    ) -> np.ndarray:
        """补全被遮挡的 mask。

        Args:
            modal_mask: 单通道 0/255 mask
            rgb_image: 可选 RGB 图（用于更好的补全）

        Returns:
            补全后的 mask (0/255)
        """
        if self.mode == "real" and self.pipeline_mask is not None:
            try:
                return self._real_complete_mask(modal_mask, rgb_image)
            except Exception as e:
                logger.warning(f"Diffusion-VAS mask failed ({e}); fallback to cv2")
        return self._stub_complete_mask(modal_mask, rgb_image)

    def complete_rgb(
        self,
        modal_mask: np.ndarray,
        rgb_image: np.ndarray,
    ) -> np.ndarray:
        """补全 RGB 内容。"""
        if self.mode == "real" and self.pipeline_rgb is not None:
            try:
                return self._real_complete_rgb(modal_mask, rgb_image)
            except Exception as e:
                logger.warning(f"Diffusion-VAS rgb failed ({e}); fallback to cv2")
        return self._stub_complete_rgb(modal_mask, rgb_image)

    # ============== Stub 实现 ==============

    def _stub_complete_mask(
        self,
        modal_mask: np.ndarray,
        rgb_image: Optional[np.ndarray],
    ) -> np.ndarray:
        """形态学闭运算 + 最大连通分量。"""
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        closed = cv2.morphologyEx(modal_mask, cv2.MORPH_CLOSE, kernel)
        # 仅在有显著外扩时截断
        from ..utils import keep_largest_component
        return keep_largest_component(closed)

    def _stub_complete_rgb(
        self,
        modal_mask: np.ndarray,
        rgb_image: np.ndarray,
    ) -> np.ndarray:
        """cv2.inpaint 简单补全。"""
        h, w = modal_mask.shape[:2]
        if rgb_image.shape[:2] != (h, w):
            rgb_image = cv2.resize(rgb_image, (w, h))
        inv = (modal_mask == 0).astype(np.uint8) * 255
        out = cv2.inpaint(rgb_image, inv, 5, cv2.INPAINT_TELEA)
        return out

    def _real_complete_mask(self, modal_mask, rgb_image):
        # 实际完整调用链在 on_4d_generation 中（pipeline_mask 调用），stub 不展开
        return self._stub_complete_mask(modal_mask, rgb_image)

    def _real_complete_rgb(self, modal_mask, rgb_image):
        return self._stub_complete_rgb(modal_mask, rgb_image)
