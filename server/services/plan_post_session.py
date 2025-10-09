"""v1.0 – Génération structurée du plan post‑séance.

Ce module encapsule la logique demandée pour produire un plan clinique
structuré à partir de la transcription complète d'une séance.  Il fournit
une API simple : ``generate_structured_plan`` qui retourne un dictionnaire
conforme au schéma ``PLAN_SCHEMA`` décrit dans le cahier des charges.

Points notables :
    * lecture des paramètres dans ``.env`` (avec valeurs par défaut).
    * segmentation du transcript en trois tiers pour garantir la couverture.
    * appel LLM (OpenAI) avec prompt dédié + fallback déterministe.
    * normalisation française systématique sur les textes générés.
    * journalisation dans ``logs/post_session.log`` pour audit.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from server.services.openai_client import DEFAULT_TEXT_MODEL, get_openai_client
from server.utils.fr_text import normalize_punctuation, trim_quotes

PLAN_TITLES: Tuple[str, ...] = (
    "Faits saillants et bifurcations",
    "Hypothèses situées (liens matériels)",
    "Contradictions et tensions",
    "Besoins et demandes (explicites/implicites)",
    "Ressources, alliances, marges de manœuvre",
    "Pistes d’action et micro-décisions réalistes",
)

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "post_session" / "plan_fr.txt"
_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "post_session.log"


@dataclass(frozen=True)
class PlanConfig:
    """Paramètres dynamiques contrôlés par l'environnement."""

    min_words: int = 450
    max_words: int = 700
    model: str = DEFAULT_TEXT_MODEL


def _load_config() -> PlanConfig:
    min_words = int(os.getenv("POSTSESSION_PLAN_WORDS_MIN", "450") or 450)
    max_words = int(os.getenv("POSTSESSION_PLAN_WORDS_MAX", "700") or 700)
    if max_words < min_words:
        max_words = min_words + 120
    model = os.getenv("POSTSESSION_PLAN_MODEL", DEFAULT_TEXT_MODEL) or DEFAULT_TEXT_MODEL
    return PlanConfig(min_words=min_words, max_words=max_words, model=model)


_LOGGER: Optional[logging.Logger] = None


def _get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    logger = logging.getLogger("assist.post_session.plan")
    if not logger.handlers:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    _LOGGER = logger
    return logger


def _split_sentences_with_span(text: str) -> List[Tuple[str, int, int]]:
    pattern = re.compile(r"[^.!?\n]+[.!?]?", re.UNICODE)
    sentences: List[Tuple[str, int, int]] = []
    for match in pattern.finditer(text):
        raw = match.group().strip()
        if not raw:
            continue
        start, end = match.span()
        sentences.append((raw, start, end))
    if not sentences:
        sentences.append((text.strip(), 0, len(text.strip())))
    return sentences


def _segment_transcript(text: str) -> List[Dict[str, object]]:
    sentences = _split_sentences_with_span(text)
    total = len(sentences)
    chunk = max(1, math.ceil(total / 3))
    segments: List[Dict[str, object]] = []
    labels = ["DEBUT", "MILIEU", "FIN"]
    for idx in range(3):
        start_idx = idx * chunk
        end_idx = min((idx + 1) * chunk, total)
        subset = sentences[start_idx:end_idx] or [sentences[-1]]
        start_pos = subset[0][1]
        end_pos = subset[-1][2]
        content = " ".join(sentence for sentence, _, _ in subset).strip()
        segments.append(
            {
                "label": labels[idx],
                "text": content,
                "start": start_pos,
                "end": end_pos,
                "sentences": subset,
            }
        )
    return segments


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return (
            "Tu écris en français. Génère un JSON avec les modules de plan demandés."
        )


def _build_prompt(segments: Sequence[Dict[str, object]], previous_notes: Optional[str]) -> str:
    payload = [_load_prompt().strip()]
    for segment in segments:
        payload.append(f"[{segment['label']}]\n{segment['text']}")
    if previous_notes:
        payload.append(f"[NOTES_ANTERIEURES]\n{previous_notes}")
    return "\n\n".join(payload)


def _call_llm(prompt: str, *, model: str) -> Optional[Dict[str, object]]:
    client = get_openai_client()
    if client is None:
        return None
    messages = [
        {"role": "system", "content": "Tu produces un JSON valide strict."},
        {"role": "user", "content": prompt},
    ]
    try:  # pragma: no cover - dépend de l'API externe
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=model,
            messages=messages,
            temperature=0.1,
        )
    except Exception:
        return None
    try:
        content = response.choices[0].message.content or ""
        return json.loads(content)
    except Exception:
        return None


def _fallback_summary(text: str, label: str) -> str:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
    if not sentences:
        return f"Aucun élément distinct relevé pour {label.lower()}."
    focus = sentences[: min(3, len(sentences))]
    reformulated = []
    for sentence in focus:
        reformulated.append(f"{label.title()} : {sentence}")
    return " ".join(reformulated)


def _fallback_plan(segments: Sequence[Dict[str, object]]) -> Dict[str, object]:
    modules = []
    for idx, title in enumerate(PLAN_TITLES):
        segment = segments[min(idx, len(segments) - 1)]
        content = _fallback_summary(segment["text"], segment["label"])
        modules.append(
            {
                "titre": title,
                "contenu": normalize_punctuation(content),
                "anchors": [[segment["start"], segment["end"]]],
            }
        )
    resume = "Séance synthétisée automatiquement faute de modèle LLM disponible."
    return {"modules": modules, "resume_editorial_5lignes": normalize_punctuation(resume)}


def _ensure_modules(plan: Dict[str, object], segments: Sequence[Dict[str, object]]) -> Dict[str, object]:
    modules = plan.get("modules") if isinstance(plan, dict) else None
    normalized: List[Dict[str, object]] = []
    if isinstance(modules, Sequence):
        for title in PLAN_TITLES:
            match = next((module for module in modules if module.get("titre") == title), None)
            if isinstance(match, dict):
                normalized.append(match)
            else:
                normalized.append({"titre": title, "contenu": "", "anchors": []})
    else:
        for title in PLAN_TITLES:
            normalized.append({"titre": title, "contenu": "", "anchors": []})

    for idx, module in enumerate(normalized):
        anchors = module.get("anchors")
        if not isinstance(anchors, Sequence) or not anchors:
            segment = segments[min(idx, len(segments) - 1)]
            module["anchors"] = [[int(segment["start"]), int(segment["end"])]]
        else:
            sanitized = []
            for anchor in anchors:
                try:
                    start, end = int(anchor[0]), int(anchor[1])
                except Exception:
                    continue
                if end < start:
                    start, end = end, start
                sanitized.append([start, end])
            if not sanitized:
                segment = segments[min(idx, len(segments) - 1)]
                sanitized = [[int(segment["start"]), int(segment["end"])]]
            module["anchors"] = sanitized
        text = normalize_punctuation(module.get("contenu", ""))
        module["contenu"] = trim_quotes(text)
    resume = trim_quotes(normalize_punctuation(plan.get("resume_editorial_5lignes", "")))
    plan["modules"] = normalized
    plan["resume_editorial_5lignes"] = resume
    return plan


def _enforce_length(plan: Dict[str, object], *, min_words: int, max_words: int) -> Dict[str, object]:
    all_text = " ".join(str(module.get("contenu", "")) for module in plan.get("modules", []))
    all_text += " " + str(plan.get("resume_editorial_5lignes", ""))
    words = [word for word in all_text.split() if word]
    count = len(words)
    if count < min_words:
        deficit = min_words - count
        plan["resume_editorial_5lignes"] = (
            f"{plan.get('resume_editorial_5lignes', '')} (Complément automatique : {deficit} mots manquants à détailler)"
        )
    elif count > max_words:
        ratio = max_words / max(count, 1)
        for module in plan.get("modules", []):
            text = str(module.get("contenu", ""))
            trimmed = " ".join(text.split()[: max(20, int(len(text.split()) * ratio))])
            module["contenu"] = trimmed + "…"
    return plan


def _ensure_segment_coverage(plan: Dict[str, object], segments: Sequence[Dict[str, object]]) -> None:
    if not segments:
        return
    first_sentence = segments[0]["sentences"][0][0] if segments[0]["sentences"] else segments[0]["text"]
    last_sentence = segments[-1]["sentences"][-1][0] if segments[-1]["sentences"] else segments[-1]["text"]
    module0 = plan["modules"][0]
    if first_sentence and first_sentence not in module0["contenu"]:
        module0["contenu"] = f"{module0['contenu']} (Début : {first_sentence})"
    module_last = plan["modules"][-1]
    if last_sentence and last_sentence not in module_last["contenu"]:
        module_last["contenu"] = f"{module_last['contenu']} (Fin : {last_sentence})"


def format_structured_plan(plan: Dict[str, object]) -> str:
    """Convertit le JSON en bloc texte multi-ligne pour l'UI existante."""

    lines: List[str] = []
    for module in plan.get("modules", []):
        title = module.get("titre", "Module")
        content = module.get("contenu", "")
        if content:
            lines.append(f"{title} : {content}")
    resume = plan.get("resume_editorial_5lignes")
    if resume:
        lines.append("")
        lines.append(f"Résumé éditorial : {resume}")
    return "\n".join(lines).strip()


def generate_structured_plan(transcript: str, previous_notes: Optional[str] = None) -> Dict[str, object]:
    """Génère un plan structuré conforme au nouveau cahier des charges."""

    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("empty_transcript")
    segments = _segment_transcript(transcript)
    config = _load_config()
    prompt = _build_prompt(segments, previous_notes)
    logger = _get_logger()
    logger.info("plan_generation_start len=%d", len(transcript))

    result = _call_llm(prompt, model=config.model)
    if result is None:
        logger.warning("plan_generation_fallback")
        plan = _fallback_plan(segments)
    else:
        plan = result
    plan = _ensure_modules(plan, segments)
    plan = _enforce_length(plan, min_words=config.min_words, max_words=config.max_words)
    _ensure_segment_coverage(plan, segments)
    logger.info("plan_generation_done modules=%d", len(plan.get("modules", [])))
    plan["segments"] = [
        {"label": seg["label"], "start": seg["start"], "end": seg["end"], "text": seg["text"]}
        for seg in segments
    ]
    plan["word_count"] = sum(len(str(module.get("contenu", "")).split()) for module in plan.get("modules", []))
    plan["config"] = {
        "min_words": config.min_words,
        "max_words": config.max_words,
        "model": config.model,
    }
    return plan


__all__ = ["generate_structured_plan", "format_structured_plan"]
