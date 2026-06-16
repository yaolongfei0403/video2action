"""backend.vector - 向量库抽象与实现"""
from .base import Hit, VectorStore, build_action_text, build_query_text
from .stub_client import StubVectorStore

_vector_store: "VectorStore | None" = None


def get_vector_store() -> VectorStore:
    """根据配置返回 VectorStore 实例（默认 stub）。"""
    global _vector_store
    if _vector_store is not None:
        return _vector_store

    import os
    from pathlib import Path

    from ..config import get_config

    cfg = get_config()
    backend = os.environ.get("VECTOR_BACKEND") or cfg.vector_db.backend

    if backend == "weaviate":
        try:
            from .weaviate_client import WeaviateVectorStore

            url = os.environ.get("WEAVIATE_URL") or cfg.vector_db.weaviate_url
            key = os.environ.get("WEAVIATE_API_KEY") or cfg.vector_db.weaviate_api_key
            _vector_store = WeaviateVectorStore(url=url, api_key=key, class_name=cfg.vector_db.class_name)
            return _vector_store
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Weaviate unavailable ({e}); falling back to stub"
            )

    data_dir = Path(cfg.runtime.data_dir) / "embeddings"
    _vector_store = StubVectorStore(persist_dir=data_dir)
    return _vector_store


__all__ = [
    "Hit",
    "StubVectorStore",
    "VectorStore",
    "build_action_text",
    "build_query_text",
    "get_vector_store",
]
