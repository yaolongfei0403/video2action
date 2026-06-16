"""Backend configuration loader."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "configs" / "body4d.yaml"


class Sam3Config(BaseModel):
    ckpt_path: str
    device: str = "cuda"
    fallback_enabled: bool = True


class Sam3DBodyConfig(BaseModel):
    ckpt_path: str
    mhr_path: str
    fov_path: str
    device: str = "cuda"
    batch_size: int = 8
    fallback_enabled: bool = True


class CompletionConfig(BaseModel):
    enable: bool = False
    model_path_mask: str
    model_path_rgb: str
    model_path_depth: str
    depth_encoder: str = "vitl"
    max_occ_len: int = 30
    detection_resolution: list[int] = [256, 512]
    completion_resolution: list[int] = [512, 1024]
    fallback_enabled: bool = True


class VLMConfig(BaseModel):
    model_path: str
    device: str = "cuda"
    fallback_enabled: bool = True
    template_path: str


class EmbeddingConfig(BaseModel):
    model_path: str
    device: str = "cpu"
    fallback_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    dim: int = 384
    fallback_enabled: bool = True


class VectorDBConfig(BaseModel):
    backend: str = "stub"
    weaviate_url: str = "http://localhost:8080"
    weaviate_api_key: Optional[str] = None
    class_name: str = "ActionClip"


class StorageConfig(BaseModel):
    backend: str = "local"
    local_dir: str = "./outputs"
    minio_endpoint: Optional[str] = None
    minio_bucket: str = "video2action"


class RuntimeConfig(BaseModel):
    output_dir: str = "./outputs"
    data_dir: str = "./data"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"


class APIConfig(BaseModel):
    cors_origins: list[str] = ["*"]
    max_upload_size_mb: int = 10240


class SystemConfig(BaseModel):
    runtime: RuntimeConfig
    sam3: Sam3Config
    sam_3d_body: Sam3DBodyConfig
    completion: CompletionConfig
    vlm: VLMConfig
    embedding: EmbeddingConfig
    vector_db: VectorDBConfig
    storage: StorageConfig
    api: APIConfig


def load_config(path: str | Path = DEFAULT_CONFIG) -> SystemConfig:
    """加载并解析 YAML 配置。

    优先级：环境变量 > YAML 文件
    - VECTOR_BACKEND: 覆盖 vector_db.backend
    - WEAVIATE_URL: 覆盖 vector_db.weaviate_url
    - LOG_LEVEL: 覆盖 runtime.log_level
    """
    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    # env 覆盖
    if "VECTOR_BACKEND" in os.environ:
        raw.setdefault("vector_db", {})["backend"] = os.environ["VECTOR_BACKEND"]
    if "WEAVIATE_URL" in os.environ:
        raw.setdefault("vector_db", {})["weaviate_url"] = os.environ["WEAVIATE_URL"]
    if "LOG_LEVEL" in os.environ:
        raw.setdefault("runtime", {})["log_level"] = os.environ["LOG_LEVEL"]
    if "DATA_DIR" in os.environ:
        raw.setdefault("runtime", {})["data_dir"] = os.environ["DATA_DIR"]
    if "OUTPUT_DIR" in os.environ:
        raw.setdefault("runtime", {})["output_dir"] = os.environ["OUTPUT_DIR"]

    return SystemConfig(**raw)


_config: Optional[SystemConfig] = None


def get_config() -> SystemConfig:
    """单例配置加载。"""
    global _config
    if _config is None:
        _config = load_config()
    return _config
