"""WeaviateVectorStore - 真实 Weaviate 客户端 (可选).

切换条件：env VECTOR_BACKEND=weaviate 且安装 weaviate-client。

Schema 完全对应 PRD 3.3.3 的 ActionClip class。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from .base import Hit, VectorStore, build_query_text

logger = logging.getLogger(__name__)


class WeaviateVectorStore(VectorStore):
    """封装 weaviate-client v4 的 VectorStore 实现。

    用法：
        store = WeaviateVectorStore(url="http://localhost:8080", api_key=None)
        store.upsert("clip_1", "标准篮球扣篮动作", {...})
        store.search("扣篮", top_k=5)
    """

    def __init__(self, url: str, api_key: Optional[str] = None, class_name: str = "ActionClip"):
        try:
            import weaviate  # type: ignore
        except ImportError as e:
            raise ImportError(
                "weaviate-client not installed. `pip install weaviate-client` "
                "or set VECTOR_BACKEND=stub"
            ) from e

        if api_key:
            auth = weaviate.AuthApiKey(api_key)
            self._client = weaviate.connect_to_wcs(url=url, auth_credentials=auth) \
                if "weaviate.cloud" in url else weaviate.connect_to_custom(
                    http_host=url.split("//")[-1].split(":")[0],
                    http_port=int(url.split(":")[-1]) if ":" in url.split("//")[-1] else 8080,
                    auth_credentials=auth,
                )
        else:
            self._client = weaviate.connect_to_local(url=url)
        self.class_name = class_name
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """按 PRD 3.3.3 创建 ActionClip class。"""
        import weaviate.classes.config as wvc_cfg  # type: ignore

        if self._client.collections.exists(self.class_name):
            return

        self._client.collections.create(
            name=self.class_name,
            description="4D 动作片段知识库条目 (纯文本语义检索)",
            properties=[
                wvc_cfg.Property(name="clip_id", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="guid", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="duration", data_type=wvc_cfg.DataType.NUMBER),
                wvc_cfg.Property(name="keywords", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="summary", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="detail", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="rhythm", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="use_case", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="manual_tags", data_type=wvc_cfg.DataType.TEXT_ARRAY),
                wvc_cfg.Property(name="quality_grade", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="rendered_video_url", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="original_video_url", data_type=wvc_cfg.DataType.TEXT),
                wvc_cfg.Property(name="created_at", data_type=wvc_cfg.DataType.DATE),
            ],
            vectorizer_config=wvc_cfg.Configure.Vectorizer.text2vec_transformers(),
        )
        logger.info(f"Created Weaviate class: {self.class_name}")

    def upsert(self, id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> None:
        coll = self._client.collections.get(self.class_name)
        meta = dict(metadata or {})
        meta.pop("text", None)  # 避免重复存储
        props = {
            "clip_id": meta.get("clip_id", id),
            "guid": meta.get("guid"),
            "duration": float(meta.get("duration", 0.0)),
            "keywords": meta.get("keywords", ""),
            "summary": meta.get("summary", ""),
            "detail": meta.get("detail", ""),
            "rhythm": meta.get("rhythm", ""),
            "use_case": meta.get("use_case", ""),
            "manual_tags": list(meta.get("manual_tags", [])),
            "quality_grade": meta.get("quality_grade", "B"),
            "rendered_video_url": meta.get("rendered_video_url", ""),
            "original_video_url": meta.get("original_video_url", ""),
        }
        coll.data.update(uuid=id, properties=props) if coll.data.exists(id) else coll.data.insert(
            uuid=id, properties=props
        )

    def search(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.0,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[Hit]:
        from weaviate.classes.query import MetadataQuery  # type: ignore

        coll = self._client.collections.get(self.class_name)
        response = coll.query.near_text(
            query=build_query_text(query),
            limit=top_k,
            return_metadata=MetadataQuery(distance=True),
        )
        results: list[Hit] = []
        for obj in response.objects:
            distance = obj.metadata.distance or 0.0
            score = max(0.0, 1.0 - distance)  # distance → 相似度
            if score < threshold:
                continue
            payload = dict(obj.properties or {})
            results.append(Hit(id=str(obj.uuid), score=score, payload=payload))
        return results

    def count(self) -> int:
        coll = self._client.collections.get(self.class_name)
        resp = coll.aggregate.over_all(total_count=True)
        return int(resp.total_count or 0)

    def clear(self) -> None:
        self._client.collections.delete(self.class_name)
        self._ensure_schema()
