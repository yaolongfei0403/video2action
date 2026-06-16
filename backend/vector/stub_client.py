"""StubVectorStore - in-memory 向量库, 零外部依赖.

默认实现：
- 编码器：sentence-transformers 多语种 MiniLM
- 不可用时回退到 TF-IDF + 字符 n-gram (基于 sklearn)

数据通过 JSON 文件持久化到 data/embeddings/。
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .base import Hit, VectorStore, build_action_text, build_query_text

logger = logging.getLogger(__name__)


class _Encoder:
    """懒加载的多语言文本编码器。"""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.model_name = model_name
        self._model = None
        self._mode: str = "unknown"
        self._vectorizer = None
        self._vocab: dict[str, int] = {}
        self._idf: Optional[np.ndarray] = None
        self._lock = threading.Lock()

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        with self._lock:
            if self._model is None and self._mode == "unknown":
                self._try_load_model()
            if self._model is not None:
                vecs = self._model.encode(
                    texts, convert_to_numpy=True, show_progress_bar=False, normalize_embeddings=True
                )
                self._mode = "st"
                return vecs.astype(np.float32)

        # 降级：TF-IDF
        return self._tfidf_encode(texts)

    def _try_load_model(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading sentence-transformers model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name)
            self._mode = "st"
            logger.info("Encoder ready (sentence-transformers)")
        except Exception as e:
            logger.warning(f"sentence-transformers unavailable: {e}; falling back to TF-IDF")
            self._model = None
            self._mode = "tfidf"

    def _tfidf_encode(self, texts: list[str]) -> np.ndarray:
        """字符 n-gram + TF-IDF 回退。"""
        from collections import Counter

        def char_ngrams(text: str, n_range=(2, 4)) -> list[str]:
            text = text or ""
            grams = []
            for n in n_range:
                for i in range(len(text) - n + 1):
                    grams.append(text[i:i + n])
            return grams

        # 更新词汇表 & IDF
        doc_freq: Counter = Counter()
        tokenized_docs = []
        for t in texts:
            toks = char_ngrams(t)
            tokenized_docs.append(toks)
            doc_freq.update(set(toks))

        if not self._vocab:
            # 已有词表：复用
            tokenized_docs_iter = tokenized_docs
        else:
            tokenized_docs_iter = tokenized_docs

        # 增量更新 vocab
        new_terms = [t for t in doc_freq if t not in self._vocab]
        start_idx = len(self._vocab)
        for i, t in enumerate(new_terms):
            self._vocab[t] = start_idx + i

        # 计算或更新 IDF
        all_terms = list(self._vocab.keys())
        df = np.array([doc_freq.get(t, 0) for t in all_terms], dtype=np.float32)
        n_docs = max(len(texts), 1)
        idf = np.log((1 + n_docs) / (1 + df)) + 1.0

        # 计算每条文本的 TF-IDF 向量
        dim = len(self._vocab) or 1
        vecs = np.zeros((len(texts), max(dim, 384)), dtype=np.float32)
        for i, toks in enumerate(tokenized_docs_iter):
            if not toks:
                continue
            tf = Counter(toks)
            total = sum(tf.values())
            for term, cnt in tf.items():
                idx = self._vocab.get(term)
                if idx is not None and idx < dim:
                    vecs[i, idx] = (cnt / total) * idf[idx] if idx < len(idf) else cnt / total

        # 截断或补零到统一维度 384
        if vecs.shape[1] > 384:
            vecs = vecs[:, :384]
        elif vecs.shape[1] < 384:
            pad = np.zeros((vecs.shape[0], 384 - vecs.shape[1]), dtype=np.float32)
            vecs = np.concatenate([vecs, pad], axis=1)

        # L2 normalize
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (vecs / norms).astype(np.float32)


class StubVectorStore(VectorStore):
    """In-memory 向量库 + JSON 持久化。"""

    def __init__(self, persist_dir: str | Path):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.encoder = _Encoder()
        self._lock = threading.RLock()
        self._ids: list[str] = []
        self._payloads: dict[str, dict[str, Any]] = {}
        self._vectors: Optional[np.ndarray] = None  # (N, D)
        self._load()

    # ---------- 持久化 ----------

    def _load(self) -> None:
        meta_path = self.persist_dir / "meta.json"
        vec_path = self.persist_dir / "vectors.npy"
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            self._ids = meta.get("ids", [])
            self._payloads = meta.get("payloads", {})
        if vec_path.exists() and self._ids:
            self._vectors = np.load(str(vec_path))
        logger.info(f"StubVectorStore loaded: {len(self._ids)} entries")

    def _save(self) -> None:
        meta_path = self.persist_dir / "meta.json"
        vec_path = self.persist_dir / "vectors.npy"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"ids": self._ids, "payloads": self._payloads}, f, ensure_ascii=False, indent=2)
        if self._vectors is not None:
            np.save(str(vec_path), self._vectors)

    # ---------- 核心接口 ----------

    def upsert(self, id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> None:
        with self._lock:
            text = (text or "").strip()
            if not text:
                return
            payload = dict(metadata or {})
            payload["text"] = text
            new_vec = self.encoder.encode([text])[0]

            if id in self._payloads:
                # 更新
                idx = self._ids.index(id)
                if self._vectors is None:
                    self._vectors = np.zeros((0, new_vec.shape[0]), dtype=np.float32)
                self._vectors[idx] = new_vec
                self._payloads[id] = payload
            else:
                self._ids.append(id)
                self._payloads[id] = payload
                if self._vectors is None or self._vectors.size == 0:
                    self._vectors = new_vec[None, :]
                else:
                    self._vectors = np.vstack([self._vectors, new_vec[None, :]])
            self._save()

    def search(
        self,
        query: str,
        top_k: int = 10,
        threshold: float = 0.0,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[Hit]:
        with self._lock:
            if not self._ids or self._vectors is None or len(self._vectors) == 0:
                return []
            qv = self.encoder.encode([build_query_text(query)])[0]
            scores = self._vectors @ qv  # cosine since vectors are L2-normalized
            order = np.argsort(-scores)[:top_k]
            results: list[Hit] = []
            for idx in order:
                score = float(scores[idx])
                if score < threshold:
                    continue
                _id = self._ids[int(idx)]
                payload = dict(self._payloads.get(_id, {}))
                if filters and not self._match_filters(payload, filters):
                    continue
                results.append(Hit(id=_id, score=score, payload=payload))
            return results

    def _match_filters(self, payload: dict[str, Any], filters: dict[str, Any]) -> bool:
        for k, v in filters.items():
            if k == "quality_grade" and isinstance(v, list):
                if payload.get("quality_grade") not in v:
                    return False
            elif k == "duration_range" and isinstance(v, (list, tuple)) and len(v) == 2:
                d = payload.get("duration", 0.0)
                if not (v[0] <= d <= v[1]):
                    return False
            elif k == "keywords_contains":
                kw = (payload.get("keywords") or "").lower()
                if v.lower() not in kw:
                    return False
            else:
                if payload.get(k) != v:
                    return False
        return True

    def count(self) -> int:
        return len(self._ids)

    def clear(self) -> None:
        with self._lock:
            self._ids = []
            self._payloads = {}
            self._vectors = None
            self._save()
