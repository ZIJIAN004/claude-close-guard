"""Lazy-loaded sentence-transformer embedder. Default: bge-base-zh-v1.5."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class Embedder:
    """Wraps a SentenceTransformer with lazy loading + a process-wide lock.

    Cold-start cost (model download + load) is paid on first encode().
    """

    def __init__(self, model_name: str = "BAAI/bge-base-zh-v1.5", device: str = "cpu") -> None:
        self.model_name = model_name
        self.device = device
        self._model: "SentenceTransformer | None" = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> "SentenceTransformer":
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    @property
    def dim(self) -> int:
        m = self._ensure_loaded()
        # sentence-transformers 5.x renamed this. Fall back for older versions.
        getter = getattr(m, "get_embedding_dimension",
                         getattr(m, "get_sentence_embedding_dimension"))
        return int(getter())

    def encode(self, texts: list[str]) -> list[list[float]]:
        m = self._ensure_loaded()
        # normalize_embeddings=True so we can use dot product as cosine similarity
        out = m.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return out.tolist()

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]
