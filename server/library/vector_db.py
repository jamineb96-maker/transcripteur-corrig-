"""Persistent vector store for the clinical library."""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from .models import Chunk, ChunkMeta

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    import numpy as _np  # type: ignore
    HAS_NUMPY = True
except Exception:  # pragma: no cover - numpy optional
    _np = None  # type: ignore
    HAS_NUMPY = False

try:  # pragma: no cover - optional dependency
    import faiss  # type: ignore
    HAS_FAISS = True
except Exception:  # pragma: no cover - faiss optional
    faiss = None  # type: ignore
    HAS_FAISS = False


EVIDENCE_ORDER: Dict[str, int] = {"inconnu": 0, "faible": 1, "modéré": 2, "élevé": 3}


def _env_truth(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_vector(vector: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [0.0 for _ in vector]
    return [value / norm for value in vector]


class VectorDB:
    """Simple vector database backed by jsonl + numpy/FAISS."""

    def __init__(self, store_dir: str | os.PathLike[str] | None = None) -> None:
        base = Path(store_dir or Path(__file__).parent / "store")
        base.mkdir(parents=True, exist_ok=True)
        self.store_dir = base
        self._chunks_path = self.store_dir / "chunks.jsonl"
        self._vectors_path = self.store_dir / "vectors.npy"
        self._vectors_json_path = self.store_dir / "vectors.json"
        self._ids_path = self.store_dir / "chunk_ids.json"
        self._faiss_path = self.store_dir / "faiss.index"
        self._lock = threading.RLock()
        self._chunks: Dict[str, Chunk] = {}
        self._chunk_ids: List[str] = []
        self._vectors: List[List[float]] = []
        self._id_to_pos: Dict[str, int] = {}
        self._doc_counts: Dict[str, int] = {}
        self._use_faiss = _env_truth("USE_FAISS") and HAS_FAISS and HAS_NUMPY
        if _env_truth("USE_FAISS") and not self._use_faiss:
            LOGGER.warning(
                "vector_db_faiss_unavailable",
                extra={"has_faiss": HAS_FAISS, "has_numpy": HAS_NUMPY},
            )
        self._faiss_index = None
        self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _load(self) -> None:
        with self._lock:
            self._load_chunks()
            self._load_vectors()
            self._reconcile_locked()
            if self._use_faiss:
                self._rebuild_faiss_locked()

    def _load_chunks(self) -> None:
        self._chunks.clear()
        self._doc_counts.clear()
        if not self._chunks_path.exists():
            return
        with open(self._chunks_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                meta_payload = payload.get("meta", {})
                text = str(payload.get("text", ""))
                try:
                    meta = ChunkMeta.from_dict(meta_payload)
                except Exception as exc:
                    LOGGER.warning("vector_db_meta_invalid", extra={"error": str(exc)})
                    continue
                chunk = Chunk(meta=meta, text=text, embedding=[])
                self._chunks[meta.chunk_id] = chunk
                self._doc_counts[meta.doc_id] = self._doc_counts.get(meta.doc_id, 0) + 1

    def _load_vectors(self) -> None:
        vectors: List[List[float]] = []
        ids: List[str] = []
        if self._ids_path.exists():
            try:
                with open(self._ids_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    ids = [str(value) for value in data]
            except Exception as exc:
                LOGGER.warning("vector_db_ids_load_failed", extra={"error": str(exc)})
        if HAS_NUMPY and self._vectors_path.exists():
            try:
                matrix = _np.load(self._vectors_path, allow_pickle=True)  # type: ignore[call-arg]
                vectors = matrix.tolist() if hasattr(matrix, "tolist") else []
            except Exception as exc:
                LOGGER.warning("vector_db_vectors_npy_failed", extra={"error": str(exc)})
        elif self._vectors_json_path.exists():
            try:
                with open(self._vectors_json_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, list):
                    vectors = [[float(value) for value in row] for row in data]
            except Exception as exc:
                LOGGER.warning("vector_db_vectors_json_failed", extra={"error": str(exc)})
        self._chunk_ids = ids if ids else list(self._chunks.keys())
        self._vectors = vectors if vectors else [[] for _ in self._chunk_ids]

    def _reconcile_locked(self) -> None:
        new_ids: List[str] = []
        new_vectors: List[List[float]] = []
        for index, chunk_id in enumerate(self._chunk_ids):
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            vector: List[float]
            if index < len(self._vectors) and self._vectors[index]:
                vector = _normalize_vector(self._vectors[index])
            else:
                vector = list(chunk.embedding or [])
            chunk.embedding = vector
            new_ids.append(chunk_id)
            new_vectors.append(vector)
        self._chunk_ids = new_ids
        self._vectors = new_vectors
        self._id_to_pos = {chunk_id: idx for idx, chunk_id in enumerate(self._chunk_ids)}
        if not self._doc_counts:
            for chunk in self._chunks.values():
                self._doc_counts[chunk.meta.doc_id] = self._doc_counts.get(chunk.meta.doc_id, 0) + 1

    def _persist_locked(self) -> None:
        with open(self._chunks_path, "w", encoding="utf-8") as handle:
            for chunk_id in self._chunk_ids:
                chunk = self._chunks.get(chunk_id)
                if chunk is None:
                    continue
                payload = {"meta": chunk.meta.to_dict(), "text": chunk.text}
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        with open(self._ids_path, "w", encoding="utf-8") as handle:
            json.dump(self._chunk_ids, handle, ensure_ascii=False)
        with open(self._vectors_json_path, "w", encoding="utf-8") as handle:
            json.dump(self._vectors, handle, ensure_ascii=False)
        if HAS_NUMPY and _np is not None:
            try:
                matrix = _np.array(self._vectors, dtype="float32")
                _np.save(self._vectors_path, matrix)
            except Exception as exc:  # pragma: no cover - disk issues
                LOGGER.warning("vector_db_vectors_npy_write_failed", extra={"error": str(exc)})
        if self._use_faiss:
            self._rebuild_faiss_locked()

    def _rebuild_faiss_locked(self) -> None:
        if not self._use_faiss or not HAS_NUMPY or _np is None or faiss is None:
            self._faiss_index = None
            return
        if not self._vectors:
            self._faiss_index = None
            try:
                if self._faiss_path.exists():
                    self._faiss_path.unlink()
            except OSError:
                pass
            return
        matrix = _np.array(self._vectors, dtype="float32")
        dim = int(matrix.shape[1]) if matrix.ndim == 2 else int(matrix.shape[0])
        index = faiss.IndexFlatIP(dim)  # type: ignore[call-arg]
        index.add(matrix)
        try:
            faiss.write_index(index, str(self._faiss_path))  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - disk issues
            LOGGER.warning("vector_db_faiss_write_failed", extra={"error": str(exc)})
        self._faiss_index = index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def upsert(self, chunks: Sequence[Chunk]) -> int:
        new_count = 0
        with self._lock:
            for chunk in chunks:
                cid = chunk.meta.chunk_id
                if not cid:
                    raise ValueError("chunk_id missing")
                vector = _normalize_vector(chunk.embedding)
                chunk.embedding = vector
                existing = self._chunks.get(cid)
                if existing is not None:
                    if existing.meta.doc_id != chunk.meta.doc_id:
                        raise ValueError("chunk_doc_mismatch")
                    self._chunks[cid] = chunk
                    pos = self._id_to_pos.get(cid)
                    if pos is None:
                        self._chunk_ids.append(cid)
                        self._id_to_pos[cid] = len(self._chunk_ids) - 1
                        self._vectors.append(vector)
                    else:
                        self._vectors[pos] = vector
                else:
                    self._chunks[cid] = chunk
                    self._chunk_ids.append(cid)
                    self._id_to_pos[cid] = len(self._chunk_ids) - 1
                    self._vectors.append(vector)
                    self._doc_counts[chunk.meta.doc_id] = self._doc_counts.get(chunk.meta.doc_id, 0) + 1
                    new_count += 1
            self._persist_locked()
        return new_count

    def stats(self, doc_id: str) -> Dict[str, int]:
        return {"chunks_indexed": int(self._doc_counts.get(doc_id, 0))}

    def has_chunk(self, doc_id: str, chunk_id: str) -> bool:
        chunk = self._chunks.get(chunk_id)
        return bool(chunk and chunk.meta.doc_id == doc_id)

    def total_chunks(self) -> int:
        return len(self._chunk_ids)

    @property
    def uses_faiss(self) -> bool:
        return bool(self._use_faiss and self._faiss_index is not None)

    def search(
        self,
        query_embed: Sequence[float],
        k: int,
        filters: Mapping[str, object] | None = None,
    ) -> List[Chunk]:
        filters = filters or {}
        query = _normalize_vector(query_embed)
        with self._lock:
            if not self._chunk_ids:
                return []
            domains_filter = [str(value) for value in filters.get("domains", []) or []]
            min_year = filters.get("min_year")
            min_level = filters.get("min_evidence_level")
            doc_filter = filters.get("doc_id")
            candidate_ids: List[str] = []
            for cid in self._chunk_ids:
                chunk = self._chunks.get(cid)
                if chunk is None:
                    continue
                if doc_filter and chunk.meta.doc_id != doc_filter:
                    continue
                if domains_filter and not set(domains_filter).intersection(set(chunk.meta.domains)):
                    continue
                if min_year is not None and chunk.meta.year and chunk.meta.year < int(min_year):
                    continue
                if min_level is not None:
                    threshold = EVIDENCE_ORDER.get(str(min_level), 0)
                    if EVIDENCE_ORDER.get(chunk.meta.evidence_level, 0) < threshold:
                        continue
                candidate_ids.append(cid)
            if not candidate_ids:
                return []
            if self._use_faiss and not filters:
                return self._search_with_faiss_locked(query, k)
            return self._search_manual_locked(query, k, candidate_ids)

    def _search_with_faiss_locked(self, query: Sequence[float], k: int) -> List[Chunk]:
        if not self._faiss_index:
            self._rebuild_faiss_locked()
        if not self._faiss_index or not HAS_NUMPY or _np is None:
            return self._search_manual_locked(query, k, list(self._chunk_ids))
        query_np = _np.array([query], dtype="float32")
        limit = min(max(k, 1), len(self._chunk_ids))
        distances, indices = self._faiss_index.search(query_np, limit)  # type: ignore[attr-defined]
        hits: List[Chunk] = []
        for rank, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(self._chunk_ids):
                continue
            chunk_id = self._chunk_ids[idx]
            score = float(distances[0][rank])
            hits.append(self._clone_with_score(chunk_id, score))
        return hits

    def _search_manual_locked(self, query: Sequence[float], k: int, candidate_ids: Sequence[str]) -> List[Chunk]:
        scored: List[tuple[float, str]] = []
        for cid in candidate_ids:
            pos = self._id_to_pos.get(cid)
            if pos is None or pos >= len(self._vectors):
                continue
            vector = self._vectors[pos]
            if not vector:
                continue
            score = sum(a * b for a, b in zip(query, vector))
            scored.append((score, cid))
        scored.sort(key=lambda item: item[0], reverse=True)
        hits: List[Chunk] = []
        for score, cid in scored[:k]:
            hits.append(self._clone_with_score(cid, score))
        return hits

    def _clone_with_score(self, chunk_id: str, score: float) -> Chunk:
        chunk = self._chunks[chunk_id]
        meta_copy = replace(chunk.meta)
        clone = Chunk(meta=meta_copy, text=chunk.text, embedding=list(chunk.embedding))
        setattr(clone, "similarity", float(score))
        return clone

    def list_chunks(self, doc_id: str | None = None, limit: int | None = None) -> List[Chunk]:
        selected: List[Chunk] = []
        for chunk_id in self._chunk_ids:
            chunk = self._chunks.get(chunk_id)
            if chunk is None:
                continue
            if doc_id and chunk.meta.doc_id != doc_id:
                continue
            selected.append(chunk)
            if limit is not None and len(selected) >= limit:
                break
        return selected


__all__ = ["VectorDB", "EVIDENCE_ORDER"]
