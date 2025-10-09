"""Vector-store powered clinical research engine (v2)."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from server.library.embeddings_backend import EmbeddingsBackend
from server.library.journal import log_event
from server.library.notions import list_notions
from server.library.vector_db import VectorDB

LOGGER = logging.getLogger(__name__)

_VECTOR_DB: Optional[VectorDB] = None


def _vector_db() -> VectorDB:
    global _VECTOR_DB
    if _VECTOR_DB is None:
        store_dir = os.getenv("LIBRARY_VECTOR_STORE_DIR")
        _VECTOR_DB = VectorDB(store_dir=store_dir)
    return _VECTOR_DB


def _embed_query(query: str) -> List[float]:
    backend = EmbeddingsBackend()
    vectors = backend.embed_texts([query])
    if not vectors:
        raise RuntimeError("query_embedding_failed")
    return vectors[0]


def _weight_evidence(level: str) -> float:
    normalized = (level or "").strip().lower()
    mapping = {
        "élevé": 1.0,
        "eleve": 1.0,
        "modéré": 0.7,
        "modere": 0.7,
        "faible": 0.4,
        "inconnu": 0.3,
        "": 0.3,
    }
    return mapping.get(normalized, 0.3)


def _weight_year(year: int) -> float:
    if not year:
        return 0.5
    current_year = datetime.utcnow().year
    window_start = current_year - 15
    if year <= window_start:
        return 0.0
    if year >= current_year:
        return 1.0
    span = current_year - window_start
    if span <= 0:
        return 0.5
    return max(0.0, min(1.0, (year - window_start) / span))


def _extract_sentences(text: str, max_sentences: int = 3) -> str:
    sentences = re.split(r"(?<=[\.\!\?])\s+", text.strip())
    filtered = [sentence.strip() for sentence in sentences if sentence.strip()]
    snippet = " ".join(filtered[:max_sentences])
    return snippet.strip()


def _notions_by_chunk() -> Dict[str, List[Dict[str, str]]]:
    mapping: Dict[str, List[Dict[str, str]]] = {}
    for notion in list_notions():
        for source in notion.sources:
            for chunk_id in source.chunk_ids:
                mapping.setdefault(chunk_id, []).append({"id": notion.id, "label": notion.label})
    return mapping


def _final_score(semantic: float, level: float, year_weight: float) -> float:
    return 0.70 * semantic + 0.20 * level + 0.10 * year_weight


def _filters(
    domains: Optional[Iterable[str]],
    min_year: Optional[int],
    min_evidence_level: Optional[str],
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if domains:
        payload["domains"] = [domain for domain in domains if domain]
    if min_year:
        payload["min_year"] = int(min_year)
    if min_evidence_level:
        payload["min_evidence_level"] = str(min_evidence_level)
    return payload


def search_evidence(
    query: str,
    domains: Optional[List[str]] = None,
    min_year: Optional[int] = None,
    min_evidence_level: Optional[str] = None,
    k: int = 8,
) -> List[Dict[str, Any]]:
    """Search for evidence chunks with reranking and notion enrichment."""

    query = (query or "").strip()
    if not query:
        return []
    vector = _embed_query(query)
    filters = _filters(domains, min_year, min_evidence_level)
    db = _vector_db()
    candidate_k = max(k * 2, 12)
    initial_hits = db.search(vector, k=candidate_k, filters=filters)
    notions_mapping = _notions_by_chunk()
    entries: List[Dict[str, Any]] = []
    for chunk in initial_hits:
        semantic = float(getattr(chunk, "similarity", 0.0))
        level_weight = _weight_evidence(chunk.meta.evidence_level)
        year_weight = _weight_year(chunk.meta.year)
        final = _final_score(semantic, level_weight, year_weight)
        extract = _extract_sentences(chunk.text)
        entry = {
            "title": chunk.meta.title,
            "doc_id": chunk.meta.doc_id,
            "authors": chunk.meta.authors,
            "page_start": chunk.meta.page_start,
            "page_end": chunk.meta.page_end,
            "extract": extract,
            "excerpt": extract,
            "score": round(final, 6),
            "score_semantic": round(semantic, 6),
            "evidence_level": chunk.meta.evidence_level,
            "year": chunk.meta.year,
            "notions": notions_mapping.get(chunk.meta.chunk_id, []),
            "chunk_id": chunk.meta.chunk_id,
            "domains": chunk.meta.domains,
            "keywords": chunk.meta.keywords,
        }
        entries.append(entry)
    entries.sort(key=lambda item: item["score"], reverse=True)
    results = entries[:k]
    log_event(
        "search_v2",
        {
            "query": query,
            "hits": len(results),
            "filters": filters,
        },
    )
    return results


__all__ = ["search_evidence"]
