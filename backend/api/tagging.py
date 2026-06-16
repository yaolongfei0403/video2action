"""/api/tagging - 标签生成 (Qwen-VL + 人工编辑)"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..store import (
    ActionClip,
    Clip,
    ClipStatus,
    Task,
    TaskStatus,
    TaskType,
    get_store,
)
from ..vector import build_action_text, get_vector_store
from backend.pipeline_registry import get_pipeline

logger = logging.getLogger(__name__)
router = APIRouter()


class VLMRequest(BaseModel):
    clip_id: str
    keywords: str = ""
    use_real: bool = False


class TaggingSaveRequest(BaseModel):
    """保存/入库请求"""
    clip_id: str
    keywords: str = ""
    summary: str = ""
    detail: str = ""
    rhythm: str = ""
    use_case: str = ""
    manual_tags: list[str] = []
    quality_grade: str = "B"


@router.post("/vlm")
def vlm_describe(req: VLMRequest) -> dict:
    """调用 VLM 生成结构化描述。

    真实模式：Qwen-VL 7B
    stub 模式：基于关键词模板
    """
    store = get_store()
    clip = store.get_clip(req.clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    # 任务
    task = Task(
        type=TaskType.VLM_TAG,
        video_id=clip.video_id,
        clip_id=clip.id,
        status=TaskStatus.SEMANTIC_TAGGING,
        current_stage="semantic_tagging",
    )
    store.create_task(task)

    vlm = get_pipeline("vlm")
    keywords = req.keywords or clip.keywords or ""
    video_path = clip.meta.get("rendered_video_url") or clip.meta.get("trimmed_path") or ""

    try:
        desc = vlm.describe(video_path=video_path, keywords=keywords)
    except Exception as e:
        logger.warning(f"VLM failed: {e}; using empty description")
        desc = {"summary": "", "detail": "", "rhythm": "", "use_case": ""}

    # 写回 clip（覆盖或初填）
    clip.keywords = keywords
    clip.summary = desc.get("summary", "")
    clip.detail = desc.get("detail", "")
    clip.rhythm = desc.get("rhythm", "")
    clip.use_case = desc.get("use_case", "")
    clip.status = ClipStatus.TAGGED
    store.upsert_clip(clip)

    store.update_task(task.id, status=TaskStatus.INDEXING, progress=0.7, current_stage="indexing")

    return {
        "task_id": task.id,
        "mode": vlm.mode,
        "description": desc,
        "clip": {
            "id": clip.id,
            "keywords": clip.keywords,
            "summary": clip.summary,
            "detail": clip.detail,
            "rhythm": clip.rhythm,
            "use_case": clip.use_case,
        },
    }


@router.post("/save")
def save_tags(req: TaggingSaveRequest) -> dict:
    """保存人工编辑的标签（可覆盖 VLM 输出）。"""
    store = get_store()
    clip = store.get_clip(req.clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    clip.keywords = req.keywords
    clip.summary = req.summary
    clip.detail = req.detail
    clip.rhythm = req.rhythm
    clip.use_case = req.use_case
    clip.manual_tags = req.manual_tags
    clip.quality_grade = req.quality_grade
    store.upsert_clip(clip)

    return {"ok": True, "clip_id": clip.id}


@router.post("/index")
def index_clip(clip_id: str) -> dict:
    """将 clip 入库到 ActionClip + 向量库。"""
    store = get_store()
    vec = get_vector_store()
    clip = store.get_clip(clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")

    # 创建 ActionClip
    asset = ActionClip(
        clip_id=clip.id,
        guid=clip.meta.get("guid"),
        duration=clip.duration,
        keywords=clip.keywords,
        summary=clip.summary,
        detail=clip.detail,
        rhythm=clip.rhythm,
        use_case=clip.use_case,
        manual_tags=clip.manual_tags,
        quality_grade=clip.quality_grade,
        rendered_video_url=clip.rendered_video_url,
        original_video_url=clip.meta.get("source_path", ""),
    )
    store.upsert_asset(asset)

    # 入向量库
    text = build_action_text(
        summary=clip.summary,
        detail=clip.detail,
        rhythm=clip.rhythm,
        use_case=clip.use_case,
        keywords=clip.keywords,
        manual_tags=clip.manual_tags,
    )
    metadata = {
        "asset_id": asset.id,
        "clip_id": clip.id,
        "guid": asset.guid,
        "duration": asset.duration,
        "keywords": asset.keywords,
        "summary": asset.summary,
        "detail": asset.detail,
        "rhythm": asset.rhythm,
        "use_case": asset.use_case,
        "manual_tags": asset.manual_tags,
        "quality_grade": asset.quality_grade,
        "rendered_video_url": asset.rendered_video_url,
        "original_video_url": asset.original_video_url,
    }
    vec.upsert(asset.id, text, metadata=metadata)

    # 更新 clip 状态
    clip.status = ClipStatus.INDEXED
    store.upsert_clip(clip)

    # 找关联 task
    tasks = store.list_tasks(limit=1000)
    related = [t for t in tasks if t.clip_id == clip.id and t.status != TaskStatus.COMPLETED]
    for t in related:
        store.update_task(t.id, status=TaskStatus.COMPLETED, progress=1.0, current_stage="completed")

    return {
        "ok": True,
        "asset_id": asset.id,
        "vector_count": vec.count(),
    }
