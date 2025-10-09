"""Blueprint léger pour la résolution de patients par prénom."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from server.services.patients import find_patients_by_firstname


bp = Blueprint("patients_api_v2", __name__, url_prefix="/api/patients")


@bp.get("/resolve")
def resolve_patient():
    firstname = request.args.get("firstname", "")
    matches = find_patients_by_firstname(firstname or "")
    payload = {"ok": True, "matches": matches}
    return jsonify(payload)


__all__ = ["bp"]
