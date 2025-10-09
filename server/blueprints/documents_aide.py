"""Blueprint exposing the document workshop endpoints."""
from __future__ import annotations

import json
import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Tuple

from flask import Blueprint, Response, current_app, jsonify, render_template, request, send_from_directory
from jinja2 import pass_context

from .utils.docx import html_to_docx
from .utils.grammar_fr import Grammar
from .utils.pdf import html_to_pdf

LOGGER = logging.getLogger(__name__)

bp = Blueprint("documents_aide", __name__, url_prefix="/api/documents-aide")

TEMPLATES: List[Dict[str, Any]] = []
TEMPLATE_LOOKUP: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _templates_root(app) -> Path:
    return Path(app.root_path) / "templates" / "documents_aide"


def _archives_root(app) -> Path:
    return Path(app.instance_path) / "archives"


def _supports_root(app, patient_id: str) -> Path:
    return _archives_root(app) / patient_id / "supports"


def _index_path(app, patient_id: str) -> Path:
    return _supports_root(app, patient_id) / "index.json"


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _scan_latest_file(directory: Path) -> Tuple[Path | None, Any]:
    if not directory.exists():
        return (None, None)
    files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return (None, None)
    data = _load_json(files[0])
    return (files[0], data)


def _default_profile() -> Dict[str, Any]:
    return {"gender": "f", "pronoun": "elle", "tv": "tu"}


def _load_profile(app, patient_id: str) -> Dict[str, Any]:
    if not patient_id:
        profile = _default_profile()
        profile["id"] = ""
        profile["display_name"] = ""
        return profile
    profile_path = _archives_root(app) / patient_id / "profile.json"
    if profile_path.exists():
        payload = _load_json(profile_path)
        if isinstance(payload, dict):
            profile = _default_profile()
            for key in ("gender", "pronoun", "tv"):
                if payload.get(key):
                    profile[key] = payload.get(key)
            for key in ("full_name", "email", "practitioner", "plural", "display_name", "displayName"):
                if payload.get(key) is not None:
                    profile[key] = payload.get(key)
            if "displayName" in profile and "display_name" not in profile:
                profile["display_name"] = profile["displayName"]
            profile.setdefault("display_name", profile.get("full_name", patient_id))
            profile.setdefault("full_name", profile.get("display_name", patient_id))
            profile["id"] = patient_id
            return profile
    profile = _default_profile()
    profile["id"] = patient_id
    profile["display_name"] = patient_id
    profile["full_name"] = patient_id
    return profile


def _extract_last_plan(app, patient_id: str) -> Dict[str, Any]:
    plan_dir = _archives_root(app) / patient_id / "plans"
    _, data = _scan_latest_file(plan_dir)
    return data if isinstance(data, dict) else {}


def _extract_last_notes(app, patient_id: str) -> Dict[str, Any]:
    notes_dir = _archives_root(app) / patient_id / "notes"
    _, data = _scan_latest_file(notes_dir)
    return data if isinstance(data, dict) else {}


def _derive_suggestions(notes: Dict[str, Any]) -> List[str]:
    suggestions: List[str] = []
    text_sources: Iterable[str] = []
    if isinstance(notes, dict):
        text_sources = [json.dumps(notes, ensure_ascii=False)]
    joined = " ".join(text_sources).lower()
    if any(keyword in joined for keyword in ("fatigue", "épuis", "épuisement")):
        suggestions.append("Surveiller les signaux de fatigue sur 24h")
    if any(keyword in joined for keyword in ("energie", "énergie", "vide")):
        suggestions.append("Documenter les activités qui rechargent vs coûtent")
    if any(keyword in joined for keyword in ("masqu", "brouillard", "surcharge")):
        suggestions.append("Planifier des pauses sensorielles ritualisées")
    return suggestions


def _namespace(obj: Any) -> Any:
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _namespace(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_namespace(v) for v in obj]
    return obj


def _build_template_context(app, patient_id: str) -> Dict[str, Any]:
    notes = _extract_last_notes(app, patient_id)
    plan = _extract_last_plan(app, patient_id)
    context = {
        "last_notes": notes,
        "last_plan": plan,
        "last_activity_date": plan.get("last_activity_date", ""),
        "last_immediate_note": notes.get("immediate", "") if isinstance(notes, dict) else "",
        "next_morning": {
            "reveil": notes.get("next_morning", {}).get("wake", "") if isinstance(notes, dict) else "",
            "tensions": notes.get("next_morning", {}).get("body", "") if isinstance(notes, dict) else "",
            "clarte": notes.get("next_morning", {}).get("clarity", "") if isinstance(notes, dict) else "",
            "suggestions": notes.get("next_morning", {}).get("actions", "") if isinstance(notes, dict) else "",
        },
        "energy": {
            "plus2": notes.get("energy", {}).get("plus", "") if isinstance(notes, dict) else "",
            "moins2": notes.get("energy", {}).get("minus", "") if isinstance(notes, dict) else "",
            "signaux_corp": notes.get("signals", {}).get("body", "") if isinstance(notes, dict) else "",
            "signaux_emo": notes.get("signals", {}).get("emotions", "") if isinstance(notes, dict) else "",
            "signaux_arret": notes.get("signals", {}).get("stop", "") if isinstance(notes, dict) else "",
        },
        "pauses": {
            "rituels": (plan.get("pauses", {}).get("rituals") or []) if isinstance(plan, dict) else [],
            "options": plan.get("pauses", {}).get(
                "options",
                {
                    "silence": False,
                    "lumiere": False,
                    "contact": False,
                    "proprio": False,
                    "odeur": False,
                    "mouvement": False,
                },
            ),
            "trousse": plan.get("pauses", {}).get("kit", "") if isinstance(plan, dict) else "",
        },
        "deadlines": plan.get("deadlines", {}) if isinstance(plan, dict) else {},
        "couts": notes.get("hidden_costs", {}) if isinstance(notes, dict) else {},
        "grille": plan.get("daily_grid", {}) if isinstance(plan, dict) else {},
        "suggestions": _derive_suggestions(notes),
    }
    # Normalise expected sub-structures
    if not isinstance(context.get("deadlines"), dict):
        context["deadlines"] = {}
    if not isinstance(context.get("couts"), dict):
        context["couts"] = {}
    if not isinstance(context.get("grille"), dict):
        context["grille"] = {}
    if not isinstance(context["deadlines"].get("jalons"), list):
        context["deadlines"]["jalons"] = []
    context["deadlines"].setdefault("communication", "")
    context["deadlines"].setdefault("signaux", "")
    context["couts"].setdefault("cuilleres", "")
    context["couts"].setdefault("strategies", "")
    for key in ("plus2", "moins2", "signaux_corp", "signaux_emo", "signaux_arret"):
        context["energy"].setdefault(key, "")
    if not isinstance(context.get("energy"), dict):
        context["energy"] = {}
    if not isinstance(context.get("pauses"), dict):
        context["pauses"] = {}
    if not isinstance(context["pauses"].get("rituels"), list):
        context["pauses"]["rituels"] = []
    if not isinstance(context["pauses"].get("options"), dict):
        context["pauses"]["options"] = {
            "silence": False,
            "lumiere": False,
            "contact": False,
            "proprio": False,
            "odeur": False,
            "mouvement": False,
        }
    context.setdefault("next_morning", {})
    if not isinstance(context["grille"].get("lignes"), list):
        context["grille"]["lignes"] = []
    context["grille"].setdefault("observations", "")
    return context


def _load_templates(app) -> None:
    global TEMPLATES, TEMPLATE_LOOKUP
    templates_path = _templates_root(app) / "templates.json"
    try:
        payload = json.loads(templates_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            TEMPLATES = payload
            TEMPLATE_LOOKUP = {item["id"]: item for item in payload if isinstance(item, dict) and "id" in item}
            LOGGER.info("[documents_aide] %s modèles chargés", len(TEMPLATES))
            return
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.error("Impossible de charger les modèles de documents : %s", exc)
    TEMPLATES = []
    TEMPLATE_LOOKUP = {}


def _register_grammar_helpers(app) -> None:
    env = app.jinja_env

    def _make_helper(name: str):
        @pass_context
        def _helper(context, *args):
            grammar: Grammar = context.get("grammar")
            if not isinstance(grammar, Grammar):
                grammar = Grammar(_default_profile())
            method = getattr(grammar, name)
            return method(*args)

        return _helper

    helpers = {
        "t": _make_helper("t"),
        "T": _make_helper("T"),
        "te": _make_helper("te"),
        "ton": _make_helper("ton"),
        "acc": _make_helper("acc"),
        "pron": _make_helper("pron"),
        "etre": _make_helper("etre"),
        "avoir": _make_helper("avoir"),
        "suff_e": _make_helper("suff_e"),
        "plur": _make_helper("plur"),
    }
    env.globals.update(helpers)


@bp.record_once
def _on_register(state) -> None:
    app = state.app
    _load_templates(app)
    _register_grammar_helpers(app)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@bp.get("/templates")
def list_templates():
    return jsonify({"ok": True, "templates": TEMPLATES})


@bp.get("/context")
def get_context():
    patient_id = request.args.get("patient", "").strip()
    profile = _load_profile(current_app, patient_id)
    context = _build_template_context(current_app, patient_id) if patient_id else {}
    return jsonify(
        {
            "ok": True,
            "patient": patient_id,
            "profile": profile,
            "context": context,
            "suggestions": context.get("suggestions", []),
        }
    )


def _load_history(app, patient_id: str) -> List[Dict[str, Any]]:
    supports = _supports_root(app, patient_id)
    index_path = _index_path(app, patient_id)
    entries: List[Dict[str, Any]] = []
    if index_path.exists():
        data = _load_json(index_path)
        if isinstance(data, list):
            entries = data
    else:
        if supports.exists():
            for file in supports.glob("*.*"):
                if file.name == "index.json":
                    continue
                stat = file.stat()
                entries.append(
                    {
                        "file": file.name,
                        "template": "",
                        "title": file.stem,
                        "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "bytes": stat.st_size,
                        "format": file.suffix.lstrip("."),
                        "path": f"/api/documents-aide/download/{patient_id}/{file.name}",
                    }
                )
        _ensure_dir(index_path.parent)
        index_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    for entry in entries:
        if "file" in entry:
            entry.setdefault("path", f"/api/documents-aide/download/{patient_id}/{entry['file']}")
    # Ensure newest first
    entries.sort(key=lambda item: item.get("created", ""), reverse=True)
    return entries


@bp.get("")
def history():
    patient_id = request.args.get("patient", "").strip()
    if not patient_id:
        return jsonify({"ok": True, "history": []})
    return jsonify({"ok": True, "history": _load_history(current_app, patient_id)})


def _safe_filename(name: str) -> str:
    keep = [c if c.isalnum() or c in {"-", "_"} else "_" for c in name.lower()]
    return "".join(keep)


def _render_template(template_id: str, profile: Dict[str, Any], inputs: Dict[str, Any], context: Dict[str, Any]) -> str:
    template_entry = TEMPLATE_LOOKUP.get(template_id)
    if not template_entry:
        raise KeyError(f"Template {template_id} introuvable")
    template_file = template_entry.get("template")
    grammar = Grammar(profile)
    patient_info = {
        "id": profile.get("id"),
        "full_name": profile.get("full_name", profile.get("display_name", profile.get("id"))),
        "practitioner": profile.get("practitioner"),
    }
    rendered = render_template(
        f"documents_aide/{template_file}",
        title=template_entry.get("title", template_id),
        inputs=inputs,
        profile=profile,
        grammar=grammar,
        context=_namespace(context),
        patient=patient_info,
        generated_at=datetime.utcnow(),
        page_number=1,
    )
    return rendered


def _save_history_entry(app, patient_id: str, entry: Dict[str, Any]) -> None:
    index_path = _index_path(app, patient_id)
    history = []
    if index_path.exists():
        data = _load_json(index_path)
        if isinstance(data, list):
            history = data
    history.insert(0, entry)
    index_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


@bp.post("/generate")
def generate_document():
    payload = request.get_json(silent=True) or {}
    template_id = payload.get("template_id")
    patient_id = payload.get("patient")
    inputs = payload.get("inputs", {})
    requested_format = payload.get("format", "pdf").lower()
    override_profile = payload.get("override_profile", {})
    preview = request.args.get("preview") == "true" or payload.get("preview")

    if not template_id:
        return jsonify({"ok": False, "error": "template_id requis"}), 400
    if not patient_id:
        return jsonify({"ok": False, "error": "patient requis"}), 400

    base_profile = _load_profile(current_app, patient_id)
    profile = {**base_profile, **{k: v for k, v in override_profile.items() if v}}
    context = _build_template_context(current_app, patient_id) if patient_id else {}

    try:
        html = _render_template(template_id, profile, inputs, context)
    except Exception as exc:
        LOGGER.exception("Erreur lors du rendu du modèle %s", template_id)
        return jsonify({"ok": False, "error": str(exc)}), 500

    if preview:
        return jsonify({"ok": True, "html": html})

    if requested_format not in {"pdf", "docx"}:
        return jsonify({"ok": False, "error": "format non supporté"}), 400

    generated_at = datetime.utcnow()
    supports_dir = _ensure_dir(_supports_root(current_app, patient_id))
    timestamp = generated_at.strftime("%Y-%m-%d_%H%M")
    safe_template = _safe_filename(template_id)
    filename = f"{timestamp}__{safe_template}.{requested_format}"
    output_path = supports_dir / filename

    try:
        if requested_format == "pdf":
            html_to_pdf(html, output_path)
        else:
            template_entry = TEMPLATE_LOOKUP.get(template_id, {})
            html_to_docx(html, output_path, title=template_entry.get("title"))
    except Exception as exc:  # pragma: no cover - runtime error logging
        LOGGER.exception("Erreur lors de la génération du fichier : %s", exc)
        return jsonify({"ok": False, "error": "export impossible"}), 500

    stat = output_path.stat()
    entry = {
        "file": filename,
        "template": template_id,
        "title": TEMPLATE_LOOKUP.get(template_id, {}).get("title", template_id),
        "created": generated_at.isoformat() + "Z",
        "bytes": stat.st_size,
        "format": requested_format,
        "path": f"/api/documents-aide/download/{patient_id}/{filename}",
    }
    _save_history_entry(current_app, patient_id, entry)
    LOGGER.info(
        "[documents_aide] génération %s/%s (%s) - %s octets",
        patient_id,
        template_id,
        requested_format,
        stat.st_size,
    )
    return jsonify({"ok": True, "path": f"/api/documents-aide/download/{patient_id}/{filename}", "entry": entry})


@bp.get("/download/<patient_id>/<path:filename>")
def download_document(patient_id: str, filename: str) -> Response:
    supports_dir = _supports_root(current_app, patient_id)
    if not (supports_dir / filename).exists():
        return jsonify({"ok": False, "error": "fichier introuvable"}), 404
    mime, _ = mimetypes.guess_type(filename)
    return send_from_directory(supports_dir, filename, mimetype=mime or "application/octet-stream", as_attachment=True)


@bp.delete("/<patient_id>/<path:filename>")
def delete_document(patient_id: str, filename: str):
    supports_dir = _supports_root(current_app, patient_id)
    target = supports_dir / filename
    if not target.exists():
        return jsonify({"ok": False, "error": "fichier introuvable"}), 404
    target.unlink()
    index_path = _index_path(current_app, patient_id)
    if index_path.exists():
        data = _load_json(index_path)
        if isinstance(data, list):
            data = [entry for entry in data if entry.get("file") != filename]
            index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


@bp.post("/rename")
def rename_document():
    payload = request.get_json(silent=True) or {}
    patient_id = payload.get("patient")
    filename = payload.get("file")
    new_title = payload.get("title")
    if not (patient_id and filename and new_title):
        return jsonify({"ok": False, "error": "paramètres manquants"}), 400
    index_path = _index_path(current_app, patient_id)
    if not index_path.exists():
        return jsonify({"ok": False, "error": "historique introuvable"}), 404
    data = _load_json(index_path)
    if not isinstance(data, list):
        return jsonify({"ok": False, "error": "index corrompu"}), 500
    for entry in data:
        if entry.get("file") == filename:
            entry["title"] = new_title
            break
    index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"ok": True})


__all__ = ["bp"]
