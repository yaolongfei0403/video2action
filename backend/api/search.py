"""/api/search - 纯文本语义检索"""
from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..store import SearchHit, SearchRequest, SearchResponse
from ..vector import get_vector_store

router = APIRouter()


@router.post("/text", response_model=SearchResponse)
def search_text(req: SearchRequest) -> SearchResponse:
    """纯文本语义检索 - 复现 PRD 3.4.1 检索 API。

    Returns:
        SearchResponse{results, total, query_time_ms}
    """
    vec = get_vector_store()
    t0 = time.time()
    hits = vec.search(
        query=req.query,
        top_k=req.top_k,
        threshold=req.threshold,
        filters=req.filters,
    )
    elapsed_ms = (time.time() - t0) * 1000

    return SearchResponse(
        query=req.query,
        results=[
            SearchHit(id=h.id, score=h.score, payload=h.payload) for h in hits
        ],
        total=len(hits),
        query_time_ms=elapsed_ms,
    )


@router.post("/reference")
def reference_for_generation(payload: dict) -> dict:
    """大模型引用接口 (复现 PRD 3.4.2).

    Args:
        payload: {
            "generation_prompt": "生成一个篮球运动员三分投篮视频",
            "style_hint": "写实, 体育",
            "duration_hint": 6.0,
            "top_k": 3
        }

    Returns: {"references": [...]}
    """
    query = payload.get("generation_prompt", "")
    style = payload.get("style_hint", "")
    duration_hint = payload.get("duration_hint")
    top_k = int(payload.get("top_k", 3))

    full_query = " ".join([query, style]).strip() or "动作参考"
    filters: dict = {}
    if duration_hint:
        # 滑窗 ±2s
        filters["duration_range"] = [max(0, duration_hint - 3), duration_hint + 3]

    vec = get_vector_store()
    hits = vec.search(query=full_query, top_k=top_k, filters=filters)

    references = []
    for i, h in enumerate(hits):
        p = h.payload
        references.append({
            "rank": i + 1,
            "score": h.score,
            "action_summary": p.get("summary", ""),
            "duration": p.get("duration", 0.0),
            "rendered_video_url": p.get("rendered_video_url", ""),
            "original_video_url": p.get("original_video_url", ""),
        })
    return {"references": references}


@router.get("/stats")
def search_stats() -> dict:
    """检索统计。"""
    vec = get_vector_store()
    return {
        "vector_count": vec.count(),
        "backend": vec.__class__.__name__,
    }
