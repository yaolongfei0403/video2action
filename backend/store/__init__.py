"""backend.store - 业务状态持久化层"""
from .models import (
    ActionClip,
    Clip,
    ClipCandidate,
    ClipStatus,
    DashboardMetrics,
    MaskAnnotation,
    SearchHit,
    SearchRequest,
    SearchResponse,
    Task,
    TaskStatus,
    TaskType,
    VideoSource,
    VideoStatus,
)
from .sqlite_store import SQLiteStore

# 单例 store
_store: "SQLiteStore | None" = None


def get_store(db_path: str | None = None) -> SQLiteStore:
    global _store
    if _store is None:
        from pathlib import Path
        from ..config import get_config

        cfg = get_config()
        data_dir = Path(cfg.runtime.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        path = db_path or str(data_dir / "system.db")
        _store = SQLiteStore(path)
    return _store


__all__ = [
    "ActionClip",
    "Clip",
    "ClipCandidate",
    "ClipStatus",
    "DashboardMetrics",
    "MaskAnnotation",
    "SearchHit",
    "SearchRequest",
    "SearchResponse",
    "SQLiteStore",
    "Task",
    "TaskStatus",
    "TaskType",
    "VideoSource",
    "VideoStatus",
    "get_store",
]
