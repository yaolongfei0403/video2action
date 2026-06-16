"""/api/assets - 资产库 (入库资产列表)"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..store import get_store

router = APIRouter()


@router.get("")
def list_assets(
    quality_grades: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """列出已入库资产。"""
    store = get_store()
    grades = quality_grades.split(",") if quality_grades else None
    assets = store.list_assets(limit=limit, quality_grades=grades)
    return {
        "assets": [_asset_to_dict(a) for a in assets],
        "total": store.count_assets(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{asset_id}")
def get_asset(asset_id: str) -> dict:
    """获取资产详情。"""
    store = get_store()
    a = store.get_asset(asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    return _asset_to_dict(a)


@router.delete("/{asset_id}")
def delete_asset(asset_id: str) -> dict:
    """删除资产（仅标记，不真正删除）。"""
    store = get_store()
    a = store.get_asset(asset_id)
    if a is None:
        raise HTTPException(404, "Asset not found")
    a.meta["deleted"] = True
    store.upsert_asset(a)
    return {"ok": True}


def _asset_to_dict(a) -> dict:
    return {
        "id": a.id,
        "clip_id": a.clip_id,
        "guid": a.guid,
        "duration": a.duration,
        "keywords": a.keywords,
        "summary": a.summary,
        "detail": a.detail,
        "rhythm": a.rhythm,
        "use_case": a.use_case,
        "manual_tags": a.manual_tags,
        "quality_grade": a.quality_grade,
        "rendered_video_url": a.rendered_video_url,
        "original_video_url": a.original_video_url,
        "view_count": a.view_count,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
