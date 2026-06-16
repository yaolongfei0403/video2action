"""/api/completed - 入库完成页"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..store import get_store

router = APIRouter()


@router.get("/{task_id}")
def get_completion(task_id: str) -> dict:
    """获取完成信息 - 复现 HTML 入库完成页的指标卡。

    Returns:
        {"task_id": ..., "rendered_videos": 1, "tags": 6, "vector_records": 1, "output_size_mb": 128}
    """
    store = get_store()
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")

    # 找关联 clip + asset
    clip = store.get_clip(task.clip_id) if task.clip_id else None
    assets = store.list_assets(limit=1000)
    related_assets = [a for a in assets if a.clip_id == task.clip_id] if task.clip_id else []

    rendered_count = 0
    size_mb = 0.0
    if clip and clip.rendered_video_url:
        path = Path(clip.rendered_video_url.lstrip("/"))
        # 实际为 outputs/{task_id}/4d_*.mp4
        out_dir = Path("outputs") / task_id
        if out_dir.exists():
            for f in out_dir.rglob("*.mp4"):
                if f.is_file():
                    rendered_count += 1
                    size_mb += f.stat().st_size / 1024 / 1024
            for f in out_dir.rglob("*.jpg"):
                size_mb += f.stat().st_size / 1024 / 1024

    tags = []
    if clip:
        tags = [t for t in [
            clip.keywords,
            clip.summary,
            clip.rhythm,
            clip.use_case,
            *clip.manual_tags,
        ] if t]

    return {
        "task_id": task_id,
        "rendered_videos": rendered_count,
        "tags": len(tags),
        "vector_records": len(related_assets),
        "output_size_mb": round(size_mb, 2),
        "clip": {
            "id": clip.id if clip else "",
            "summary": clip.summary if clip else "",
            "rendered_video_url": clip.rendered_video_url if clip else "",
        } if clip else None,
    }
