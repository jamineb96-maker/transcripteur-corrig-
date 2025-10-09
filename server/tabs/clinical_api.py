"""API REST pour la mémoire clinique locale."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, Response, current_app, jsonify, request

from server.services.clinical_indexer import ClinicalIndexer
from server.services.clinical_repo import ClinicalRepo, ClinicalRepoError
from server.services.clinical_service import ClinicalService, ClinicalServiceError
from server.services.trauma_mapper import TraumaMapper, TraumaMapperError

LOGGER = logging.getLogger("clinical.api")

bp = Blueprint("clinical_api", __name__, url_prefix="/api/clinical")


def _get_repo() -> ClinicalRepo:
    app = current_app
    repo = app.extensions.get("clinical_repo")
    if repo is None:
        repo = ClinicalRepo(instance_root=Path(app.instance_path))
        app.extensions["clinical_repo"] = repo
    return repo


def _get_service() -> ClinicalService:
    app = current_app
    service = app.extensions.get("clinical_service")
    if service is None:
        repo = _get_repo()
        service = ClinicalService(repo=repo)
        app.extensions["clinical_service"] = service
    return service


def _get_indexer() -> ClinicalIndexer:
    service = _get_service()
    return service.indexer


def _get_trauma_mapper() -> TraumaMapper:
    app = current_app
    mapper = app.extensions.get("trauma_mapper")
    if mapper is None:
        mapper = TraumaMapper(repo=_get_repo())
        app.extensions["trauma_mapper"] = mapper
    return mapper


def _json_success(data: Dict[str, Any], status: int = 200) -> Response:
    payload = {"success": True, "data": data}
    return jsonify(payload), status


def _json_error(error: str, status: int = 400, details: Dict[str, Any] | None = None) -> Response:
    payload: Dict[str, Any] = {"success": False, "error": error}
    if details:
        payload["details"] = details
    return jsonify(payload), status


@bp.get("/patients")
def list_patients() -> Response:
    repo = _get_repo()
    patients = repo.list_patients()
    LOGGER.debug("[clinical] %d patients listés", len(patients))
    return _json_success({"patients": patients})


@bp.get("/patient/<slug>/overview")
def patient_overview(slug: str) -> Response:
    try:
        overview = _get_service().get_patient_overview(slug)
    except ClinicalRepoError as exc:
        LOGGER.warning("[clinical] overview indisponible", exc_info=True)
        return _json_error("patient_not_found", 404)
    return _json_success(overview)


@bp.get("/patient/<slug>/session/<path:session_path>/materials")
def session_materials(slug: str, session_path: str) -> Response:
    try:
        materials = _get_service().get_session_material(slug, session_path)
    except ClinicalServiceError:
        return _json_error("session_not_found", 404)
    except ClinicalRepoError:
        return _json_error("patient_not_found", 404)
    return _json_success(materials)


@bp.get("/patient/<slug>/trauma")
def trauma_profile(slug: str) -> Response:
    try:
        profile = _get_trauma_mapper().get_trauma_profile(slug)
    except ClinicalRepoError:
        return _json_error("patient_not_found", 404)
    return _json_success(profile)


@bp.post("/patient/<slug>/milestones")
def add_milestone(slug: str) -> Response:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _json_error("invalid_payload", 400)
    try:
        updated = _get_service().update_milestones(slug, payload)
    except ClinicalServiceError:
        return _json_error("invalid_milestone", 422)
    return _json_success(updated, status=201)


@bp.post("/patient/<slug>/quotes")
def add_quote(slug: str) -> Response:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _json_error("invalid_payload", 400)
    try:
        updated = _get_service().append_quote(slug, payload)
    except ClinicalServiceError:
        return _json_error("invalid_quote", 422)
    return _json_success(updated, status=201)


@bp.post("/patient/<slug>/contexts")
def update_contexts(slug: str) -> Response:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _json_error("invalid_payload", 400)
    try:
        updated = _get_service().update_contexts(slug, payload)
    except ClinicalServiceError:
        return _json_error("invalid_contexts", 422)
    return _json_success(updated)


@bp.post("/patient/<slug>/contradictions")
def update_contradictions(slug: str) -> Response:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _json_error("invalid_payload", 400)
    try:
        updated = _get_service().update_contradictions(slug, payload)
    except ClinicalServiceError:
        return _json_error("invalid_contradictions", 422)
    return _json_success(updated)


@bp.post("/patient/<slug>/trauma")
def update_trauma(slug: str) -> Response:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return _json_error("invalid_payload", 400)
    try:
        updated = _get_service().update_trauma(slug, payload)
    except ClinicalServiceError:
        return _json_error("invalid_trauma", 422)
    return _json_success(updated)


@bp.post("/reindex/<slug>")
def rebuild_index(slug: str) -> Response:
    try:
        index = _get_indexer().rebuild_index(slug)
    except ClinicalRepoError:
        return _json_error("patient_not_found", 404)
    return _json_success(index)


@bp.post("/patient/<slug>/trauma/interpretations")
def trauma_interpretations(slug: str) -> Response:
    payload = request.get_json(silent=True) or {}
    signals = payload.get("signals") if isinstance(payload, dict) else []
    if not isinstance(signals, list):
        return _json_error("invalid_signals", 400)
    try:
        suggestions = _get_trauma_mapper().suggest_interpretations(slug, signals)
    except (ClinicalRepoError, TraumaMapperError):
        return _json_error("patient_not_found", 404)
    return _json_success(suggestions)


__all__ = ["bp"]

