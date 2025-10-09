"""API blueprint providing journal critique resources."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request

from modules.research_engine import invalidate_journal_cache
from server.services.journal_service import JournalService

LOGGER = logging.getLogger(__name__)

bp = Blueprint("journal_critique", __name__, url_prefix="/api/journal-critique")


class ValidationError(ValueError):
    """Erreur de validation pour les payloads JSON."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = details or {}


def _service() -> JournalService:
    service = current_app.extensions.get("journal_service")
    if not isinstance(service, JournalService):  # pragma: no cover - configuration
        raise RuntimeError("JournalService non initialisé")
    return service


def _json_success(payload: Dict[str, Any], status: int = 200):
    return jsonify({"success": True, **payload}), status


def _json_error(
    code: str,
    message: str,
    *,
    status: int = 400,
    details: Optional[Dict[str, Any]] = None,
):
    LOGGER.warning("Journal critique erreur (%s): %s", code, message, extra={"details": details or {}})
    return (
        jsonify({"success": False, "error": {"code": code, "message": message, "details": details or {}}}),
        status,
    )


def _parse_list_param(values: List[str]) -> List[str]:
    items: List[str] = []
    for value in values:
        if not value:
            continue
        chunks = [chunk.strip() for chunk in value.split(",") if chunk.strip()]
        for chunk in chunks:
            if chunk not in items:
                items.append(chunk)
    return items


def _parse_iso_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError("format de date invalide", {"value": value}) from exc


def _validate_entry_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("payload invalide")
    entry_id = str(payload.get("id", "")).strip()
    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValidationError("Le titre est requis", {"field": "title"})

    body = payload.get("body_md")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise ValidationError("body_md doit être une chaîne", {"field": "body_md"})

    def _ensure_strings(values: Any, field: str) -> List[str]:
        if values is None:
            return []
        if not isinstance(values, list):
            raise ValidationError(f"{field} doit être une liste", {"field": field})
        return [str(item).strip() for item in values if isinstance(item, str) and item.strip()]

    def _ensure_mappings(values: Any, field: str, keys: Tuple[str, ...]) -> List[Dict[str, str]]:
        if values is None:
            return []
        if not isinstance(values, list):
            raise ValidationError(f"{field} doit être une liste", {"field": field})
        results: List[Dict[str, str]] = []
        for item in values:
            if not isinstance(item, dict):
                raise ValidationError(f"{field} doit contenir des objets", {"field": field})
            record = {key: str(item.get(key, "")).strip() for key in keys}
            results.append(record)
        return results

    tags = _ensure_strings(payload.get("tags"), "tags")
    concepts = _ensure_strings(payload.get("concepts"), "concepts")
    sources = _ensure_mappings(payload.get("sources"), "sources", ("label", "url"))
    patients = _ensure_mappings(payload.get("patients"), "patients", ("id", "name"))

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    meta = dict(meta)

    return {
        "id": entry_id or None,
        "title": title,
        "body_md": body,
        "tags": tags,
        "concepts": concepts,
        "sources": sources,
        "patients": patients,
        "meta": meta,
    }


@bp.get("/ping")
def ping():
    """Simple endpoint used for health checks."""

    return _json_success({"data": "journal-pong"})


@bp.get("/list")
def list_entries():
    service = _service()
    try:
        tags = _parse_list_param(request.args.getlist("tags"))
        concepts = _parse_list_param(request.args.getlist("concepts"))
        patient = request.args.get("patient", "").strip() or None
        query = (request.args.get("query") or "").strip()
        limit_raw = request.args.get("limit", "50").strip() or "50"
        offset_raw = request.args.get("offset", "0").strip() or "0"
        try:
            limit = max(0, min(200, int(limit_raw)))
            offset = max(0, int(offset_raw))
        except ValueError as exc:
            raise ValidationError("limit/offset invalides") from exc
        date_from = _parse_iso_date(request.args.get("from"))
        date_to = _parse_iso_date(request.args.get("to"))
    except ValidationError as exc:
        return _json_error("validation_error", str(exc), details=getattr(exc, "details", {}))

    try:
        items, total = service.list_entries(
            query=query,
            tags=tags,
            concepts=concepts,
            patient=patient,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
    except OSError:
        LOGGER.error("Lecture de l'index journal impossible", exc_info=True)
        return _json_error("io_error", "Lecture impossible", status=500)

    return _json_success({"items": items, "total": total})


@bp.get("/get")
def get_entry():
    entry_id = (request.args.get("id") or "").strip()
    if not entry_id:
        return _json_error("validation_error", "Paramètre id requis")

    try:
        entry = _service().get_entry(entry_id)
    except OSError:
        LOGGER.error("Lecture de l'entrée %s impossible", entry_id, exc_info=True)
        return _json_error("io_error", "Lecture impossible", status=500)

    if not entry:
        return _json_error("not_found", "Entrée introuvable", status=404)

    return _json_success({"item": entry})


@bp.post("/save")
def save_entry():
    payload = request.get_json(silent=True)
    if payload is None:
        return _json_error("validation_error", "Corps JSON requis")

    try:
        entry_payload = _validate_entry_payload(payload)
    except ValidationError as exc:
        return _json_error("validation_error", str(exc), details=getattr(exc, "details", {}))

    service = _service()
    try:
        saved = service.save_entry(entry_payload)
    except FileNotFoundError:
        return _json_error("not_found", "Entrée introuvable", status=404)
    except ValueError as exc:
        return _json_error("validation_error", str(exc))
    except RuntimeError:
        LOGGER.error("Erreur d'écriture journal", exc_info=True)
        return _json_error("io_error", "Enregistrement impossible", status=500)
    except OSError:
        LOGGER.error("Erreur d'écriture journal", exc_info=True)
        return _json_error("io_error", "Enregistrement impossible", status=500)

    invalidate_journal_cache()
    return _json_success({"item": saved})


@bp.delete("/delete")
def delete_entry():
    entry_id = (request.args.get("id") or "").strip()
    if not entry_id:
        return _json_error("validation_error", "Paramètre id requis")

    try:
        _service().delete_entry(entry_id)
    except FileNotFoundError:
        return _json_error("not_found", "Entrée introuvable", status=404)
    except OSError:
        LOGGER.error("Suppression journal impossible", exc_info=True)
        return _json_error("io_error", "Suppression impossible", status=500)

    invalidate_journal_cache()
    return _json_success({})


@bp.post("/reindex")
def reindex():
    try:
        count = _service().reindex()
    except OSError:
        LOGGER.error("Réindexation journal impossible", exc_info=True)
        return _json_error("io_error", "Réindexation impossible", status=500)

    invalidate_journal_cache()
    return _json_success({"count": count})


_DOMAIN_FALLBACKS: Dict[str, List[Dict[str, object]]] = {
    "somatique": [
        {
            "title": "Cartographie somato-cognitive",
            "suggested_tags": ["somatique", "auto-observation"],
            "skeleton_md": "## Explorer les signaux somatiques\n- Localiser les tensions actuelles\n- Identifier les contextes qui amplifient ou apaisent ces signaux\n- Lister les ressources corporelles disponibles à court terme",
        },
        {
            "title": "Ancrage respiratoire express",
            "suggested_tags": ["respiration", "auto-régulation"],
            "skeleton_md": "## Micro-pause respiratoire\n- 4 cycles d'inspiration lente\n- 4 cycles d'expiration prolongée\n- Noter une observation corporelle après chaque cycle",
        },
    ],
    "relationnel": [
        {
            "title": "Cartographie des allié·e·s",
            "suggested_tags": ["soutien", "alliances"],
            "skeleton_md": "## Alliances actuelles\n- Lister trois personnes ou collectifs\n- Décrire le soutien concret attendu\n- Identifier le prochain micro-pas relationnel",
        },
    ],
    "cognitif": [
        {
            "title": "Résultats uniques",
            "suggested_tags": ["re-membering", "narratif"],
            "skeleton_md": "## Résultat inattendu\n- Décrire un moment où la situation a été différente\n- Nommer les compétences mobilisées\n- Imaginer comment les réutiliser",
        },
    ],
    "politique": [
        {
            "title": "Lettre au problème",
            "suggested_tags": ["externalisation", "positionnement"],
            "skeleton_md": "## Prendre position\n- Saluer le problème\n- Expliquer son impact politique\n- Définir les limites non négociables",
        },
    ],
    "valeurs": [
        {
            "title": "Boussole de valeurs",
            "suggested_tags": ["valeurs", "alignement"],
            "skeleton_md": "## Valeurs en présence\n- Nommer trois valeurs sollicitées\n- Décrire comment elles s'expriment\n- Identifier un geste pour les honorer",
        },
    ],
}

_DEFAULT_PROMPTS: List[Dict[str, object]] = [
    {
        "id": "externalisation-probleme",
        "title": "Externalisation du problème",
        "family": "externalisation",
        "familyLabel": "Externalisation",
        "tags": ["externalisation", "positionnement"],
        "reading_level": "accessible",
        "budget_profile": "léger",
    },
    {
        "id": "resultats-uniques",
        "title": "Résultats uniques",
        "family": "resultats_uniques",
        "familyLabel": "Résultats uniques",
        "tags": ["re-membering", "narratif"],
        "reading_level": "intermédiaire",
        "budget_profile": "moyen",
    },
    {
        "id": "remembering-alliances",
        "title": "Re-membering des alliances",
        "family": "alliances",
        "familyLabel": "Alliances",
        "tags": ["relationnel", "alliances"],
        "reading_level": "accessible",
        "budget_profile": "léger",
    },
    {
        "id": "cartographie-somato",
        "title": "Cartographie somato-cognitive",
        "family": "somatique",
        "familyLabel": "Somatique",
        "tags": ["somatique", "auto-observation"],
        "reading_level": "accessible",
        "budget_profile": "léger",
    },
    {
        "id": "lettre-au-probleme",
        "title": "Lettre au problème",
        "family": "politique",
        "familyLabel": "Positionnement politique",
        "tags": ["politique", "valeurs"],
        "reading_level": "intermédiaire",
        "budget_profile": "moyen",
    },
]


@dataclass
class PromptsPayload:
    prompts: List[Dict[str, object]]
    source: str


def _library_root() -> Path:
    instance_library = Path(current_app.instance_path) / "library"
    if instance_library.exists():
        return instance_library
    project_library = Path(current_app.root_path).resolve().parent / "library"
    return project_library


def _load_prompts_index() -> PromptsPayload:
    library_root = _library_root()
    index_path = library_root / "journal_prompts_index.json"
    if index_path.exists():
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                prompts = [prompt for prompt in payload if isinstance(prompt, dict)]
                LOGGER.info("Journal critique : prompts chargés depuis %s", index_path)
                return PromptsPayload(prompts=prompts, source="json")
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("Impossible de lire %s : %s", index_path, exc)
    LOGGER.info("Journal critique : prompts de démonstration utilisés")
    return PromptsPayload(prompts=_DEFAULT_PROMPTS, source="demo")


def _read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_templates_for_domain(domain: str) -> Tuple[List[Dict[str, object]], str]:
    library_root = _library_root()
    templates_dir = library_root / "journal_prompts"
    entries: List[Dict[str, object]] = []
    if templates_dir.exists():
        for candidate in sorted(templates_dir.glob("*.md")):
            content = _read_markdown(candidate)
            if not content:
                continue
            entries.append(
                {
                    "title": candidate.stem.replace("_", " ").strip().title(),
                    "suggested_tags": [domain],
                    "skeleton_md": content.strip(),
                }
            )
    if entries:
        if len(entries) > 5:
            entries = entries[:5]
        LOGGER.info(
            "Journal critique : %d recommandations chargées (%s)",
            len(entries),
            templates_dir,
        )
        return entries, "library"
    LOGGER.info("Journal critique : recommandations de démonstration pour %s", domain)
    return _DOMAIN_FALLBACKS.get(domain, []), "demo"


@bp.get("/prompts")
def list_prompts():
    payload = _load_prompts_index()
    return jsonify({"ok": True, "source": payload.source, "prompts": payload.prompts})


@bp.get("/recommendations")
def list_recommendations():
    domain = (request.args.get("domain") or "somatique").lower()
    if domain not in _DOMAIN_FALLBACKS:
        domain = "somatique"
    templates, source = _load_templates_for_domain(domain)
    return jsonify({"ok": True, "domain": domain, "source": source, "templates": templates})


@bp.post("/preview")
def preview_journal():
    body = request.get_json(silent=True) or {}
    return jsonify(
        {
            "ok": True,
            "message": "Prévisualisation indisponible dans la démo.",
            "echo": body,
        }
    )


__all__ = ["bp"]
