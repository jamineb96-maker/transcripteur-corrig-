"""Blueprint exposing the post-session v2 API."""

from __future__ import annotations

import json
import os
import time
from os import getenv
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from server.post_v2.endpoints import (
    default_token_estimator,
    run_consolidate,
    run_extract,
    run_megaprompt,
    run_rag_local,
    run_rag_web,
)
from server.post_v2.style_profile import style_blocks

bp = Blueprint("post_v2_api", __name__, url_prefix="/api/post/v2")

POST_V2 = getenv("POST_V2", "true").lower() == "true"
RESEARCH_V2 = getenv("RESEARCH_V2", "true").lower() == "true"
WEB_PROVIDER = getenv("RAG_WEB_PROVIDER", "none")
ALLOWLIST_PATH = getenv(
    "RAG_WEB_ALLOWLIST",
    str(Path(__file__).resolve().parents[1] / "research" / "allowlist.txt"),
)


def _log_event(event: str, payload: Dict[str, Any]) -> None:
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    record.update(payload)
    try:
        journal_path = Path(__file__).resolve().parents[2] / "library" / "store" / "journal.log"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover
        pass


@bp.route("/extract", methods=["POST"])
def extract_signals():
    start = time.perf_counter()
    payload = request.get_json(force=True) or {}
    debug = request.args.get("debug", "false").lower() == "true"
    result = run_extract(payload, debug=debug)
    if debug and isinstance(result, tuple):
        facts, debug_payload = result
        response = facts.to_dict()
        response["debug"] = debug_payload
    else:
        facts = result if not isinstance(result, tuple) else result[0]
        response = facts.to_dict()
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event("post_v2_api_extract", {"ms": duration_ms, "debug": debug})
    return jsonify(response)


@bp.route("/rag_local", methods=["POST"])
def rag_local():
    start = time.perf_counter()
    payload = request.get_json(force=True) or {}
    filters = payload.get("filters") or {}
    debug = request.args.get("debug", "false").lower() == "true"
    result = run_rag_local(payload, filters, debug=debug)
    if debug and isinstance(result, tuple):
        items, debug_payload = result
        response = {
            "items": [item.to_dict() for item in items],
            "debug": debug_payload,
        }
    else:
        items = result if not isinstance(result, tuple) else result[0]
        response = [item.to_dict() for item in items]
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event(
        "post_v2_api_rag_local",
        {"returned": len(items), "ms": duration_ms, "debug": debug},
    )
    return jsonify(response)


@bp.route("/rag_web", methods=["POST"])
def rag_web():
    start = time.perf_counter()
    payload = request.get_json(force=True) or {}
    items = run_rag_web(payload)
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event("post_v2_api_rag_web", {"returned": len(items), "ms": duration_ms})
    return jsonify([item.to_dict() for item in items])


@bp.route("/consolidate", methods=["POST"])
def consolidate():
    start = time.perf_counter()
    payload = request.get_json(force=True) or {}
    kp = run_consolidate(payload)
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event("post_v2_api_consolidate", {"axes": len(kp.axes), "ms": duration_ms})
    return jsonify(kp.to_dict())


@bp.route("/megaprompt", methods=["POST"])
def megaprompt():
    start = time.perf_counter()
    payload = request.get_json(force=True) or {}
    bundle = run_megaprompt(payload, default_token_estimator)
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event("post_v2_api_megaprompt", {"tokens": bundle.token_estimate, "ms": duration_ms})
    return jsonify(bundle.to_dict())


@bp.route("/health", methods=["GET"])
def health():
    if os.path.exists(ALLOWLIST_PATH):
        with open(ALLOWLIST_PATH, "r", encoding="utf-8") as handle:
            allowlist_count = sum(
                1 for line in handle if line.strip() and not line.strip().startswith("#")
            )
    else:
        allowlist_count = 0
    payload = {
        "post_v2": POST_V2,
        "research_v2": RESEARCH_V2,
        "web_provider": WEB_PROVIDER,
        "allowlist_count": allowlist_count,
    }
    _log_event("post_v2_api_health", payload)
    return jsonify(payload)


@bp.route("/search_debug", methods=["POST"])
def search_debug():
    start = time.perf_counter()
    payload = request.get_json(force=True) or {}
    filters = payload.get("filters") or {}
    facts_payload = payload.get("session_facts") or payload
    local = run_rag_local(facts_payload, filters)
    response: Dict[str, Any] = {
        "local": [item.to_dict() for item in local[:5]],
    }
    if os.getenv("RAG_WEB_PROVIDER", "none").lower() != "none":
        web = run_rag_web(facts_payload)
        response["web"] = [item.to_dict() for item in web[:3]]
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event("post_v2_api_search_debug", {"local": len(response.get("local", [])), "ms": duration_ms})
    return jsonify(response)


@bp.route("/style_profile", methods=["GET"])
def style_profile():
    start = time.perf_counter()
    profile_text = style_blocks()
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event("post_v2_api_style_profile", {"ms": duration_ms})
    return jsonify({"style_profile": profile_text})


__all__ = ["bp"]
