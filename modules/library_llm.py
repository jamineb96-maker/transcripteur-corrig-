"""Intégration OpenAI pour la Bibliothèque clinique."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from server.blueprints.library.plan_schema import SCHEMA_VERSION, get_plan_json_schema
from server.services.openai_client import DEFAULT_TEXT_MODEL, get_openai_client

try:  # pragma: no cover - dépendance optionnelle
    import httpx
except Exception:  # pragma: no cover - httpx peut être absent
    httpx = None  # type: ignore[assignment]


class LibraryLLMError(RuntimeError):
    """Erreur générique pour les opérations LLM de la bibliothèque."""


class LibraryLLMUpstreamError(LibraryLLMError):
    """Erreur signalant une indisponibilité de l'API amont."""


LOGGER = logging.getLogger(__name__)

LOGS_DIR = Path("library/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)

INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

EMAIL_RE = re.compile(r"[\w.\-]+@[\w.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\b(?:\+?\d[\d\s\-]{7,}\d)\b")

MAX_SEGMENTS = 14
MAX_SEGMENT_CHARS = 2000


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_upstream_error(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    try:
        if isinstance(status, int) and 500 <= status < 600:
            return True
    except Exception:  # pragma: no cover - robustesse
        pass
    if httpx is not None:
        if isinstance(exc, getattr(httpx, "TimeoutException", ())):  # type: ignore[arg-type]
            return True
        transport_error = getattr(httpx, "TransportError", None)
        if transport_error and isinstance(exc, transport_error):
            return True
    if isinstance(exc, TimeoutError):
        return True
    return False


@dataclass
class LLMPlanGeneration:
    doc_id: str
    prompt: str
    raw_content: str
    has_tool_calls: bool
    finish_reason: str | None
    model: str

    def preview(self, limit: int = 400) -> str:
        return (self.raw_content or "")[:limit]


@dataclass
class RelaxedParseResult:
    ok: bool
    data: Dict[str, Any] | None
    errors: List[str]
    preview: str
    reason: str | None = None


def _extract_code_block(raw: str) -> str | None:
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_balanced_json_object(raw: str) -> str | None:
    depth = 0
    start = -1
    in_string = False
    escape = False
    for index, char in enumerate(raw):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            if depth:
                depth -= 1
                if depth == 0 and start != -1:
                    return raw[start : index + 1].strip()
    return None


def parse_llm_plan_relaxed(raw: str, *, preview_chars: int = 400) -> RelaxedParseResult:
    text = (raw or "").strip()
    errors: List[str] = []

    def _attempt(candidate: str, label: str) -> Dict[str, Any] | None:
        try:
            loaded = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(f"{label}: {exc.msg} (line {exc.lineno} col {exc.colno})")
            return None
        except Exception as exc:  # pragma: no cover - robustesse
            errors.append(f"{label}: {exc}")
            return None
        if not isinstance(loaded, dict):
            errors.append(f"{label}: root_is_not_object")
            return None
        return loaded

    if text:
        direct = _attempt(text, "direct")
        if direct is not None:
            preview = text[:preview_chars]
            return RelaxedParseResult(True, direct, [], preview)
    else:
        errors.append("empty_content")

    fenced = _extract_code_block(raw)
    if fenced:
        parsed = _attempt(fenced, "code_block")
        if parsed is not None:
            preview = text[:preview_chars]
            return RelaxedParseResult(True, parsed, [], preview)

    balanced = _extract_balanced_json_object(raw)
    if balanced:
        parsed = _attempt(balanced, "balanced")
        if parsed is not None:
            preview = text[:preview_chars]
            return RelaxedParseResult(True, parsed, [], preview)

    preview = text[:preview_chars]
    if not errors:
        errors.append("non_conforming_output")
    return RelaxedParseResult(False, None, errors, preview, reason="non_conforming_output")


def _safe_doc_id_for_filename(doc_id: str) -> str:
    sanitized = INVALID_FILENAME_CHARS_RE.sub("_", doc_id)
    sanitized = sanitized.strip()
    sanitized = sanitized.rstrip(".")
    if not sanitized:
        return _hash_text(doc_id)
    if sanitized in {".", ".."}:
        return _hash_text(doc_id)
    return sanitized


def _pseudonymise(text: str) -> str:
    masked = EMAIL_RE.sub("[EMAIL]", text)
    masked = PHONE_RE.sub("[PHONE]", masked)
    return masked


def _select_segments(segments: Iterable[dict], max_segments: int = MAX_SEGMENTS) -> List[dict]:
    usable: List[dict] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        usable.append(
            {
                "segment_id": str(segment.get("segment_id") or segment.get("id") or f"seg_{len(usable):03d}"),
                "pages": segment.get("pages", []),
                "text": text[:MAX_SEGMENT_CHARS],
            }
        )
    usable.sort(key=lambda item: len(item["text"]), reverse=True)
    return usable[:max_segments]


def _build_prompt(doc_id: str, segments: Sequence[dict]) -> str:
    schema_json = json.dumps(get_plan_json_schema(), ensure_ascii=False)
    header = (
        "Tu es chargé d'analyser des segments extraits d'un document clinique. "
        "Identifie des notions utiles pour la pratique, sans pathologiser, en restant synthétique. "
        "Réponds STRICTEMENT en JSON (UTF-8) sans texte hors JSON et sans délimiteurs ```.")
    examples = [
        "- Croise les sources et signale les divergences pertinentes.",
        "- Priorise les usages cliniques concrets (psychoéducation, questions d'ouverture).",
        "- Marque autosuggest_pre/autosuggest_post selon l'utilité dans chaque onglet.",
        "- Ajoute candidate_notion_id stable en minuscules avec traits d'union.",
        f"- Utilise schema_version='{SCHEMA_VERSION}' exactement.",
    ]
    schema_hint = f"Schéma JSON attendu (version {SCHEMA_VERSION}) : {schema_json}"
    lines = [header, "", "Consignes :"]
    lines.extend(examples)
    lines.append("")
    lines.append(schema_hint)
    lines.append("")
    lines.append(f"doc_id cible : {doc_id}")
    lines.append("Segments fournis :")
    for segment in segments:
        pages = segment.get("pages") or []
        pages_label = ",".join(str(p) for p in pages) if pages else "?"
        text = segment.get("text", "").strip()
        lines.append(
            f"[Segment {segment['segment_id']} | pages {pages_label}]\n{text}\n---"
        )
    return "\n".join(lines)


def _log_plan_interaction(
    doc_id: str,
    prompt: str,
    response_text: str,
    payload: Mapping[str, Any] | None,
    *,
    keep_prompt_clear: bool,
) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    safe_doc_id = _safe_doc_id_for_filename(doc_id)
    log_path = LOGS_DIR / f"{safe_doc_id}_plan.json"
    entry = {
        "doc_id": doc_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt": {
            "hash": _hash_text(prompt),
            "clear": prompt if keep_prompt_clear else None,
        },
        "response": {
            "hash": _hash_text(response_text),
            "clear": response_text if keep_prompt_clear else None,
        },
        "payload": payload,
    }
    log_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


def propose_notions(
    doc_id: str,
    segments: Iterable[dict],
    *,
    pseudonymize: bool = True,
    keep_prompt_clear: bool = False,
) -> LLMPlanGeneration:
    """Construit un plan de notions via l'API OpenAI et retourne la sortie brute."""

    selected_segments = _select_segments(segments)
    if not selected_segments:
        raise LibraryLLMError("Aucun segment exploitable pour proposer des notions.")

    if pseudonymize:
        for item in selected_segments:
            item["text"] = _pseudonymise(item["text"])

    prompt = _build_prompt(doc_id, selected_segments)

    client = get_openai_client()
    if client is None:
        raise LibraryLLMError("Client OpenAI indisponible ou non configuré.")

    model = os.getenv("OPENAI_MODEL_PLAN") or os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_TEXT_MODEL

    messages = [
        {"role": "system", "content": "Tu es un outil de curation clinique extrêmement rigoureux."},
        {"role": "user", "content": prompt},
    ]

    try:
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=model,
            messages=messages,
            temperature=0.15,
            response_format={"type": "json_object"},
            max_tokens=1400,
            seed=42,
            stream=False,
        )
    except Exception as exc:  # pragma: no cover - dépendance externe
        if _is_upstream_error(exc):
            raise LibraryLLMUpstreamError("Service LLM indisponible en amont.") from exc
        raise LibraryLLMError(f"Appel LLM impossible : {exc}") from exc

    try:
        choice = response.choices[0]
        message = choice.message
        content = message.content or ""
    except (AttributeError, IndexError) as exc:  # pragma: no cover - robustesse
        raise LibraryLLMError("Réponse LLM vide ou inattendue.") from exc

    has_tool_calls = bool(getattr(message, "tool_calls", None) or getattr(message, "function_call", None))
    finish_reason = getattr(choice, "finish_reason", None)

    _log_plan_interaction(doc_id, prompt, content, None, keep_prompt_clear=keep_prompt_clear)

    return LLMPlanGeneration(
        doc_id=doc_id,
        prompt=prompt,
        raw_content=content,
        has_tool_calls=has_tool_calls,
        finish_reason=finish_reason,
        model=model,
    )


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Calcule des embeddings à l'aide du modèle configuré."""

    if not texts:
        return []
    client = get_openai_client()
    model = os.getenv("OPENAI_MODEL_EMBED") or os.getenv("OPENAI_MODEL_EMBEDDING") or "text-embedding-3-small"
    if client is None:
        LOGGER.warning("Client OpenAI absent : embeddings non calculés.")
        return []
    try:
        response = client.embeddings.create(model=model, input=texts)  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - dépendance externe
        LOGGER.warning("Impossible de calculer les embeddings : %s", exc)
        raise LibraryLLMError(f"Calcul d'embeddings impossible : {exc}") from exc
    vectors: List[List[float]] = []
    for item in getattr(response, "data", []):
        vector = list(getattr(item, "embedding", []))
        vectors.append(vector)
    return vectors


__all__ = [
    "LibraryLLMError",
    "LibraryLLMUpstreamError",
    "LLMPlanGeneration",
    "RelaxedParseResult",
    "parse_llm_plan_relaxed",
    "propose_notions",
    "embed_texts",
]
