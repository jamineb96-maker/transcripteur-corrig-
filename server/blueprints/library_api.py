"""REST endpoints for the clinical library v2."""

from __future__ import annotations

import logging
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from flask import Blueprint, current_app, jsonify, request

from server.library.embeddings_backend import EmbeddingsBackend
from server.library.indexer import upsert_chunks
from server.library.journal import log_event
from server.library.models import Notion
from server.library.notions import (
    list_notions_for_doc,
    notion_links_count,
    save_notion,
    search_notions,
)
from server.library.vector_db import VectorDB
from server.utils.docid import doc_id_to_fs_path, legacy_fs_path

LOGGER = logging.getLogger(__name__)

bp = Blueprint("library_api", __name__, url_prefix="/api/library")

_VECTOR_DB: Optional[VectorDB] = None


def _vector_db() -> VectorDB:
    global _VECTOR_DB
    if _VECTOR_DB is None:
        store_dir = current_app.config.get("LIBRARY_VECTOR_STORE_DIR")
        _VECTOR_DB = VectorDB(store_dir=store_dir)
    return _VECTOR_DB


def _safe_json() -> Dict[str, Any]:
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload
    return {}


def _config_truth(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _is_store_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".writable"
        with probe.open("w", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink(missing_ok=True)
        return True
    except Exception:  # pragma: no cover - filesystem edge cases
        return False


def _resolve_pdf_path(doc_id: str, doc_path: str | None = None) -> Optional[str]:
    candidate = (doc_path or "").strip()
    if candidate and os.path.exists(candidate):
        return candidate
    config = current_app.config
    instance_root = Path(current_app.instance_path)
    library_root = Path(config.get("LIBRARY_ROOT", instance_root / "library"))
    raw_root = Path(config.get("LIBRARY_RAW_ROOT", library_root / "raw_pdfs"))
    shard = _config_truth(config.get("LIBRARY_FS_SHARDING"), default=True)
    candidates: List[Path] = []
    try:
        candidates.append(doc_id_to_fs_path(raw_root, doc_id, shard=shard).with_suffix(".pdf"))
    except Exception:  # pragma: no cover - invalid doc id
        pass
    try:
        candidates.append(legacy_fs_path(raw_root, doc_id).with_suffix(".pdf"))
    except Exception:  # pragma: no cover - legacy fallback
        pass
    candidates.append(raw_root / f"{doc_id}.pdf")
    for path in candidates:
        if path.exists():
            return str(path)
    return candidate if candidate else None


def _embedding_status(backend: EmbeddingsBackend) -> str:
    if backend.is_ready():
        return "ok"
    if backend.name == "fake":
        return "fake"
    return "unavailable"


def _extract_sentences(text: str, max_sentences: int = 3) -> str:
    sentences = [segment.strip() for segment in text.split(". ") if segment.strip()]
    return ". ".join(sentences[:max_sentences]).strip()


@lru_cache(maxsize=128)
def _notions_mapping(doc_id: str) -> tuple[Dict[str, List[Dict[str, str]]], int]:
    notions = list_notions_for_doc(doc_id)
    mapping: Dict[str, List[Dict[str, str]]] = {}
    for notion in notions:
        for source in notion.get("sources", []):
            if not isinstance(source, Mapping):
                continue
            if source.get("doc_id") != doc_id:
                continue
            for chunk_id in source.get("chunk_ids", []) or []:
                mapping.setdefault(str(chunk_id), []).append(
                    {
                        "id": str(notion.get("id", "")),
                        "label": str(notion.get("label", notion.get("id", ""))),
                    }
                )
    return mapping, len(notions)


def _serialize_chunk_for_ui(chunk, notions_map: Mapping[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    chunk_id = chunk.meta.chunk_id
    return {
        "chunk_id": chunk_id,
        "doc_id": chunk.meta.doc_id,
        "title": chunk.meta.title,
        "authors": chunk.meta.authors,
        "year": chunk.meta.year,
        "page_start": chunk.meta.page_start,
        "page_end": chunk.meta.page_end,
        "evidence_level": chunk.meta.evidence_level,
        "domains": chunk.meta.domains,
        "keywords": chunk.meta.keywords,
        "text": chunk.text,
        "preview": _extract_sentences(chunk.text),
        "notions": notions_map.get(chunk_id, []),
    }


@bp.get("/health")
def health_endpoint():
    db = _vector_db()
    backend = EmbeddingsBackend()
    research_v2 = _config_truth(current_app.config.get("RESEARCH_V2"), default=False)
    status = {
        "store_writable": _is_store_writable(db.store_dir),
        "embeddings_backend": _embedding_status(backend),
        "research_v2": research_v2,
        "faiss": db.uses_faiss,
    }
    log_event(
        "health",
        {
            "store_writable": status["store_writable"],
            "emb": status["embeddings_backend"],
            "v2": research_v2,
            "faiss": status["faiss"],
        },
    )
    return jsonify(status)


@bp.post("/index_chunks")
def index_chunks_endpoint():
    payload = _safe_json()
    doc_id = str(payload.get("doc_id") or "").strip()
    doc_path = str(payload.get("doc_path") or "").strip()
    meta_raw = payload.get("meta") or {}
    if not isinstance(meta_raw, Mapping):
        meta_raw = {}
    if not doc_id:
        return jsonify({"error": "invalid_request", "message": "doc_id requis."}), 400
    resolved_path = _resolve_pdf_path(doc_id, doc_path)
    if not resolved_path or not os.path.exists(resolved_path):
        return jsonify({"error": "not_found", "message": "PDF introuvable."}), 404
    allow_fake = _config_truth(os.getenv("ALLOW_FAKE_EMBEDS"), default=False)
    backend = EmbeddingsBackend()
    if not backend.is_ready() and _embedding_status(backend) == "unavailable" and not allow_fake:
        return jsonify({"error": "embeddings_unavailable"}), 503
    meta: Dict[str, Any] = dict(meta_raw)
    meta["doc_id"] = doc_id
    if meta_raw.get("pseudonymize") or meta_raw.get("pseudonymize_before_llm"):
        meta["pseudonymize"] = True
    db = _vector_db()
    try:
        result = upsert_chunks(resolved_path, meta, backend=backend, vector_db=db)
    except Exception as exc:  # pragma: no cover - robustesse
        LOGGER.exception("index_chunks_failed", extra={"doc_id": doc_id})
        return jsonify({"error": "index_failed", "message": str(exc)}), 500
    chunks = db.list_chunks(doc_id)
    notions_map, notion_count = _notions_mapping(doc_id)
    serialized = [_serialize_chunk_for_ui(chunk, notions_map) for chunk in chunks]
    doc_stats = db.stats(doc_id)
    response = {
        "doc_id": doc_id,
        "inserted": result.get("inserted", 0),
        "total": doc_stats.get("chunks_indexed", 0),
        "ms": result.get("ms"),
        "pseudonymized": bool(meta.get("pseudonymize")),
        "doc_chunks": serialized,
        "doc_chunk_count": len(serialized),
        "notions_count": notion_count,
        "notion_links": notion_links_count(doc_id),
    }
    log_event(
        "index_chunks_endpoint",
        {
            "doc_id": doc_id,
            "inserted": response["inserted"],
            "total": response["total"],
            "ms": response.get("ms"),
            "pseudonymized": response.get("pseudonymized"),
            "chunks": response["doc_chunk_count"],
        },
    )
    return jsonify(response)


@bp.get("/debug/doc/<doc_id>")
def debug_doc_endpoint(doc_id: str):
    db = _vector_db()
    stats = db.stats(doc_id)
    notions = list_notions_for_doc(doc_id)
    response = {
        "doc_id": doc_id,
        "chunks_indexed": stats.get("chunks_indexed", 0),
        "notions": len(notions),
        "notion_links": notion_links_count(doc_id),
    }
    log_event(
        "debug_doc",
        {
            "doc_id": doc_id,
            "chunks_indexed": response["chunks_indexed"],
            "notions": response["notions"],
            "notion_links": response["notion_links"],
        },
    )
    return jsonify(response)


@bp.post("/notions")
def save_notion_endpoint():
    payload = _safe_json()
    try:
        notion = Notion.from_dict(payload)
    except Exception as exc:  # pragma: no cover - invalid payload
        return jsonify({"error": "invalid_payload", "message": str(exc)}), 400
    try:
        saved = save_notion(notion, vector_db=_vector_db())
    except ValueError as exc:
        return jsonify({"error": "validation_failed", "message": str(exc)}), 400
    _notions_mapping.cache_clear()
    log_event(
        "save_notion_endpoint",
        {
            "id": saved.id,
            "doc_ids": sorted({source.doc_id for source in saved.sources}),
            "sources": sum(len(source.chunk_ids) for source in saved.sources),
        },
    )
    return jsonify(saved.to_dict())


@bp.get("/notions")
def list_notions_endpoint():
    query = request.args.get("q", "")
    doc_id = request.args.get("doc_id")
    notions = search_notions(query, doc_id=doc_id)
    payload = [notion.to_dict() for notion in notions]
    log_event(
        "list_notions_endpoint",
        {
            "doc_id": doc_id,
            "query": query,
            "count": len(payload),
        },
    )
    return jsonify({"items": payload, "count": len(payload)})


@bp.post("/search_debug")
def search_debug_endpoint():
    payload = _safe_json()
    query = str(payload.get("query") or "").strip()
    if not query:
        return jsonify({"error": "invalid_request", "message": "query requis."}), 400
    filters = payload.get("filters") or {}
    if not isinstance(filters, Mapping):
        filters = {}
    domains = [str(value) for value in filters.get("domains", []) if str(value).strip()]
    min_year = filters.get("min_year")
    try:
        min_year_int = int(min_year) if min_year is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_request", "message": "min_year invalide."}), 400
    min_evidence = filters.get("min_evidence_level")
    doc_id = filters.get("doc_id")
    backend = EmbeddingsBackend()
    allow_fake = _config_truth(os.getenv("ALLOW_FAKE_EMBEDS"), default=False)
    status = _embedding_status(backend)
    if status == "unavailable" and not allow_fake:
        return jsonify({"error": "embeddings_unavailable"}), 503
    started = time.perf_counter()
    try:
        vectors = backend.embed_texts([query])
    except Exception as exc:  # pragma: no cover - backend failure
        LOGGER.exception("search_debug_embed_failed")
        return jsonify({"error": "embedding_failed", "message": str(exc)}), 502
    if not vectors:
        return jsonify({"error": "embedding_failed", "message": "embedding vide."}), 502
    query_vector = vectors[0]
    db = _vector_db()
    search_filters = {
        "domains": domains,
    }
    if min_year_int is not None:
        search_filters["min_year"] = min_year_int
    if isinstance(min_evidence, str) and min_evidence.strip():
        search_filters["min_evidence_level"] = min_evidence.strip()
    if isinstance(doc_id, str) and doc_id.strip():
        search_filters["doc_id"] = doc_id.strip()
    try:
        hits = db.search(query_vector, int(payload.get("k", 8) or 8), search_filters)
    except Exception as exc:  # pragma: no cover - defensive
        LOGGER.exception("search_debug_failed")
        return jsonify({"error": "search_failed", "message": str(exc)}), 500
    results = []
    for chunk in hits:
        similarity = float(getattr(chunk, "similarity", 0.0))
        results.append(
            {
                "title": chunk.meta.title,
                "doc_id": chunk.meta.doc_id,
                "page_start": chunk.meta.page_start,
                "page_end": chunk.meta.page_end,
                "extract": _extract_sentences(chunk.text),
                "score": similarity,
                "evidence_level": chunk.meta.evidence_level,
                "year": chunk.meta.year,
                "chunk_id": chunk.meta.chunk_id,
            }
        )
    duration_ms = int((time.perf_counter() - started) * 1000)
    log_event(
        "search_debug",
        {
            "query": query,
            "hits": len(results),
            "filters": search_filters,
            "ms": duration_ms,
        },
    )
    return jsonify({"hits": results, "ms": duration_ms})


@bp.get("/chunks")
def list_chunks_endpoint():
    doc_id = (request.args.get("doc_id") or "").strip()
    if not doc_id:
        return jsonify({"error": "invalid_request", "message": "doc_id requis."}), 400
    db = _vector_db()
    chunks = db.list_chunks(doc_id)
    notions_map, notion_count = _notions_mapping(doc_id)
    payload = [_serialize_chunk_for_ui(chunk, notions_map) for chunk in chunks]
    response = {
        "doc_id": doc_id,
        "chunks": payload,
        "total": len(payload),
        "notions_count": notion_count,
        "notion_links": notion_links_count(doc_id),
    }
    log_event(
        "list_chunks_endpoint",
        {
            "doc_id": doc_id,
            "total": response["total"],
            "notions": response["notions_count"],
            "notion_links": response["notion_links"],
        },
    )
    return jsonify(response)


__all__ = ["bp"]
