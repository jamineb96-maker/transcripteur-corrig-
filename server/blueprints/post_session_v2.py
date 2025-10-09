"""Modern post-session workflow API (transcription, plan, research, prompt)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from flask import Blueprint, current_app, jsonify, request, send_file, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from server.services.openai_client import (
    DEFAULT_ASR_MODEL,
    DEFAULT_TEXT_MODEL,
    FALLBACK_ASR_MODEL,
    get_openai_client,
    is_openai_configured,
)
from server.services.patients import find_patients_by_firstname
from server.util.slug import slugify


bp = Blueprint("post_session_v2", __name__, url_prefix="/api/post")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_UPLOAD_ROOT = _PROJECT_ROOT / "uploads"
_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 Mo pour les très longues séances
_SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
_PLAN_MODEL = os.getenv("PLAN_MODEL", DEFAULT_TEXT_MODEL)

_STOPWORDS = {
    "et",
    "le",
    "la",
    "les",
    "des",
    "une",
    "un",
    "de",
    "en",
    "que",
    "qui",
    "dans",
    "pour",
    "avec",
    "sur",
    "au",
    "aux",
    "du",
    "se",
    "ses",
    "son",
    "sa",
    "ce",
    "cela",
    "cette",
    "elles",
    "ils",
    "elles",
    "leurs",
    "leur",
    "mais",
    "plus",
    "tout",
    "toute",
    "tous",
    "toutes",
    "comme",
    "faire",
    "être",
    "avoir",
    "nous",
    "vous",
    "elles",
    "ils",
    "je",
    "tu",
    "il",
    "elle",
    "on",
    "mes",
    "tes",
    "vos",
    "notre",
    "votre",
    "leur",
    "par",
    "pas",
    "ou",
}

_STYLE_HINTS = {
    "sobre": "un ton sobre, professionnel et direct, sans emphase inutile",
    "empathique": "un ton chaleureux, soutenant et contenant",
    "bref": "un ton concis, efficace et orienté synthèse",
}

_FILENAME_FIRSTNAME_RE = re.compile(r"^([A-Za-zÀ-ÖØ-öø-ÿ'’\-]+)\s+\d+\b")


def _json_response(payload: Dict[str, Any], status: int = 200):
    response = jsonify(payload)
    response.status_code = status
    return response


def _probe_request_payload(req) -> Dict[str, Any]:
    try:
        files_keys = list(req.files.keys())
    except Exception:  # pragma: no cover - best effort logging
        files_keys = []
    try:
        form_keys = list(req.form.keys())
    except Exception:  # pragma: no cover - best effort logging
        form_keys = []
    return {
        "ua": req.headers.get("User-Agent"),
        "ct": req.headers.get("Content-Type"),
        "cl": req.headers.get("Content-Length"),
        "files_keys": files_keys,
        "form_keys": form_keys,
    }


def _pick_upload(req) -> Optional[FileStorage]:
    for key in ("audio", "file", "upload", "audio_file", "audio[]", "files[]"):
        if key in req.files:
            return req.files[key]
    try:
        return next(iter(req.files.values())) if req.files else None
    except Exception:  # pragma: no cover - best effort logging
        return None


def _jsonify(obj):
    """Convertit récursivement les objets OpenAI/Pydantic en structures JSON-safe."""
    import dataclasses
    from collections.abc import Mapping, Sequence

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if hasattr(obj, "model_dump_json"):
        try:
            import json as _json

            return _json.loads(obj.model_dump_json())
        except Exception:
            pass

    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)

    if isinstance(obj, Mapping):
        return {k: _jsonify(v) for k, v in obj.items()}

    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [_jsonify(v) for v in obj]

    return obj
def _llm_health() -> Dict[str, bool]:
    env_ready = is_openai_configured()
    if not env_ready:
        return {"env": False, "llm": False}
    return {"env": True, "llm": get_openai_client() is not None}


def _llm_available() -> bool:
    return _llm_health()["llm"]


def _normalise_patient_folder(patient: str) -> Path:
    slug = slugify(patient or "patient")
    base = Path(current_app.instance_path) / "archives" / slug
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ensure_session_prefix(date_str: str | None, base_name: str | None) -> Tuple[str, str]:
    try:
        if date_str:
            parsed = datetime.strptime(date_str, "%Y-%m-%d")
        else:
            parsed = datetime.utcnow()
    except ValueError:
        parsed = datetime.utcnow()
    date_fmt = parsed.strftime("%Y-%m-%d")
    base = slugify(base_name or "seance").replace("-", "_")
    if not base:
        base = "seance"
    return date_fmt, base


def _session_file_paths(patient: str, date_str: str, base_name: str) -> Dict[str, Path]:
    folder = _normalise_patient_folder(patient)
    prefix = f"{date_str}_{base_name}"
    return {
        "transcript": folder / f"{prefix}_transcript.txt",
        "segments": folder / f"{prefix}_segments.json",
        "words": folder / f"{prefix}_words.json",
        "plan": folder / f"{prefix}_plan.txt",
        "mail": folder / f"{prefix}_mail.md",
    }


def _persist_session_assets(
    patient: str,
    date_str: str,
    base_name: str,
    *,
    transcript: str | None = None,
    segments: Iterable[Dict[str, Any]] | None = None,
    words: Iterable[Dict[str, Any]] | None = None,
    plan_text: str | None = None,
    mail_md: str | None = None,
) -> Dict[str, str]:
    paths = _session_file_paths(patient, date_str, base_name)
    written: Dict[str, str] = {}
    if transcript is not None:
        paths["transcript"].write_text(transcript, encoding="utf-8")
        written["transcript"] = str(paths["transcript"])
    if segments is not None:
        data = _jsonify(list(segments))
        paths["segments"].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        written["segments"] = str(paths["segments"])
    if words is not None:
        data = _jsonify(list(words))
        paths["words"].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        written["words"] = str(paths["words"])
    if plan_text is not None:
        paths["plan"].write_text(plan_text, encoding="utf-8")
        written["plan"] = str(paths["plan"])
    if mail_md is not None:
        paths["mail"].write_text(mail_md, encoding="utf-8")
        written["mail"] = str(paths["mail"])
    return written


def _load_session_assets(
    patient: str,
    *,
    date_str: str | None = None,
    base_name: str | None = None,
) -> Tuple[str, str, Dict[str, Any]]:
    folder = _normalise_patient_folder(patient)
    target_date, target_base = _ensure_session_prefix(date_str, base_name)

    def _find_latest() -> Tuple[str, str]:
        candidates: List[Tuple[str, str]] = []
        for path in folder.glob("*_transcript.txt"):
            match = re.match(r"^(\d{4}-\d{2}-\d{2})_([^/]+?)_transcript\\.txt$", path.name)
            if not match:
                continue
            candidates.append((match.group(1), match.group(2)))
        candidates.sort(reverse=True)
        if candidates:
            return candidates[0]
        raise FileNotFoundError("no_session")

    if not (folder / f"{target_date}_{target_base}_transcript.txt").exists():
        target_date, target_base = _find_latest()

    paths = _session_file_paths(patient, target_date, target_base)
    payload: Dict[str, Any] = {
        "transcript": "",
        "plan_text": "",
        "segments": [],
        "words": [],
        "mail_md": "",
    }
    if paths["transcript"].exists():
        payload["transcript"] = paths["transcript"].read_text(encoding="utf-8")
    if paths["plan"].exists():
        payload["plan_text"] = paths["plan"].read_text(encoding="utf-8")
    if paths["mail"].exists():
        payload["mail_md"] = paths["mail"].read_text(encoding="utf-8")
    if paths["segments"].exists():
        try:
            payload["segments"] = json.loads(paths["segments"].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["segments"] = []
    if paths["words"].exists():
        try:
            payload["words"] = json.loads(paths["words"].read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["words"] = []

    history: List[Dict[str, str]] = []
    for path in sorted(folder.glob("*_transcript.txt"), reverse=True):
        match = re.match(r"^(\d{4}-\d{2}-\d{2})_([^/]+?)_transcript\\.txt$", path.name)
        if not match:
            continue
        history.append({
            "date": match.group(1),
            "base_name": match.group(2),
        })
    payload["history"] = history
    payload["historique"] = "\n".join(f"{item['date']} — {item['base_name']}" for item in history)
    return target_date, target_base, payload


def _fake_segments(transcript: str) -> List[Dict[str, Any]]:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[\.!?])\s+|\n+", transcript)
        if sentence.strip()
    ]
    if not sentences:
        return []
    segments: List[Dict[str, Any]] = []
    cursor = 0.0
    for index, sentence in enumerate(sentences):
        word_count = max(1, len(re.findall(r"\w+", sentence)))
        duration = min(45.0, 4.0 + word_count * 0.5)
        segments.append(
            {
                "id": index,
                "start": round(cursor, 2),
                "end": round(cursor + duration, 2),
                "text": sentence.replace("\n", " "),
            }
        )
        cursor += duration
    return segments


def _asr_response_format_for(model: str) -> str:
    m = (model or "").lower()
    if not m:
        return "verbose_json"
    if "transcribe" in m or m.startswith("gpt-4o-mini"):
        return "verbose_json"
    if "whisper" in m:
        return "verbose_json"
    return "verbose_json"


def _transcribe_audio(file_path: Path, *, verbose: bool = True) -> Dict[str, Any]:
    client = get_openai_client()
    if client is not None:  # pragma: no cover - dépend du réseau
        try:
            with file_path.open("rb") as handle:
                response = None
                used_model = DEFAULT_ASR_MODEL
                response_format = _asr_response_format_for(DEFAULT_ASR_MODEL)

                def _invoke(selected_model: str, *, fmt: str):
                    kwargs: Dict[str, Any] = {
                        "model": selected_model,
                        "file": handle,
                        "response_format": fmt,
                        "temperature": 0,
                        "language": "fr",
                    }
                    if fmt == "verbose_json":
                        kwargs["timestamp_granularities"] = ["segment", "word"]
                    return client.audio.transcriptions.create(  # type: ignore[attr-defined]
                        **kwargs
                    )

                try:
                    response = _invoke(used_model, fmt=response_format)
                except Exception:
                    # Certains modèles (ou SDK) refusent verbose_json ; repli sur json.
                    current_app.logger.warning(
                        "Transcription OpenAI (%s) format=%s échouée, repli json",
                        used_model,
                        response_format,
                        exc_info=True,
                    )
                    handle.seek(0)
                    try:
                        response = _invoke(used_model, fmt="json")
                        response_format = "json"
                    except Exception:
                        fallback_model = FALLBACK_ASR_MODEL
                        if fallback_model and fallback_model != used_model:
                            handle.seek(0)
                            response_format = _asr_response_format_for(fallback_model)
                            try:
                                response = _invoke(fallback_model, fmt=response_format)
                            except Exception:
                                current_app.logger.warning(
                                    "Transcription OpenAI (%s) format=%s échouée, repli json",
                                    fallback_model,
                                    response_format,
                                    exc_info=True,
                                )
                                handle.seek(0)
                                response = _invoke(fallback_model, fmt="json")
                                response_format = "json"
                            used_model = fallback_model
                        else:
                            raise
        except Exception:
            current_app.logger.warning(
                "Transcription OpenAI indisponible malgré les replis", exc_info=True
            )
        else:
            if response is not None:
                if isinstance(response, dict):
                    text = str(response.get("text") or "").strip()
                    language = response.get("language")
                    duration = response.get("duration")
                    segments = response.get("segments") or []
                    words = response.get("words") or []
                else:  # openai>=1.x renvoie un objet pydantic
                    text = str(getattr(response, "text", "") or "").strip()
                    language = getattr(response, "language", None)
                    duration = getattr(response, "duration", None)
                    segments = getattr(response, "segments", None) or []
                    words = getattr(response, "words", None) or []
                if text:
                    raw_segments = segments if verbose else []
                    raw_words = words if verbose else []
                    return {
                        "text": text,
                        "segments": _jsonify(raw_segments),
                        "words": _jsonify(raw_words),
                        "language": language,
                        "duration": duration,
                        "model": used_model,
                    }

    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = ""
    if not text:
        text = (
            "[Transcription indisponible] Aucun modèle Whisper n'est configuré. "
            "Ajoutez OPENAI_API_KEY ou collez la transcription manuellement."
        )
    segments = _fake_segments(text) if verbose else []
    return {
        "text": text,
        "segments": _jsonify(segments),
        "words": [],
        "language": None,
        "duration": None,
        "model": None,
    }


def _call_chat_model(messages: List[Dict[str, str]], *, model: str) -> Optional[str]:
    client = get_openai_client()
    if client is None:
        return None
    try:  # pragma: no cover - dépendance externe
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=model,
            messages=messages,
            temperature=0.4,
        )
    except Exception:
        current_app.logger.warning("Appel LLM échoué", exc_info=True)
        return None
    try:
        return str(response.choices[0].message.content or "").strip()
    except Exception:
        return None


def _extract_keywords(text: str, *, limit: int = 12) -> List[str]:
    tokens = [token.lower() for token in re.findall(r"[\wÀ-ÖØ-öø-ÿ]{3,}", text)]
    counts: Counter[str] = Counter()
    for token in tokens:
        if token in _STOPWORDS:
            continue
        counts[token] += 1
    return [word for word, _ in counts.most_common(limit)]


def _fallback_plan(transcript: str) -> str:
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[\.!?])\s+", transcript)
        if sentence.strip()
    ]
    if not sentences:
        sentences = [transcript.strip()]
    overview = sentences[0]
    keywords = _extract_keywords(transcript, limit=6)
    axes = [
        f"Axe {index + 1}. Approfondir « {word} » en reliant les propos aux contraintes matérielles et relationnelles."
        for index, word in enumerate(keywords[:4])
    ]
    if not axes:
        axes = [
            "Axe 1. Clarifier les attentes de la personne et sécuriser le cadre.",
            "Axe 2. Identifier les ressources concrètes mobilisables sans épuisement.",
        ]
    actions = [
        "Planifier un point de suivi court pour valider ce qui a été entendu et les besoins urgents.",
        "Co-construire un tableau partagé des appuis et signaux de surcharge.",
        "Lister les personnes et structures à contacter pour renforcer le filet de sécurité.",
        "Programmer un temps de feedback sur l'expérience de la séance précédente.",
        "Mettre à disposition un support écrit reprenant les repères stabilisants.",
    ]
    body_sections = [
        (
            "R1 — Réalité immédiate",
            " ".join(sentences[: min(len(sentences), 6)])
            or (
                "La personne décrit plusieurs éléments saillants qu'il convient de replacer dans le contexte de la séance. "
                "Cette section rappelle les faits, les ressentis prioritaires et les signaux d'alerte repérés ensemble."
            ),
        ),
        (
            "R2 — Raisons et dynamiques",
            " ".join(sentences[6:12])
            or (
                "Analyse rapide des dynamiques relationnelles, institutionnelles et corporelles évoquées pendant la séance. "
                "L'objectif est de dégager les liens entre les difficultés décrites et les environnements matériels."
            ),
        ),
        (
            "R3 — Ressources et ouvertures",
            " ".join(sentences[12:18])
            or (
                "Repérage des ressources internes, collectives et environnementales disponibles ou à consolider. "
                "On articule ici les relais possibles, les marges de manœuvre et les actions soutenables."
            ),
        ),
    ]
    lines = [overview, ""]
    for title, content in body_sections:
        lines.append(title)
        lines.append(content)
        lines.append("")
    lines.append("Axes prioritaires")
    lines.extend(axes)
    lines.append("")
    lines.append("Actions concrètes")
    lines.extend([f"- {item}" for item in actions])
    return "\n".join(lines).strip()


def _generate_plan(transcript: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "Tu es une psychologue clinicienne qui rédige un plan post-séance structuré. "
                "Le plan doit comporter les sections R1, R2, R3, une liste Axes prioritaires et une liste Actions concrètes."
            ),
        },
        {
            "role": "user",
            "content": (
                "Transcript de la séance:\n\n" + transcript + "\n\n"
                "Produit un plan détaillé (500 à 900 mots) sans excuses ni redites."
            ),
        },
    ]
    completion = _call_chat_model(messages, model=_PLAN_MODEL)
    if completion:
        return completion
    return _fallback_plan(transcript)


def _generate_queries(plan_text: str, patient: str | None = None) -> List[str]:
    keywords = _extract_keywords(plan_text, limit=12)
    base_queries: List[str] = []
    patient_hint = f" {patient}" if patient else ""
    for keyword in keywords[:5]:
        base_queries.append(f"{keyword}{patient_hint} études de cas psychologie clinique")
    if len(base_queries) < 5 and keywords:
        base_queries.append(f"{keywords[0]}{patient_hint} accompagnement interdisciplinaire")
    if len(base_queries) < 6:
        base_queries.append("alliance thérapeutique post séance matériaux situés")
    if len(base_queries) < 7:
        base_queries.append("fatigue décisionnelle soins continus bibliographie")
    if len(base_queries) < 8:
        base_queries.append("traumatismes cumulés pratiques centrées patient communauté")
    unique = []
    seen = set()
    for query in base_queries:
        cleaned = " ".join(query.split())
        if cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        unique.append(cleaned)
    return unique[:10]


def _compose_prompt(patient: str, plan_text: str, queries: list[str], style: str) -> tuple[str, str]:
    """
    Compose un prompt structuré pour le flux post‑séance (version z2). Ce
    format garantit la conformité aux règles stylistiques, l'ajout d'un
    marqueur de version et une structure de sortie stable. Il renvoie un
    tuple contenant le prompt et l'objet de mail suggéré.
    """
    # Préparation des champs patient et contexte
    safe_patient = (patient or "").strip()
    display_name = safe_patient if safe_patient else "—"
    # Nettoyer le plan et les requêtes (suppression de backticks)
    plan_plain = (plan_text or "").replace("```,", "").replace("```", "").strip()
    q_plain = [q.strip() for q in (queries or []) if isinstance(q, str) and q.strip()]
    q_sentence = " ; ".join(q_plain)

    # Marqueur de version pour audit
    version = "PROMPT_TEMPLATE_VERSION=2025-10-09-z2"
    salutation = f'Bonjour {safe_patient},' if safe_patient else "Bonjour,"

    template = (
        f"=== VERSION === {version}\n"
        "=== SYSTEM (obligatoire) ===\n"
        "Tu es chargé d'écrire un compte-rendu de séance en français qui reformule avec précision le contenu fourni.\n"
        "Tu n'inventes rien. Tu ne prescris rien. Tu ne poses pas de diagnostic. Tu relies systématiquement les phénomènes au contexte matériel, social, institutionnel quand c'est pertinent.\n\n"

        "=== STYLE_GUARD (obligatoire) ===\n"
        "Règles strictes de sortie :\n"
        "1) Guillemets obligatoires : utiliser exclusivement \" ... \". Interdiction de « » et de “ ”.\n"
        "2) Interdiction du tiret long et de la séquence --. Utiliser des parenthèses ( ... ) pour les incises, ou des virgules.\n"
        "3) Pas de listes à puces ni de markdown. Paragraphes en prose, une seule ligne vide entre eux.\n"
        "4) Pas de double espace. Pas d'émojis. Pas de ton infantilisant.\n"
        "5) Voix située autorisée : tu peux employer \"je\" pour expliciter une hypothèse, une incertitude ou une limite de sécurité.\n"
        "6) Zéro pathologisation. Lecture matérialiste et anti-individualisante.\n\n"

        "=== TONE_PROFILE (obligatoire) ===\n"
        "Sobre, humain, analytique sans surplomb. Préférer : \"vous décrivez\", \"vous soulignez\", \"cela éclaire\", \"cela interroge\".\n"
        "Éviter : \"il faut\", \"vous devez\", \"cela prouve\", \"clairement\".\n\n"

        "=== OUTPUT_RULES (obligatoire) ===\n"
        "But : produire un texte immédiatement collable dans un mail, sans markdown.\n"
        "Structure exacte :\n"
        f"1) Salutation : \"{salutation}\" sur une ligne. Puis une phrase brève de cadrage : \"Comme d'habitude, ce texte sert de mémoire ; corrigez si besoin.\"\n"
        "2) Section 1, titre exact sur sa propre ligne : Ce que vous avez exprimé et ce que j'en ai compris\n"
        "   Contenu : 2 à 4 paragraphes courts (3–5 lignes chacun). Inclure au moins une phrase reliant explicitement les phénomènes à des conditions matérielles/institutionnelles.\n"
        "3) Section 2, titre exact sur sa propre ligne : Pistes de lecture et repères\n"
        "   Contenu : 3 à 7 paragraphes courts. Chaque paragraphe commence par un micro‑sous‑titre conceptuel suivi d’un deux‑points (ex. \"Balises mnésiques : …\", \"Économie de seuils : …\", \"Effet blouse blanche : …\"), sans gras ni puces. Autorisé exceptionnellement : une séquence d’options en 1 à 3 lignes (chaque ligne = une phrase autonome), sans puces.\n"
        "4) Clôture : \"Bien à vous,\" puis \"Benjamin.\"\n"
        "Bornes : 550 à 1000 mots au total. Pas de numérotation ni d'encart.\n\n"

        "=== CONTEXTE DISPONIBLE ===\n"
        f"[Patient·e] : {display_name}\n"
        "[Plan court consolidé] :\n"
        f"{plan_plain}\n\n"
        "[Pistes/documentation (phrases, sans puces)] :\n"
        f"{q_sentence}\n\n"

        "=== TÂCHE (obligatoire) ===\n"
        "Rédige MAINTENANT le mail final en respectant STRICTEMENT SYSTEM, STYLE_GUARD, TONE_PROFILE et OUTPUT_RULES.\n"
        "Contraintes fermes : utiliser uniquement des guillemets droits \" \" ; aucune séquence — ni -- ; pas de puces ni de markdown ; aucune invention de contenu ; deux sections exactement avec les titres imposés ; micro‑sous‑titres exigés en tête des paragraphes de la section 2 ; inclure au moins une phrase d’ancrage matériel par section.\n\n"

        "=== QA-CHECKS (auto-contrôle) ===\n"
        "Vérifie que le texte final :\n"
        "- Commence par \"Bonjour\" et contient les deux titres exacts.\n"
        "- N'emploie ni — ni -- et utilise uniquement des guillemets droits \" \".\n"
        "- Ne contient aucune puce (*, -, •) ni balise markdown.\n"
        "- Dans la section 2, au moins deux paragraphes commencent par un mot/une locution suivie de deux‑points.\n"
        "- Chaque section contient au moins une phrase reliant phénomènes ↔ déterminants matériels/institutionnels."
    ).strip()

    prompt = template
    # Choisir l'objet du mail en fonction du patient renseigné
    subject = f"Compte-rendu — {safe_patient}" if safe_patient else "Compte-rendu — séance"
    return prompt, subject


def _save_upload(file_storage, patient: str) -> Tuple[Path, str]:
    filename = secure_filename(getattr(file_storage, "filename", "session_audio")) or "session_audio"
    extension = os.path.splitext(filename)[1].lower()
    if extension and extension not in _SUPPORTED_AUDIO_EXTENSIONS:
        raise ValueError("unsupported_audio")
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size and size > _MAX_UPLOAD_BYTES:
        raise ValueError("file_too_large")
    patient_slug = slugify(patient or "global")
    target_dir = _UPLOAD_ROOT / patient_slug
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"{timestamp}_{filename}"
    file_storage.save(target)
    base_name = os.path.splitext(filename)[0]
    return target, base_name


@bp.post("/transcribe")
def api_transcribe():
    probe_info = _probe_request_payload(request)
    file_storage = _pick_upload(request)

    fallback_meta: Dict[str, Any] = {"fallback": False}
    if file_storage is None or not getattr(file_storage, "filename", ""):
        raw_body = request.get_data(cache=False) or b""
        if raw_body:
            fallback_field = getattr(file_storage, "name", None) or "audio"
            fallback_filename = (
                request.headers.get("X-File-Name")
                or getattr(file_storage, "filename", "")
                or "upload.bin"
            )
            fallback_mimetype = request.headers.get("Content-Type", "application/octet-stream")
            safe_filename = secure_filename(fallback_filename) or "upload.bin"
            stream = BytesIO(raw_body)
            file_storage = FileStorage(
                stream=stream,
                filename=safe_filename,
                name=fallback_field,
                content_type=fallback_mimetype,
            )
            stream.seek(0)
            fallback_meta.update(
                {
                    "fallback": "binary",
                    "fallback_len": len(raw_body),
                    "fallback_filename": safe_filename,
                    "fallback_mimetype": fallback_mimetype,
                }
            )
        else:
            log_payload = dict(probe_info)
            log_payload.update({"fallback": False})
            try:
                current_app.logger.info(
                    "[/post/transcribe/request] %s", json.dumps(log_payload, ensure_ascii=False)
                )
            except Exception:  # pragma: no cover - logging best effort
                current_app.logger.info("[/post/transcribe/request] %s", log_payload)
            debug_info = dict(probe_info)
            return _json_response(
                {
                    "ok": False,
                    "error": {
                        "type": "missing_file",
                        "message": "Fichier audio requis.",
                        "details": {"debug": debug_info},
                    },
                },
                400,
            )

    if file_storage is not None and not getattr(file_storage, "filename", ""):
        fallback_filename = request.headers.get("X-File-Name") or getattr(file_storage, "name", "") or "upload.bin"
        safe_filename = secure_filename(fallback_filename) or "upload.bin"
        try:
            file_storage.filename = safe_filename  # type: ignore[attr-defined]
        except Exception:
            file_storage = FileStorage(
                stream=file_storage.stream,
                filename=safe_filename,
                name=getattr(file_storage, "name", None),
                content_type=getattr(file_storage, "mimetype", None),
            )

    log_payload = dict(probe_info)
    log_payload.update(fallback_meta)
    if file_storage is not None:
        log_payload.update(
            {
                "field": getattr(file_storage, "name", None),
                "filename": getattr(file_storage, "filename", ""),
                "mimetype": getattr(file_storage, "mimetype", None),
            }
        )
    try:
        current_app.logger.info(
            "[/post/transcribe/request] %s", json.dumps(log_payload, ensure_ascii=False)
        )
    except Exception:  # pragma: no cover - logging best effort
        current_app.logger.info("[/post/transcribe/request] %s", log_payload)

    patient = (
        request.form.get("patient")
        or request.form.get("patient_id")
        or request.args.get("patient")
        or request.args.get("patient_id")
        or request.headers.get("X-Patient")
        or ""
    ).strip()
    base_name_override = (
        request.form.get("base_name")
        or request.form.get("base")
        or request.args.get("base_name")
        or request.args.get("base")
        or request.headers.get("X-Base-Name")
        or ""
    ).strip()
    original_filename = getattr(file_storage, "filename", "") if file_storage is not None else ""
    auto_candidate = ""
    auto_matches: List[Dict[str, str]] = []
    if isinstance(original_filename, str) and original_filename.strip():
        match = _FILENAME_FIRSTNAME_RE.match(original_filename.strip())
        if match:
            auto_candidate = match.group(1).strip()
            try:
                auto_matches = find_patients_by_firstname(auto_candidate)
            except Exception:  # pragma: no cover - robustesse
                auto_matches = []
    if file_storage is None or not getattr(file_storage, "filename", ""):
        return _json_response(
            {
                "ok": False,
                "error": {
                    "type": "missing_file",
                    "message": "Fichier audio requis.",
                    "details": None,
                },
            },
            400,
        )
    if not patient:
        return _json_response(
            {
                "ok": False,
                "error": {
                    "type": "missing_patient",
                    "message": "Sélectionnez un patient.",
                    "details": None,
                },
            },
            400,
        )
    try:
        upload_path, derived_base = _save_upload(file_storage, patient)
    except ValueError as exc:
        code = str(exc)
        if code == "unsupported_audio":
            return _json_response(
                {
                    "ok": False,
                    "error": {
                        "type": "unsupported_audio",
                        "message": "Format audio non supporté. Utilisez MP3, WAV, M4A, AAC ou OGG.",
                        "details": None,
                    },
                },
                415,
            )
        if code == "file_too_large":
            max_bytes = current_app.config.get("MAX_CONTENT_LENGTH", _MAX_UPLOAD_BYTES)
            max_mb = int(max_bytes / (1024 * 1024)) if isinstance(max_bytes, int) and max_bytes > 0 else int(_MAX_UPLOAD_BYTES / (1024 * 1024))
            return _json_response(
                {
                    "ok": False,
                    "error": {
                        "type": "file_too_large",
                        "message": f"Le fichier dépasse la taille autorisée ({max_mb} Mo).",
                        "max_mb": max_mb,
                        "details": {"max_mb": max_mb},
                    },
                },
                413,
            )
        return _json_response(
            {
                "ok": False,
                "error": {
                    "type": "upload_failed",
                    "message": "Impossible d'enregistrer le fichier.",
                    "details": None,
                },
            },
            500,
        )

    date_str, base_name = _ensure_session_prefix(None, base_name_override or derived_base)

    try:
        transcription = _transcribe_audio(upload_path, verbose=True)
    except Exception:  # pragma: no cover - dépend du FS
        current_app.logger.exception("Transcription impossible")
        return _json_response(
            {
                "ok": False,
                "error": {
                    "type": "transcription_failed",
                    "message": "La transcription a échoué.",
                    "details": None,
                },
            },
            500,
        )

    raw_text = str(transcription.get("text") or "")
    segments_data = _jsonify(transcription.get("segments") or [])
    if segments_data is None:
        segments_data = []
    if not isinstance(segments_data, list):
        segments_data = list(segments_data) if isinstance(segments_data, (tuple, set)) else [segments_data]

    normalized_segments: List[Dict[str, Any]] = []
    segment_text_parts: List[str] = []
    for item in segments_data:
        if isinstance(item, dict):
            segment = dict(item)
            text_value = segment.get("text")
            if isinstance(text_value, str):
                text_str = text_value
            elif text_value is None:
                text_str = ""
            else:
                text_str = str(text_value)
            segment["text"] = text_str
            normalized_segments.append(segment)
            cleaned = text_str.strip()
            if cleaned:
                segment_text_parts.append(cleaned)
        elif item is not None:
            text_str = str(item)
            normalized_segments.append({"text": text_str})
            cleaned = text_str.strip()
            if cleaned:
                segment_text_parts.append(cleaned)

    stitched_segments_text = "\n".join(segment_text_parts)
    normalized_text = raw_text.replace("\r\n", "\n")
    full_text = normalized_text
    if stitched_segments_text and len(stitched_segments_text) > len(full_text):
        full_text = stitched_segments_text
    final_text = (full_text or "").replace("\x00", "\uFFFD")
    transcript = final_text

    segments = normalized_segments
    words = _jsonify(transcription.get("words") or [])
    if words is None:
        words = []
    if not isinstance(words, list):
        words = list(words) if isinstance(words, (tuple, set)) else [words]
    language = transcription.get("language")
    duration = transcription.get("duration")

    _persist_session_assets(
        patient,
        date_str,
        base_name,
        transcript=transcript,
        segments=segments,
        words=words,
    )

    transcript_url = url_for(
        "post_session_v2.api_assets",
        patient=patient,
        date=date_str,
        base=base_name,
        kind="transcript",
        _external=False,
    )

    try:
        with upload_path.open("rb") as audio_handle:
            audio_bytes = audio_handle.read()
    except OSError:
        audio_bytes = b""

    audio_length = len(audio_bytes or b"")
    full_length = len(full_text or "")
    stitched_length = len(stitched_segments_text or "")
    sent_length = len(transcript or "")
    segments_length = len(segments or [])
    current_app.logger.info(
        "[/post/transcribe] audio_bytes=%s full_len=%s stitched_len=%s sent_len=%s segments=%s",
        audio_length,
        full_length,
        stitched_length,
        sent_length,
        segments_length,
    )

    del audio_bytes

    selected_id = auto_matches[0].get("id") if len(auto_matches) == 1 else None
    auto_event = None
    if auto_candidate:
        auto_event = {
            "event": "auto_patient",
            "filename": original_filename,
            "candidate": auto_candidate.casefold(),
            "matches": len(auto_matches),
            "selected_id": selected_id,
        }
        try:
            current_app.logger.info(json.dumps(auto_event, ensure_ascii=False))
        except Exception:  # pragma: no cover - logging best effort
            pass

    auto_payload = {
        "candidate": auto_candidate or None,
        "matches": auto_matches,
        "selected_id": selected_id,
        "event": auto_event,
    }

    text_len = len(transcript)
    text_sha256 = hashlib.sha256((transcript or "").encode("utf-8")).hexdigest()

    payload = {
        "ok": True,
        "patient": patient,
        "base_name": base_name,
        "date": date_str,
        "transcript": transcript,
        "text": transcript,
        "language": language,
        "duration": duration,
        "segments": segments,
        "words": words,
        "text_len": text_len,
        "text_sha256": text_sha256,
        "segments_count": len(segments),
        "words_count": len(words),
        "llm_available": _llm_available(),
        "openai_health": _llm_health(),
        "auto_patient": auto_payload,
        "transcript_url": transcript_url,
    }
    current_app.logger.info(
        "[/post/transcribe] sent_len=%s sha256=%s segments=%s",
        text_len,
        text_sha256,
        segments_length,
    )

    safe_patient = slugify(patient or "")
    import hashlib, os
    from pathlib import Path

    text = payload.get("text") if isinstance(payload, dict) else None
    if isinstance(text, str) and text:
        tail = text[-2000:] if len(text) > 2000 else text
        sha = hashlib.sha256(tail.encode("utf-8", "ignore")).hexdigest()
        payload["text_len"] = len(text)
        payload["text_sha256"] = sha
        # Debug file
        dbg_dir = Path("instance") / "transcripts_debug"
        dbg_dir.mkdir(parents=True, exist_ok=True)
        fname = f"transcribe_{safe_patient or 'anon'}.log"
        with open(dbg_dir / fname, "a", encoding="utf-8") as fh:
            fh.write(f"len={len(text)} sha={sha}\nlast2k={tail}\n---\n")

    return _json_response(payload)


@bp.post("/plan")
def api_plan():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    patient = str(payload.get("patient") or "").strip()
    base_name = str(payload.get("base_name") or "").strip()
    date_str = str(payload.get("date") or "").strip()
    transcript = str(payload.get("transcript") or "").strip()
    if not transcript:
        if not patient:
            return _json_response(
                {
                    "ok": False,
                    "error": "missing_transcript",
                    "message": "Aucune transcription fournie et aucune archive détectée.",
                },
                400,
            )
        try:
            date_str, base_name, assets = _load_session_assets(patient, date_str=date_str or None, base_name=base_name or None)
        except FileNotFoundError:
            return _json_response(
                {
                    "ok": False,
                    "error": "missing_transcript",
                    "message": "Impossible de récupérer une transcription sauvegardée.",
                },
                404,
            )
        transcript = str(assets.get("transcript") or "").strip()
    if not transcript:
        return _json_response(
            {"ok": False, "error": "empty_transcript", "message": "La transcription est vide."},
            400,
        )

    date_str, base_name = _ensure_session_prefix(date_str or None, base_name or None)
    plan_text = _generate_plan(transcript)
    _persist_session_assets(patient or "", date_str, base_name, plan_text=plan_text)
    return _json_response({
        "ok": True,
        "plan_text": plan_text,
        "date": date_str,
        "base_name": base_name,
        "llm_available": _llm_available(),
        "openai_health": _llm_health(),
    })


@bp.post("/research")
def api_research():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    plan_text = str(payload.get("plan_text") or payload.get("plan") or "").strip()
    transcript = str(payload.get("transcript") or "").strip()
    patient = str(payload.get("patient") or "").strip()
    source_text = plan_text or transcript
    if not source_text:
        return _json_response(
            {
                "ok": False,
                "error": "missing_context",
                "message": "Fournissez un plan ou un extrait de transcript pour générer les recherches.",
            },
            400,
        )

    queries = _generate_queries(source_text, patient if patient else None)
    return _json_response(
        {"ok": True, "queries": queries, "llm_available": _llm_available(), "openai_health": _llm_health()}
    )


@bp.post("/prompt")
def api_prompt():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    patient = str(payload.get("patient") or "").strip()
    plan_text = str(payload.get("plan_text") or payload.get("plan") or "").strip()
    queries = payload.get("queries")
    style = str(payload.get("style") or "sobre").strip().lower()
    if not plan_text:
        return _json_response({"ok": False, "error": "missing_plan", "message": "Plan requis."}, 400)
    if isinstance(queries, list):
        filtered = [str(item) for item in queries if isinstance(item, str) and item.strip()]
    else:
        filtered = []
    prompt, subject = _compose_prompt(patient, plan_text, filtered, style)
    return _json_response(
        {
            "ok": True,
            "prompt": prompt,
            "suggested_subject": subject,
        }
    )


@bp.post("/save-mail")
def api_save_mail():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        payload = {}
    patient = str(payload.get("patient") or "").strip()
    base_name = str(payload.get("base_name") or "").strip()
    date_str = str(payload.get("date") or "").strip()
    mail_md = str(payload.get("mail_md") or "").strip()
    if not patient:
        return _json_response({"ok": False, "error": "missing_patient", "message": "Patient requis."}, 400)
    if not mail_md:
        return _json_response({"ok": False, "error": "empty_mail", "message": "Le contenu du mail est vide."}, 400)
    date_str, base_name = _ensure_session_prefix(date_str or None, base_name or None)
    written = _persist_session_assets(patient, date_str, base_name, mail_md=mail_md)
    path = written.get("mail")
    if path:
        try:
            rel_path = str(Path(path).relative_to(Path(current_app.instance_path)))
        except ValueError:
            rel_path = path
    else:
        rel_path = ""
    return _json_response({
        "ok": True,
        "path": rel_path,
        "date": date_str,
        "base_name": base_name,
    })


@bp.get("/assets")
def api_assets():
    patient = str(request.args.get("patient") or "").strip()
    base_param = request.args.get("base") or request.args.get("base_name")
    base_name = base_param.strip() if isinstance(base_param, str) else None
    date_str = request.args.get("date")
    kind = (request.args.get("kind") or "").strip().lower()
    if not patient:
        return _json_response({"ok": False, "error": "missing_patient", "message": "Patient requis."}, 400)
    try:
        resolved_date, resolved_base, assets = _load_session_assets(
            patient,
            date_str=date_str or None,
            base_name=base_name or None,
        )
    except FileNotFoundError:
        return _json_response({"ok": False, "error": "not_found", "message": "Aucun historique trouvé."}, 404)
    if kind == "transcript":
        paths = _session_file_paths(patient, resolved_date, resolved_base)
        transcript_path = paths["transcript"]
        if not transcript_path.exists():
            return current_app.response_class(
                "", status=404, mimetype="text/plain; charset=utf-8"
            )
        return send_file(
            transcript_path,
            mimetype="text/plain; charset=utf-8",
            as_attachment=False,
        )

    payload = {
        "ok": True,
        "patient": patient,
        "date": resolved_date,
        "base_name": resolved_base,
        **assets,
        "llm_available": _llm_available(),
        "openai_health": _llm_health(),
    }
    return _json_response(payload)


__all__ = ["bp"]
