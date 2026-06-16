"""Pipeline 单例注册表 - 避免 backend.main ↔ backend.api 循环导入."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import get_config
from .pipelines import (
    DiffusionVASPipeline,
    EmbeddingPipeline,
    FineCutEngine,
    FourDPipeline,
    RoughCutEngine,
    SAM3DBodyPipeline,
    SAM3Pipeline,
    VLMPipeline,
)

_pipelines: dict[str, Any] = {}


def get_pipeline(name: str) -> Any:
    """懒加载 Pipeline 单例。"""
    if name in _pipelines:
        return _pipelines[name]
    cfg = get_config()

    if name == "sam3":
        _pipelines[name] = SAM3Pipeline()
    elif name == "sam3d":
        _pipelines[name] = SAM3DBodyPipeline()
    elif name == "vas":
        _pipelines[name] = DiffusionVASPipeline()
    elif name == "fourd":
        _pipelines[name] = FourDPipeline()
    elif name == "rough_cut":
        _pipelines[name] = RoughCutEngine()
    elif name == "fine_cut":
        _pipelines[name] = FineCutEngine(
            output_dir=str(Path(cfg.runtime.output_dir))
        )
    elif name == "vlm":
        _pipelines[name] = VLMPipeline()
    elif name == "embedding":
        _pipelines[name] = EmbeddingPipeline()
    else:
        raise KeyError(f"Unknown pipeline: {name}")
    return _pipelines[name]


def reset_pipelines() -> None:
    """清空缓存（主要用于测试）。"""
    _pipelines.clear()
