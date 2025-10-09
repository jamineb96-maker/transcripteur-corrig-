# [pipeline-v3 begin]
"""Endpoints Flask pour la pipeline pré-séance v3."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from flask import Blueprint, Response, current_app, jsonify, request

from modules.pre_session_plan import build_pre_session_plan
from modules.prompt_builder import build_final_prompt
from modules.research_engine import run_research

LOGGER = logging.getLogger("assist.pipeline_v3.api")

bp = Blueprint("pipeline_v3", __name__, url_prefix="/api")

try:  # pragma: no cover - dépendance optionnelle
    from pydantic import BaseModel, ValidationError
except ModuleNotFoundError:  # pragma: no cover - fallback
    BaseModel = None  # type: ignore
    ValidationError = Exception  # type: ignore


if BaseModel is not None:  # pragma: no cover - dépendance optionnelle

    class _PlanRequest(BaseModel):  # type: ignore[misc]
        raw_context: Dict[str, Any]
        previous_plan: Dict[str, Any] | None = None

    class _ResearchRequest(BaseModel):  # type: ignore[misc]
        plan: Dict[str, Any]
        raw_context: Dict[str, Any]
        allow_internet: bool = True

    class _PromptRequest(BaseModel):  # type: ignore[misc]
        plan: Dict[str, Any]
        research: Dict[str, Any]
        mail_brut: str
        prenom: str | None = None

else:  # pragma: no cover - fallback

    _PlanRequest = dict  # type: ignore
    _ResearchRequest = dict  # type: ignore
    _PromptRequest = dict  # type: ignore


def _validate_payload(model: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    if BaseModel is None:
        return payload
    try:
        obj = model(**payload)
        return obj.model_dump()
    except ValidationError as exc:  # pragma: no cover - dépendance optionnelle
        raise ValueError(str(exc)) from exc


def _json_error(message: str, status: int = 400) -> Response:
    response = jsonify({"ok": False, "message": message})
    response.status_code = status
    response.headers["X-Pipeline-Version"] = "presession-v3"
    return response


def _log_request(event: str, **extra: Any) -> None:
    LOGGER.info("pipeline_v3.%s", event, extra=extra)


@bp.post("/pre_session/plan")
def pre_session_plan() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        validated = _validate_payload(_PlanRequest, payload)
    except ValueError as exc:
        return _json_error(f"Requête invalide : {exc}")
    raw_context = validated.get("raw_context") or {}
    previous_plan = validated.get("previous_plan")
    try:
        plan = build_pre_session_plan(raw_context, previous_plan)
    except ValueError as exc:
        return _json_error(str(exc))
    response = jsonify(plan)
    response.headers["X-Pipeline-Version"] = "presession-v3"
    _log_request(
        "plan",
        mail_len=len(str(raw_context.get("mail_brut", ""))),
        orientation=len(plan.get("orientation", "")),
    )
    return response


@bp.post("/research")
def research() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        validated = _validate_payload(_ResearchRequest, payload)
    except ValueError as exc:
        return _json_error(f"Requête invalide : {exc}")
    plan = validated.get("plan") or {}
    raw_context = dict(validated.get("raw_context") or {})
    allow_internet = bool(validated.get("allow_internet", True))
    results = run_research(plan, raw_context, allow_internet=allow_internet)
    txt = json.dumps(results, ensure_ascii=False).replace("http://", "").replace("https://", "")
    response = current_app.response_class(txt, mimetype="application/json")
    response.headers["X-Pipeline-Version"] = "presession-v3"
    _log_request(
        "research",
        allow_internet=allow_internet,
        local=len(results.get("local_library", [])),
        internet=len(results.get("internet", [])),
    )
    return response


@bp.post("/prompt/final")
def prompt_final() -> Response:
    payload = request.get_json(silent=True) or {}
    try:
        validated = _validate_payload(_PromptRequest, payload)
    except ValueError as exc:
        return _json_error(f"Requête invalide : {exc}")
    plan = validated.get("plan") or {}
    research_payload = validated.get("research") or {}
    mail_brut = str(validated.get("mail_brut") or "")
    prenom = str(validated.get("prenom") or "la personne")
    prompt = build_final_prompt(plan, research_payload, mail_brut, prenom)
    response = jsonify({"prompt": prompt})
    response.headers["X-Pipeline-Version"] = "presession-v3"
    _log_request(
        "prompt",
        prompt_len=len(prompt),
        local=len(research_payload.get("local_library", [])),
        internet=len(research_payload.get("internet", [])),
    )
    return response


__all__ = ["bp"]
# [pipeline-v3 end]
