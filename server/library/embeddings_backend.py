"""Embedding backend adapter with deterministic fallback."""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Callable, List, Sequence

LOGGER = logging.getLogger(__name__)

_FAKE_DIM = 384


class EmbeddingsBackend:
    """Expose the embedding capabilities of the project with a fallback."""

    def __init__(self) -> None:
        self._backend_name = "unavailable"
        self._embed: Callable[[Sequence[str]], List[List[float]]] | None = None
        self._allow_fake = os.getenv("ALLOW_FAKE_EMBEDS", "false").lower() == "true"
        self._load_backend()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    @property
    def name(self) -> str:
        if self._embed is None:
            return "fake" if self._allow_fake else "unavailable"
        return self._backend_name

    def is_ready(self) -> bool:
        return self._embed is not None

    def embed_texts(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        if self._embed is not None:
            try:
                vectors = self._embed(texts)
                if vectors:
                    return vectors
                LOGGER.warning("embeddings_empty_output", extra={"backend": self._backend_name})
            except Exception as exc:  # pragma: no cover - resilient logging
                LOGGER.exception("embeddings_backend_error", extra={"backend": self._backend_name})
                if not self._allow_fake:
                    raise RuntimeError("embeddings_backend_unavailable") from exc
        if not self._allow_fake:
            raise RuntimeError("embeddings_backend_unavailable")
        LOGGER.warning("embeddings_using_fake", extra={"dim": _FAKE_DIM})
        return [_fake_embedding(text, dimensions=_FAKE_DIM) for text in texts]

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _load_backend(self) -> None:
        try:
            from modules.library_llm import embed_texts as embed_fn  # type: ignore
        except Exception:  # pragma: no cover - optional dependency
            self._embed = None
            self._backend_name = "unavailable"
            return
        self._embed = lambda texts: embed_fn(list(texts))
        self._backend_name = "modules.library_llm"


def _fake_embedding(text: str, *, dimensions: int) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    seed = int(digest[:16], 16)
    rng_state = seed
    vector = []
    for _ in range(dimensions):
        rng_state = (1103515245 * rng_state + 12345) & 0x7FFFFFFF
        value = (rng_state / 0x7FFFFFFF) * 2.0 - 1.0
        vector.append(value)
    norm = sum(v * v for v in vector) ** 0.5
    if norm == 0:
        return vector
    return [v / norm for v in vector]


__all__ = ["EmbeddingsBackend"]
