"""Post-session blueprint providing transcription and summarisation pipelines."""

from __future__ import annotations

import json
import os
import re
import textwrap
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from server.services.openai_client import (
    DEFAULT_ASR_MODEL,
    FALLBACK_ASR_MODEL,
    get_openai_client,
)
from server.services.patients import list_patients_with_roots, resolve_patient_archive
from server.util.slug import slugify

bp = Blueprint("post_session_legacy", __name__, url_prefix="/api/post-session")

_BASE_DIR = Path(__file__).resolve().parents[2]
_UPLOAD_ROOT = _BASE_DIR / "uploads"
_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

_ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a"}
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 Mo


def _find_patient(slug: str) -> Optional[Dict[str, Any]]:
    items, _ = list_patients_with_roots()
    slug_lower = (slug or "").lower()
    for item in items:
        candidate = str(item.get("slug") or "").lower()
        if candidate == slug_lower:
            return item
    return None


def _notes_dir(slug: str) -> Path:
    base = Path(current_app.instance_path) / "archives" / slug / "notes" / "post"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _prepare_upload_target(patient: str | None) -> Path:
    safe_patient = slugify(patient or "_global")
    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
    target = _UPLOAD_ROOT / safe_patient / timestamp
    target.mkdir(parents=True, exist_ok=True)
    return target


def _register_upload(file_path: Path, meta: Dict[str, Any]) -> Dict[str, Any]:
    rel_path = file_path.relative_to(_UPLOAD_ROOT)
    file_id = rel_path.as_posix()
    payload = {
        "ok": True,
        "file_id": file_id,
        "path_rel": file_id,
        "relpath": file_id,
        "filename": file_path.name,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
    }
    payload.update(meta)
    return payload


@bp.post("/upload-audio")
def upload_audio():
    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify({"ok": False, "message": "Fichier audio requis."}), 400
    filename = secure_filename(file.filename)
    extension = os.path.splitext(filename)[1].lower()
    if extension not in _ALLOWED_AUDIO_EXTENSIONS:
        return (
            jsonify(
                {
                    "ok": False,
                    "message": "Format audio non supporté. Extensions autorisées: .mp3, .wav, .m4a.",
                }
            ),
            400,
        )

    size = request.content_length
    if size is None:
        try:
            file.stream.seek(0, os.SEEK_END)
            size = file.stream.tell()
            file.stream.seek(0)
        except Exception:
            size = None
    if size is not None and size > _MAX_UPLOAD_BYTES:
        max_mb = int(_MAX_UPLOAD_BYTES / (1024 * 1024))
        return (
            jsonify(
                {
                    "ok": False,
                    "message": f"Fichier trop volumineux (limite {max_mb} Mo).",
                }
            ),
            400,
        )
    patient = request.form.get("patient") or request.form.get("patient_id") or request.form.get("slug")
    target_dir = _prepare_upload_target(patient)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    target_path = target_dir / unique_name
    try:
        file.save(target_path)
    except Exception as exc:  # pragma: no cover - dépend des FS
        return jsonify({"ok": False, "message": f"Impossible d'enregistrer le fichier ({exc})."}), 500
    meta: Dict[str, Any] = {"patient": patient or None}
    duration_raw = request.form.get("duration")
    if duration_raw:
        try:
            meta["duration"] = float(duration_raw)
        except (TypeError, ValueError):
            meta["duration"] = duration_raw
    return jsonify(_register_upload(target_path, meta))


def _transcribe_with_openai(file_path: Path, language: str | None, verbose: bool) -> Optional[Dict[str, Any]]:
    client = get_openai_client()
    if client is None:
        return None
    try:
        with file_path.open("rb") as handle:
            try:
                response = client.audio.transcriptions.create(  # type: ignore[attr-defined]
                    model=DEFAULT_ASR_MODEL,
                    file=handle,
                    response_format="verbose_json" if verbose else "json",
                    language=language or None,
                )
            except Exception:
                current_app.logger.warning(
                    "Transcription OpenAI (%s) échouée, tentative de repli",
                    DEFAULT_ASR_MODEL,
                    exc_info=True,
                )
                handle.seek(0)
                response = client.audio.transcriptions.create(  # type: ignore[attr-defined]
                    model=FALLBACK_ASR_MODEL,
                    file=handle,
                    response_format="verbose_json" if verbose else "json",
                    language=language or None,
                )
    except Exception as exc:  # pragma: no cover - réseau
        current_app.logger.warning(
            "Transcription OpenAI indisponible malgré le repli: %s", exc, exc_info=True
        )
        return None
    if isinstance(response, dict):
        text = response.get("text") or ""
        segments = response.get("segments") if verbose else None
        language_code = response.get("language")
    else:  # openai v1 renvoie pydantic
        text = getattr(response, "text", "")
        segments = getattr(response, "segments", None) if verbose else None
        language_code = getattr(response, "language", None)
    return {
        "ok": True,
        "text": text or "",
        "segments": segments if verbose else None,
        "lang": language_code or language or "fr",
        "provider": "openai",
    }


def _mock_transcription(file_path: Path) -> Dict[str, Any]:
    hint = file_path.stem.replace("_", " ")
    return {
        "ok": True,
        "text": textwrap.dedent(
            f"""
            [Transcription simulée] Aucune clé OpenAI détectée.\n
            Fichier analysé : {file_path.name}.\n
            Utilisez ce texte comme point de départ pour vos annotations.
            """
        ).strip(),
        "segments": [],
        "lang": "fr",
        "provider": "mock",
    }


@bp.post("/transcribe")
def transcribe_audio():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    file_id = str(payload.get("file_id") or payload.get("id") or "").strip()
    if not file_id:
        return jsonify({"ok": False, "message": "file_id requis"}), 400
    language = payload.get("language")
    verbose = str(os.getenv("VERBOSE_WHISPER", "0")).lower() in {"1", "true", "yes"}
    file_path = (_UPLOAD_ROOT / file_id).resolve()
    if not str(file_path).startswith(str(_UPLOAD_ROOT.resolve())):
        return jsonify({"ok": False, "message": "Chemin non autorisé."}), 400
    if not file_path.exists():
        return jsonify({"ok": False, "message": "Fichier introuvable."}), 404
    result = _transcribe_with_openai(file_path, language, verbose)
    if result is None:
        result = _mock_transcription(file_path)
    return jsonify(result)


def _extract_sentences(text: str, limit: int = 4) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    cleaned = [sentence.strip() for sentence in sentences if sentence.strip()]
    return cleaned[:limit]


def _generate_plan(transcript: str, notes: str | None = None) -> Dict[str, Any]:
    highlights = _extract_sentences(transcript, limit=3)
    annotations = _extract_sentences(notes or "", limit=2)
    sections = [
        {
            "title": "Ancrages concrets",
            "bullets": highlights or ["Revenir sur les éléments matériels évoqués en séance."],
        },
        {
            "title": "Hypothèses situées",
            "bullets": annotations or ["Identifier les contraintes sociales et structurelles qui traversent la situation."],
        },
        {
            "title": "Prochaines étapes",
            "bullets": [
                "Valider avec la personne les priorités immédiates et les ressources déjà mobilisées.",
                "Programmer un temps de retour critique pour ajuster le plan d'accompagnement.",
            ],
        },
    ]
    lines = ["Plan structuré — matérialiste et situé", ""]
    for index, section in enumerate(sections, start=1):
        lines.append(f"{index}. {section['title']}")
        for bullet in section["bullets"]:
            lines.append(f"   • {bullet}")
        lines.append("")
    return {"text": "\n".join(lines).strip(), "sections": sections}


@bp.post("/plan")
def generate_plan():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    transcript = str(payload.get("transcript") or "").strip()
    notes = str(payload.get("notes") or payload.get("annotations") or "").strip()
    if not transcript:
        return jsonify({"ok": False, "message": "Transcription requise pour générer un plan."}), 400
    plan = _generate_plan(transcript, notes)
    return jsonify({"ok": True, "plan": plan["text"], "sections": plan["sections"]})


def _build_mail_sections(transcript: str, plan: str, historique: Optional[str]) -> Dict[str, str]:
    sentences = _extract_sentences(transcript, limit=3)
    materiel = "; ".join(sentences) if sentences else "vos observations concrètes sur le quotidien."
    intro = textwrap.dedent(
        f"""Ce que j’ai retenu de notre séance

        Je garde en tête les éléments matériels que vous avez partagés : {materiel}
        Nous avons replacé ces faits dans leur contexte politique et relationnel, en vérifiant que les responsabilités ne pèsent pas sur vous seule mais bien sur les organisations qui structurent votre environnement."""
    ).strip()
    bibliographie = textwrap.dedent(
        """Pistes de lecture et repères

        Je vous propose d'explorer notre bibliothèque critique interne : les dossiers « Matérialités du soin » et « Savoirs situés » éclairent les rapports de pouvoir évoqués."""
    ).strip()
    if historique:
        bibliographie += "\nNous garderons trace des ajustements réalisés précédemment afin d'éviter toute prescription comportementale."

    bibliographie += "\n" + textwrap.dedent(
        """Ces notes insistent sur les cadres collectifs et les ressources déjà présentes, sans recourir à des échelles chiffrées ni à des protocoles comportementalistes."""
    ).strip()
    prompt = textwrap.dedent(
        f"""
        Synthétiser l'échange sans pathologiser, en restant situé et matérialiste.

        Plan de séance :
        {plan}

        Résumé à produire :
        - Section 1 « Ce que j’ai retenu de notre séance »
        - Section 2 « Pistes de lecture et repères »
        - Mentionner les ressources bibliographiques critiques pertinentes.
        - Aucun recours à la TCC, aucune échelle chiffrée, aucune injonction comportementale.
        """
    ).strip()
    return {"resume": intro.strip(), "pistes": bibliographie.strip(), "prompt": prompt}


def _persist_artifacts(slug: str, base_name: str, date_label: str, transcript: str, plan: str, mail: Dict[str, str]) -> None:
    archive_root = resolve_patient_archive(slug) or (_BASE_DIR / "archives" / slug)
    notes_dir = archive_root / "notes" / "post"
    notes_dir.mkdir(parents=True, exist_ok=True)
    timestamp = date_label or datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    base = slugify(base_name or f"seance-{timestamp}")
    (notes_dir / f"{base}_transcript.txt").write_text(transcript, encoding="utf-8")
    (notes_dir / f"{base}_plan.txt").write_text(plan, encoding="utf-8")
    mail_path = notes_dir / f"{base}_mail.txt"
    mail_path.write_text(
        textwrap.dedent(
            f"""
            Ce que j’ai retenu de notre séance
            {mail['resume']}

            Pistes de lecture et repères
            {mail['pistes']}
            """
        ).strip(),
        encoding="utf-8",
    )


@bp.post("/mail")
def generate_mail():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    transcript = str(payload.get("transcript") or "").strip()
    plan = str(payload.get("plan") or "").strip()
    historique = str(payload.get("historique") or "").strip()
    if not transcript:
        return jsonify({"ok": False, "message": "Transcription requise."}), 400
    if not plan:
        return jsonify({"ok": False, "message": "Plan requis pour générer le mail."}), 400
    sections = _build_mail_sections(transcript, plan, historique)
    result = {
        "ok": True,
        "resume_seance": sections["resume"],
        "pistes_lectures_repere": sections["pistes"],
        "prompt": sections["prompt"],
    }
    slug = payload.get("patient") or payload.get("slug")
    base_name = payload.get("base_name") or payload.get("label") or "seance"
    date_label = payload.get("date") or payload.get("timestamp") or ""
    if slug:
        try:
            _persist_artifacts(slugify(str(slug)), str(base_name), str(date_label), transcript, plan, sections)
        except Exception as exc:  # pragma: no cover - dépend du FS
            current_app.logger.warning("Sauvegarde post-séance impossible: %s", exc, exc_info=True)
    return jsonify(result)


@bp.get("/context")
def get_context():
    slug = (request.args.get("patient") or "").strip()
    patient = _find_patient(slug) if slug else None
    context = {
        "patient": patient,
        "last_notes": "",
        "actions": [],
    }
    if slug:
        notes_dir = _notes_dir(slug)
        notes = sorted(notes_dir.glob("*.json"))
        if notes:
            latest = notes[-1]
            try:
                payload = json.loads(latest.read_text(encoding="utf-8"))
                context["last_notes"] = payload.get("notes") or payload.get("summary") or ""
                context["actions"] = payload.get("actions") or []
            except Exception:  # pragma: no cover - lecture défensive
                pass
    return jsonify(context)


@bp.post("/save")
def save_post_session():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    slug = (payload.get("patient") or payload.get("slug") or "").strip()
    if not slug:
        return jsonify({"success": False, "message": "Patient requis."}), 400

    notes_dir = _notes_dir(slug)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    path = notes_dir / f"{timestamp}.json"
    entry = {
        "patient": slug,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "notes": payload.get("notes") or "",
        "insights": payload.get("insights") or "",
        "actions": payload.get("actions") or [],
    }
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"success": True, "saved": entry, "path": str(path)})


__all__ = ["bp"]
