"""API Post-séance (plan, recherche, pharmacologie).

Cette version s'appuie sur les nouveaux services déterministes décrits dans
le cahier des charges : plan structuré, recherche unifiée et analyse
pharmacologique normalisée.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from modules.research_v2.audit import configure_logger, log_json

from server.research import prepare_prompt
from server.research.utils import clean_lines, count_lines, ensure_text, sanitize_block
from server.services.pharma_analyzer import analyze_pharmacology
from server.services.plan_post_session import format_structured_plan, generate_structured_plan
from server.services.research_unified import run_unified_research

bp = Blueprint("research_api", __name__, url_prefix="/api/post/research")
_AUDIT_LOGGER = configure_logger()


def _json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


@bp.post("/plan_v2")
def plan_v2():
    start = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    transcript = ensure_text(payload.get("transcript"))
    if not transcript:
        return _json_error("empty_transcript")

    try:
        plan_structured = generate_structured_plan(transcript)
    except ValueError as exc:
        return _json_error(str(exc) or "plan_generation_failed", status=422)

    plan_text = clean_lines(format_structured_plan(plan_structured), max_lines=20)
    duration_ms = int((time.perf_counter() - start) * 1000)
    log_json(
        _AUDIT_LOGGER,
        {
            "event": "plan_structured",
            "lines": count_lines(plan_text),
            "ms": duration_ms,
            "word_count": plan_structured.get("word_count"),
        },
    )
    return jsonify({"ok": True, "plan_text": plan_text, "plan_structured": plan_structured})


@bp.post("/pharma")
def pharma():
    start = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    transcript = ensure_text(payload.get("transcript"))
    plan_text = ensure_text(payload.get("plan_text"))
    if not transcript and not plan_text:
        return _json_error("empty_payload")

    analysis = analyze_pharmacology(transcript, plan_text)
    duration_ms = int((time.perf_counter() - start) * 1000)
    log_json(
        _AUDIT_LOGGER,
        {
            "event": "research_pharma_v3",
            "molecules": len(analysis.get("molecules", [])),
            "ms": duration_ms,
        },
    )
    return jsonify(
        {
            "ok": True,
            "pharma_block": analysis.get("export_block"),
            "entries": analysis.get("molecules", []),
            "memo": analysis.get("memo", ""),
        }
    )


def _build_biblio_block(biblio: List[str]) -> str:
    if not biblio:
        return "[EXTRAITS BIBLIO]\n– néant explicite –"
    lines = ["[EXTRAITS BIBLIO]"]
    for item in biblio:
        lines.append(f"– {item}")
    return "\n".join(lines)


@bp.post("/library")
def library():
    start = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    transcript = ensure_text(payload.get("transcript"))
    plan_text = ensure_text(payload.get("plan_text"))
    if not transcript and not plan_text:
        return _json_error("empty_payload")

    search_input = "\n\n".join(part for part in (transcript, plan_text) if part)
    try:
        research = run_unified_research(search_input)
    except ValueError as exc:
        return _json_error(str(exc) or "research_failed", status=422)

    biblio_block = _build_biblio_block(research.get("biblio", []))
    duration_ms = int((time.perf_counter() - start) * 1000)
    log_json(
        _AUDIT_LOGGER,
        {
            "event": "research_unified",
            "cards": len(research.get("cards", [])),
            "biblio": len(research.get("biblio", [])),
            "ms": duration_ms,
        },
    )
    return jsonify(
        {
            "ok": True,
            "cards": research.get("cards", []),
            "items": research.get("cards", []),
            "biblio": research.get("biblio", []),
            "biblio_block": biblio_block,
            "keywords": research.get("keywords", []),
        }
    )


@bp.post("/compose")
def compose():
    start = time.perf_counter()
    payload = request.get_json(silent=True) or {}
    transcript = ensure_text(payload.get("transcript"))
    plan_text = ensure_text(payload.get("plan_text"))
    pharma_block = ensure_text(payload.get("pharma_block"))
    biblio_block = ensure_text(payload.get("biblio_block"))

    if not transcript:
        return _json_error("empty_transcript")
    if not plan_text:
        return _json_error("empty_plan")

    research_payload: Dict[str, Any] = {
        "pharmacologie": sanitize_block(pharma_block),
        "bibliographie": sanitize_block(biblio_block),
        "evidence_sheet": sanitize_block("\n\n".join(filter(None, [pharma_block, biblio_block]))),
    }

    prompt = prepare_prompt(transcript=transcript, plan_text=plan_text, research=research_payload)
    duration_ms = int((time.perf_counter() - start) * 1000)
    log_json(
        _AUDIT_LOGGER,
        {
            "event": "research_compose",
            "chars": len(prompt),
            "ms": duration_ms,
        },
    )
    return jsonify({"ok": True, "prompt": prompt})


__all__ = ["bp"]
