"""API unifiée pour la recherche clinique (local + web)."""
from __future__ import annotations

import logging
import time
from typing import List

from flask import Blueprint, current_app, jsonify, request

from config import settings
from server.services.library_search import LocalSearchEngine
from modules.research_engine import search_web_openai

LOGGER = logging.getLogger("assist.research.api")

bp = Blueprint("library_search", __name__, url_prefix="/library")
search_bp = bp

_ENGINE: LocalSearchEngine | None = None


def _get_engine() -> LocalSearchEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = LocalSearchEngine()
    return _ENGINE


@bp.route("/search", methods=["POST"])
def search_library() -> tuple[str, int] | tuple[dict, int]:
    start = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    queries = payload.get("queries")
    scope = (payload.get("scope") or "local").strip().lower()
    top_k = payload.get("top_k") or 5
    patient_hash = payload.get("patient_hash")

    if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
        return jsonify({"ok": False, "why": "queries_invalid"}), 200
    try:
        top_k_int = max(1, min(int(top_k), 20))
    except (TypeError, ValueError):
        top_k_int = 5

    LOGGER.info(
        "research.query_received",
        extra={"queries": len(queries), "scope": scope, "top_k": top_k_int, "patient_hash": bool(patient_hash)},
    )

    engine = _get_engine()

    local_results: List[dict] = []
    if scope in {"local", "both", ""}:
        local_results = engine.search(queries, top_k=top_k_int)
        LOGGER.info("research.results_local", extra={"count": len(local_results)})

    web_enabled = current_app.config.get("RESEARCH_WEB_ENABLED", settings.RESEARCH_WEB_ENABLED)
    web_results: List[dict] = []
    web_error: str | None = None
    if scope in {"web", "both"} and not web_enabled:
        LOGGER.info("research.results_web", extra={"count": 0, "skipped": True})
    elif scope in {"web", "both"} and web_enabled:
        web_query = " ".join(q.strip() for q in queries if isinstance(q, str)).strip()
        if not web_query:
            LOGGER.info(
                "research.results_web",
                extra={"count": 0, "skipped": False, "empty_query": True},
            )
        else:
            try:
                web_results = search_web_openai(web_query, k=top_k_int)[:top_k_int]
            except Exception:  # pragma: no cover - robustesse API externe
                web_results = []
                web_error = "web_search_failed"
                LOGGER.exception("research.web_search_failed", extra={"query": web_query})
            LOGGER.info(
                "research.results_web",
                extra={
                    "count": len(web_results),
                    "skipped": False,
                    "error": bool(web_error),
                },
            )

    duration_ms = int((time.perf_counter() - start) * 1000)
    LOGGER.info("research.query_duration", extra={"duration_ms": duration_ms})

    if scope == "web":
        source = "web"
        results = web_results
    elif scope == "both":
        source = "both"
        results = local_results + web_results
    else:
        source = "local"
        results = local_results

    response: dict = {"ok": True, "source": source, "results": results}
    if web_error:
        response["ok"] = False if scope == "web" else True
        response["web_error"] = web_error

    return jsonify(response), 200


__all__ = ["bp", "search_bp"]

