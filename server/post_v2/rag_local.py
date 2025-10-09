"""Local RAG pipeline for post-session v2 with deterministic heuristics."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from server.library.embeddings_backend import EmbeddingsBackend
from server.library.vector_db import VectorDB

from .schemas import EvidenceItemLocal, SessionFacts

_VECTOR_DB: Optional[VectorDB] = None
_EMBED_BACKEND: Optional[EmbeddingsBackend] = None


def _env_truth(name: str, default: str = "true") -> bool:
    value = os.getenv(name, default)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _ensure_research_enabled() -> None:
    if not _env_truth("RESEARCH_V2", "true"):
        raise RuntimeError("research_v2_disabled")


def _vector_db() -> VectorDB:
    global _VECTOR_DB
    if _VECTOR_DB is None:
        store_dir = os.getenv("LIBRARY_VECTOR_STORE_DIR")
        _VECTOR_DB = VectorDB(store_dir=store_dir)
    return _VECTOR_DB


def _embeddings_backend() -> EmbeddingsBackend:
    global _EMBED_BACKEND
    if _EMBED_BACKEND is None:
        _EMBED_BACKEND = EmbeddingsBackend()
    return _EMBED_BACKEND


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _truncate(text: str, limit: int = 180) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _dedupe_preserve_order(items: Sequence[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        key = item.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _build_queries(facts: SessionFacts) -> List[str]:
    themes = [t for t in (facts.themes or []) if t]
    meds = [m.get("name") for m in (facts.meds or []) if isinstance(m, dict) and m.get("name")]
    asks = [a for a in (facts.asks or []) if a]

    seeds: List[str] = []
    for theme in themes[:6]:
        seeds.append(f"accompagnement clinique {theme}")
        seeds.append(f"{theme} evidence pratiques sociales")
    for med in meds[:4]:
        seeds.append(f"{med} effets secondaires santé mentale")
        seeds.append(f"{med} prise en charge matérialiste")
    for ask in asks[:4]:
        seeds.append(_truncate(ask, 140))
    if themes and meds:
        for theme in themes[:3]:
            for med in meds[:2]:
                seeds.append(f"{theme} {med} stratégies situées")
    if themes and asks:
        for ask in asks[:3]:
            seeds.append(f"réponse situated {themes[0]} : {_truncate(ask, 80)}")

    queries = [q for q in (_clean(seed) for seed in seeds) if len(q) >= 16]
    queries = _dedupe_preserve_order(queries)
    if not queries:
        return []

    base_stub = facts.patient or "patient·e"
    enrichers = [
        f"analyse clinique matérialiste {base_stub}",
        f"repères situated care {base_stub}",
        "psychoeducation evidence situated",
        "santé mentale critique pratiques collectives",
    ]
    idx = 0
    while len(queries) < 8 and idx < len(enrichers):
        queries.append(enrichers[idx])
        idx += 1
    return queries[:12]


def _format_pages(meta) -> str:
    start = getattr(meta, "page_start", None)
    end = getattr(meta, "page_end", None)
    if start and end:
        return f"{start}–{end}"
    if start:
        return str(start)
    if end:
        return str(end)
    return "s.o."


def _weight_evidence(level: str) -> float:
    mapping = {"élevé": 1.0, "eleve": 1.0, "modéré": 0.7, "modere": 0.7, "faible": 0.4, "inconnu": 0.3, "": 0.3}
    return mapping.get((level or "").lower(), 0.3)


def _weight_year(year: int) -> float:
    if not year:
        return 0.5
    current = time.localtime().tm_year
    window_start = current - 15
    if year <= window_start:
        return 0.1
    if year >= current:
        return 1.0
    span = max(1, current - window_start)
    return max(0.1, min(1.0, (year - window_start) / span))


def _score_chunk(semantic: float, evidence_weight: float, year_weight: float) -> float:
    return 0.7 * semantic + 0.2 * evidence_weight + 0.1 * year_weight


def _chunk_to_item(chunk, score: float) -> EvidenceItemLocal:
    return EvidenceItemLocal(
        title=chunk.meta.title,
        doc_id=chunk.meta.doc_id,
        pages=_format_pages(chunk.meta),
        extract=_clean(chunk.text) or "(extrait indisponible)",
        evidence_level=chunk.meta.evidence_level,
        year=int(chunk.meta.year or 0),
        domains=list(chunk.meta.domains or []),
        chunk_id=chunk.meta.chunk_id,
        score=float(round(score, 6)),
    )


def search_local_evidence(
    session_facts: SessionFacts,
    k: int = 12,
    filters: Optional[Dict[str, object]] = None,
    *,
    debug: bool = False,
) -> List[EvidenceItemLocal] | Tuple[List[EvidenceItemLocal], Dict[str, object]]:
    """Search the local library for evidence relevant to the session."""

    _ensure_research_enabled()
    filters = dict(filters or {})
    filters.setdefault("min_evidence_level", filters.get("min_evidence_level") or "modéré")

    queries = _build_queries(session_facts)
    if not queries:
        payload = {"k": k, "returned": 0, "queries": 0, "ms": 0, "empty": True}
        _log_event("post_v2_rag_local", payload)
        if debug:
            return [], {"queries": [], "selected_chunk_ids": []}
        return []

    start = time.perf_counter()
    backend = _embeddings_backend()
    vectors = backend.embed_texts(queries)
    db = _vector_db()

    candidate_map: Dict[str, Tuple[EvidenceItemLocal, float]] = {}
    for query, vector in zip(queries, vectors):
        if not vector:
            continue
        hits = db.search(vector, k=max(k * 2, 24), filters=filters)
        for chunk in hits:
            semantic = float(getattr(chunk, "similarity", 0.0))
            evidence_weight = _weight_evidence(chunk.meta.evidence_level)
            year_weight = _weight_year(int(chunk.meta.year or 0))
            final_score = _score_chunk(semantic, evidence_weight, year_weight)
            key = f"{chunk.meta.doc_id}:{chunk.meta.chunk_id}"
            item = _chunk_to_item(chunk, final_score)
            if key not in candidate_map or final_score > candidate_map[key][1]:
                candidate_map[key] = (item, final_score)

    sorted_items = sorted(candidate_map.values(), key=lambda entry: entry[1], reverse=True)
    limit = min(max(k, 6), 12)
    selected = [entry[0] for entry in sorted_items[:limit]]

    duration_ms = int((time.perf_counter() - start) * 1000)
    log_payload: Dict[str, object] = {
        "k": k,
        "returned": len(selected),
        "queries": len(queries),
        "ms": duration_ms,
    }
    if debug:
        log_payload["queries_detail"] = queries
        log_payload["chunk_ids"] = [item.chunk_id for item in selected]
    _log_event("post_v2_rag_local", log_payload)

    if debug:
        return selected, {"queries": queries, "selected_chunk_ids": [item.chunk_id for item in selected]}
    return selected


def _log_event(event: str, payload: Dict[str, object]) -> None:
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    record.update(payload)
    try:
        journal_path = Path(__file__).resolve().parents[1] / "library" / "store" / "journal.log"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover
        pass


__all__ = ["search_local_evidence"]
