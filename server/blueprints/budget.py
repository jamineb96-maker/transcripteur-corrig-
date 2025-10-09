"""Budget cognitif endpoints to remove 404s and expose demo data."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

import json

bp = Blueprint("budget", __name__, url_prefix="/api/budget")

_PRESETS: List[Dict[str, Any]] = [
    {"id": "morning_routine", "label": "Routine matinale", "cost": 3},
    {"id": "work_session", "label": "Session de travail ciblée", "cost": 5},
    {"id": "family_dinner", "label": "Repas de famille", "cost": 4},
    {"id": "sport", "label": "Activité sportive douce", "cost": 2},
    {"id": "admin", "label": "Tâches administratives", "cost": 3},
]


def _history_path(slug: str) -> Path:
    root = Path("instance/archives") / slug / "budget"
    root.mkdir(parents=True, exist_ok=True)
    return root / "history.json"


@bp.get("/presets")
def get_presets():
    return jsonify({"presets": _PRESETS, "count": len(_PRESETS)})


@bp.get("/history")
def get_history():
    slug = (request.args.get("patient") or "").strip()
    if not slug:
        return jsonify({"entries": [], "patient": None})
    path = _history_path(slug)
    if not path.exists():
        return jsonify({"entries": [], "patient": slug})
    try:
        data = path.read_text(encoding="utf-8")
    except OSError:
        return jsonify({"entries": [], "patient": slug})
    try:
        entries = json.loads(data)
    except Exception:
        entries = []
    if not isinstance(entries, list):
        entries = []
    return jsonify({"entries": entries, "patient": slug})


@bp.post("/history")
def append_history():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    slug = (payload.get("patient") or payload.get("slug") or "").strip()
    if not slug:
        return jsonify({"success": False, "message": "Patient manquant."}), 400

    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "budget": payload.get("budget"),
        "note": payload.get("note"),
    }
    path = _history_path(slug)
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        else:
            existing = []
    except Exception:
        existing = []
    existing.append(entry)
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"success": True, "saved": entry, "patient": slug})
