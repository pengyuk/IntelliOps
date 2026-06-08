"""
Vector search — embedding-based similarity for incident cases and knowledge assets.

Uses sentence-transformers (or TF-IDF fallback) to compute embeddings,
then FAISS for efficient Top-K similarity search.

Replaces the old set-intersection-based _related_cases_for_incident.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


class VectorSearch:
    """Lightweight vector search with optional FAISS acceleration."""

    def __init__(self):
        self._model = None
        self._index = None
        self._items: List[Dict[str, Any]] = []
        self._embeddings: Optional[np.ndarray] = None

    @property
    def model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(
                    os.environ.get("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
                )
            except ImportError:
                self._model = False  # mark as unavailable
        return self._model if self._model is not False else None

    def _encode(self, texts: List[str]) -> np.ndarray:
        model = self.model
        if model:
            return model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

        # TF-IDF fallback using simple word overlap
        all_words = set()
        for t in texts:
            all_words.update(t.lower().split())
        word_list = sorted(all_words)[:5000]
        word_to_idx = {w: i for i, w in enumerate(word_list)}
        vectors = np.zeros((len(texts), len(word_list)), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().split():
                if w in word_to_idx:
                    vectors[i, word_to_idx[w]] = 1.0
        # Normalize
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def _build_faiss_index(self, embeddings: np.ndarray) -> None:
        try:
            import faiss
            dim = embeddings.shape[1]
            self._index = faiss.IndexFlatIP(dim)  # inner product (cosine for normalized vectors)
            self._index.add(embeddings.astype(np.float32))
        except ImportError:
            self._index = None

    def index_items(self, items: List[Dict[str, Any]], text_key: str = "summary") -> None:
        """Build index from a list of items. Each item must have a text_key field."""
        if not items:
            return
        self._items = items
        texts = [item.get(text_key, "") for item in items]
        self._embeddings = self._encode(texts)
        self._build_faiss_index(self._embeddings)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """Search for top_k most similar items. Returns [(item, score), ...]."""
        if not self._items:
            return []
        query_vec = self._encode([query])

        if self._index is not None:
            import faiss
            scores, indices = self._index.search(query_vec.astype(np.float32), min(top_k, len(self._items)))
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if idx >= 0 and idx < len(self._items):
                    results.append((self._items[idx], float(score)))
            return results

        # Brute-force cosine similarity
        similarities = np.dot(query_vec, self._embeddings.T)[0]
        top_indices = np.argsort(similarities)[::-1][:top_k]
        return [(self._items[i], float(similarities[i])) for i in top_indices if similarities[i] > 0]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_vector_search: Optional[VectorSearch] = None


def get_vector_search() -> VectorSearch:
    global _vector_search
    if _vector_search is None:
        _vector_search = VectorSearch()
    return _vector_search
