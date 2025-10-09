"""Patients API blueprint exposing archive-backed listings."""

from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

from server.services.patients import (
    create_patient as svc_create_patient,
    get_diagnostics,
    get_patients_source,
    list_patients,
    refresh_cache,
)

bp = Blueprint("patients", __name__, url_prefix="/api")


def _payload(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    items = list(snapshot.get("items", [])) if isinstance(snapshot.get("items"), list) else []
    source = snapshot.get("source") or get_patients_source()
    dir_abs = snapshot.get("dir_abs")
    count = snapshot.get("count") if isinstance(snapshot.get("count"), int) else len(items)
    roots = list(snapshot.get("roots", [])) if isinstance(snapshot.get("roots"), list) else []
    payload = {
        "ok": True,
        "success": True,
        "source": source,
        "dir_abs": dir_abs,
        "count": count,
        "items": items,
        "patients": items,
        "roots": roots,
    }
    return payload


@bp.get("/patients")
def get_patients():
    refresh = str(request.args.get("refresh") or "").strip().lower()
    force_refresh = refresh in {"1", "true", "yes", "force"}
    snapshot = list_patients(refresh=force_refresh)
    return jsonify(_payload(snapshot))


@bp.post("/patients/refresh")
def refresh_patients():
    items, _roots = refresh_cache()
    snapshot = {
        "items": items,
        "count": len(items),
        "source": get_patients_source(),
        "roots": _roots,
        "dir_abs": _roots[0] if _roots else None,
    }
    return jsonify(_payload(snapshot))


@bp.post("/patients")
def create_patient():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    display_name = (
        str(
            payload.get("display_name")
            or payload.get("displayName")
            or payload.get("name")
            or payload.get("full_name")
            or ""
        )
        .strip()
    )
    slug = payload.get("slug") or payload.get("id") or payload.get("identifier")
    email = payload.get("email") or payload.get("mail")

    if not display_name:
        return jsonify({"ok": False, "message": "Le nom du patient est requis."}), 400

    try:
        created = svc_create_patient(display_name=display_name, slug=slug, email=email)
    except ValueError as exc:  # validation error
        return jsonify({"ok": False, "message": str(exc)}), 400

    snapshot = list_patients(refresh=True)
    payload = _payload(snapshot)
    payload.update({"created": created, "selectedId": created.get("slug")})
    return jsonify(payload)


@bp.get("/patients/diagnostics")
def patients_diagnostics():
    snapshot = get_diagnostics()
    payload = {
        "ok": True,
        "source": snapshot.get("source"),
        "dir_abs": snapshot.get("dir_abs"),
        "total_entries": snapshot.get("total_entries"),
        "kept": snapshot.get("kept"),
        "count": snapshot.get("count"),
        "sample": snapshot.get("sample", []),
        "roots": snapshot.get("roots", []),
        "dropped": snapshot.get("dropped", []),
        "items": snapshot.get("items", []),
    }
    return jsonify(payload)
