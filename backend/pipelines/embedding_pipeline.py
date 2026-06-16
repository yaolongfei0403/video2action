"""EmbeddingPipeline - 文本向量化

真实模式：Qwen3-Embedding
降级模式：sentence-transformers 多语种 MiniLM (复用 stub_client._Encoder)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

from ..config import get_config
from ..vector.stub_client import _Encoder

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """文本向量化 Pipeline。

    接口：
        ep = EmbeddingPipeline()
        vec = ep.encode(["text1", "text2"])  # (N, D)
    """

    def __init__(self) -> None:
        self.cfg = get_config().embedding
        self._qwen_model = None
        self._encoder = _Encoder(model_name=self.cfg.fallback_model)
        self.mode = "stub"
        self._try_load_qwen()

    def _try_load_qwen(self) -> None:
        """尝试加载 Qwen3-Embedding；checkpoint 缺失则降级。"""
        try:
            # 检查 checkpoint 路径是否存在
            import os
            if self.cfg.model_path and not os.path.exists(self.cfg.model_path):
                raise FileNotFoundError(f"Qwen3-Embedding path missing: {self.cfg.model_path}")
            from transformers import AutoModel, AutoTokenizer
            import torch

            logger.info(f"Loading Qwen3-Embedding from {self.cfg.model_path}")
            self._qwen_tokenizer = AutoTokenizer.from_pretrained(self.cfg.model_path)
            self._qwen_model = AutoModel.from_pretrained(self.cfg.model_path)
            if torch.cuda.is_available() and self.cfg.device == "cuda":
                self._qwen_model = self._qwen_model.cuda()
            self._qwen_model.eval()
            self.mode = "real"
            logger.info("Qwen3-Embedding loaded (real mode)")
        except Exception as e:
            logger.warning(
                f"Qwen3-Embedding unavailable: {e}; using sentence-transformers fallback"
            )
            self._qwen_model = None
            self.mode = "stub"

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.mode == "real" and self._qwen_model is not None:
            try:
                return self._qwen_encode(texts)
            except Exception as e:
                logger.warning(f"Qwen3 inference failed ({e}); falling back to stub")
        return self._encoder.encode(texts)

    def _qwen_encode(self, texts: list[str]) -> np.ndarray:
        import torch

        inputs = self._qwen_tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        )
        if torch.cuda.is_available() and self.cfg.device == "cuda":
            inputs = {k: v.cuda() for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self._qwen_model(**inputs)
        # 使用 last_hidden_state 的 mean pooling
        hidden = outputs.last_hidden_state
        mask = inputs["attention_mask"].unsqueeze(-1).float()
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-6)
        pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return pooled.cpu().numpy().astype(np.float32)

    @property
    def dim(self) -> int:
        if self.mode == "real":
            return int(getattr(self._qwen_model.config, "hidden_size", self.cfg.dim))
        return self.cfg.dim
