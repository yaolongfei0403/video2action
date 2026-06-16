"""VectorStore 抽象接口 (对应 PRD 3.3.3 / 3.4.1).

backend/vector 包暴露一个 VectorStore 抽象 + 两个实现：
- StubVectorStore (默认，本地内存)
- WeaviateVectorStore (可选，依赖 weaviate-client)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Hit:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """向量库统一接口。

    实现方：
    - stub_client.StubVectorStore — in-memory, 零外部依赖
    - weaviate_client.WeaviateVectorStore — weaviate-client, env WEAVIATE_URL
    """

    @abstractmethod
    def upsert(self, id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> None:
        """插入或更新一条文本记录，自动向量化。"""
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.0,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[Hit]:
        """纯文本语义检索。返回按相似度降序的命中列表。"""
        ...

    @abstractmethod
    def count(self) -> int:
        """库内向量数量。"""
        ...

    @abstractmethod
    def clear(self) -> None:
        """清空（主要用于测试）。"""
        ...


# 文本拼接 (与 PRD 3.3.3 入库流程一致)
def build_action_text(
    summary: str,
    detail: str,
    rhythm: str,
    use_case: str,
    keywords: str = "",
    manual_tags: Optional[list[str]] = None,
) -> str:
    """将多维度文本拼成一条长文本，用于向量化。

    与 PRD 描述一致：textFields = [summary, detail, rhythm, use_case, keywords, manual_tags]
    """
    parts = [
        f"摘要：{summary}" if summary else "",
        f"细节：{detail}" if detail else "",
        f"节奏：{rhythm}" if rhythm else "",
        f"场景：{use_case}" if use_case else "",
        f"关键词：{keywords}" if keywords else "",
        f"标签：{' '.join(manual_tags or [])}",
    ]
    return " | ".join(p for p in parts if p)


def build_query_text(query: str) -> str:
    """用户检索的 query 同样做规范化（多语言场景下保持原样，仅去空白）。"""
    return " ".join((query or "").split())
