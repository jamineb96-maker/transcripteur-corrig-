"""Extraction heuristics for post-session v2 (deterministic hardening)."""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - yaml optional
    yaml = None  # type: ignore

from .schemas import SessionFacts

BASE_DIR = Path(__file__).resolve().parent
LEXICON_DIR = BASE_DIR / "lexicons"


def _lexicon_path(filename: str) -> Path:
    return LEXICON_DIR / filename


def _load_list(path: Path) -> List[str]:
    items: List[str] = []
    if not path.exists():
        return items
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            entry = line.strip()
            if entry and not entry.startswith("#"):
                items.append(entry)
    return items


def _load_yaml(path: Path) -> Dict[str, Iterable[str]]:
    if not path.exists():
        return {}
    if yaml is not None:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if isinstance(data, dict):
            return {str(k): list(v or []) for k, v in data.items()}
        return {}
    mapping: Dict[str, List[str]] = {}
    current_key: str | None = None
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith(":"):
                current_key = line[:-1].strip()
                mapping[current_key] = []
                continue
            if line.startswith("-") and current_key:
                value = line[1:].strip()
                if value:
                    mapping.setdefault(current_key, []).append(value)
    return mapping


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\s+", " ", value.strip())
    return value.lower()


def _sentences_fr(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[\.\?!;])\s+(?=[A-ZÉÈÊÂÎÔÛÀ])", text)
    if len(parts) < 3:
        parts = re.split(r"(?<=[\.\?!;])\s+", text)
    sentences = [segment.strip().strip('\"') for segment in parts if segment and segment.strip()]
    return sentences


MEDS = {_norm(entry): entry for entry in _load_list(_lexicon_path("meds.txt"))}
THEMES = {key: [_norm(token) for token in tokens] for key, tokens in _load_yaml(_lexicon_path("themes.yaml")).items()}
REQ_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in _load_yaml(_lexicon_path("requests.yaml")).get("patterns", [])]

THERAPIST_MARKERS = re.compile(
    r"\b(je (?:te|vous) (?:rassure|propose|invite|conseille|suggere)|je (?:pense|voudrais) que tu)\b",
    re.IGNORECASE,
)

FLAG_UNCERTAINTY = re.compile(r"\b(je ne sais pas|je ne comprends pas|c['’]?est flou|je suis perdu(?:e)?)\b", re.IGNORECASE)
FLAG_RISK = re.compile(r"\b(suicide|suicidaire|agression|violence|danger|blackout)\b", re.IGNORECASE)


def _detect_meds(transcript: str) -> Tuple[List[Dict[str, object]], List[str]]:
    if not transcript:
        return [], []
    normalized = _norm(transcript)
    meds: List[Dict[str, object]] = []
    matched_tokens: List[str] = []
    for lexeme_norm, lexeme_raw in MEDS.items():
        if not lexeme_norm:
            continue
        pattern = rf"\b{re.escape(lexeme_norm)}\b"
        if re.search(pattern, normalized):
            meds.append({"name": lexeme_raw, "status": "en cours", "effects": []})
            matched_tokens.append(lexeme_raw)
    return meds, matched_tokens


def _count_themes(normalized_transcript: str) -> Tuple[List[str], Dict[str, int]]:
    counts: Counter[str] = Counter()
    for category, keywords in THEMES.items():
        for keyword in keywords:
            if not keyword:
                continue
            counts[category] += len(re.findall(rf"\b{re.escape(keyword)}\b", normalized_transcript))
    ordered = [category for category, _ in counts.most_common() if counts[category] > 0][:6]
    return ordered, dict(counts)


def _pick_asks(sentences: List[str]) -> Tuple[List[str], List[str]]:
    asks: List[str] = []
    raw: List[str] = []
    for sentence in sentences:
        candidate = sentence.strip()
        if not candidate:
            continue
        if THERAPIST_MARKERS.search(candidate):
            continue
        if candidate.endswith("?") or any(pattern.search(candidate) for pattern in REQ_PATTERNS):
            if 30 <= len(candidate) <= 140:
                asks.append(candidate)
                raw.append(candidate)
        if len(asks) >= 5:
            break
    return asks, raw


def _pick_quotes(sentences: List[str]) -> Tuple[List[str], List[str]]:
    quotes: List[str] = []
    candidates: List[str] = []
    for sentence in sentences:
        candidate = sentence.strip()
        if not candidate:
            continue
        if THERAPIST_MARKERS.search(candidate):
            continue
        normalized = f" {_norm(candidate)} "
        if " je " not in normalized:
            continue
        if 80 <= len(candidate) <= 240:
            quotes.append(candidate)
        candidates.append(candidate)
        if len(quotes) >= 5:
            break
    return quotes[:5], candidates[:10]


FILLER_PATTERN = re.compile(
    r"\b(tr[eè]s|vraiment|un peu|plut[oô]t|assez|genre|du coup|peut-[eê]tre|justement)\b",
    re.IGNORECASE,
)


def _condense_sentence(sentence: str) -> str | None:
    if not sentence:
        return None
    text = re.sub(r"\([^)]*\)", "", sentence)
    text = FILLER_PATTERN.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .;")
    if not text:
        return None
    fragments = [frag.strip() for frag in re.split(r"[.;]", text) if frag.strip()]
    if fragments:
        text = fragments[-1] if len(fragments[-1].split()) >= 10 else fragments[0]
    words = text.split()
    if len(words) > 28:
        text = " ".join(words[:28])
    elif len(words) < 12:
        return None
    if not text.endswith((".", "!", "?")):
        text = text + "."
    return text.strip()


def _context_for_category(category: str, sentences: List[str]) -> str | None:
    keywords = THEMES.get(category, [])
    for sentence in reversed(sentences):
        normalized_sentence = _norm(sentence)
        if any(re.search(rf"\b{re.escape(keyword)}\b", normalized_sentence) for keyword in keywords):
            simplified = _condense_sentence(sentence)
            if simplified:
                return simplified
    return None


def _extract_context(sentences: List[str]) -> Dict[str, str | None]:
    context = {
        "travail": _context_for_category("travail", sentences),
        "logement": _context_for_category("logement", sentences),
        "argent": _context_for_category("argent", sentences),
        "famille": _context_for_category("relation", sentences),
    }
    return context


def _collect_flags(normalized_transcript: str) -> Dict[str, List[str]]:
    flags = {"incertitudes": [], "risques": []}
    if FLAG_UNCERTAINTY.search(normalized_transcript):
        flags["incertitudes"].append("incertitude exprimée")
    if FLAG_RISK.search(normalized_transcript):
        flags["risques"].append("risque explicite")
    return flags


def extract_session_facts(
    transcript: str,
    patient: str,
    date_iso: str,
    *,
    debug: bool = False,
):
    """Extract heuristic facts from the raw transcript.

    When ``debug`` is true, returns ``(facts, debug_payload)``.
    """

    start = time.perf_counter()
    sentences = _sentences_fr(transcript)
    normalized_transcript = _norm(transcript)

    meds, meds_matches = _detect_meds(transcript)
    themes, themes_counts = _count_themes(normalized_transcript)
    asks, asks_raw = _pick_asks(sentences)
    quotes, quote_candidates = _pick_quotes(sentences)
    context = _extract_context(sentences)
    flags = _collect_flags(normalized_transcript)

    facts = SessionFacts(
        patient=patient.strip(),
        date=date_iso,
        themes=themes,
        meds=meds,
        context=context,
        asks=asks,
        quotes=quotes,
        flags=flags,
    )

    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event(
        "post_v2_extract",
        {
            "patient": patient,
            "n_quotes": len(quotes),
            "n_meds": len(meds),
            "n_themes": len(themes),
            "ms": duration_ms,
        },
    )

    if not debug:
        return facts

    debug_payload = {
        "meds_matches": meds_matches,
        "asks_raw": asks_raw,
        "quotes_candidates": quote_candidates,
        "themes_counts": themes_counts,
    }
    return facts, debug_payload


def _log_event(event: str, payload: Dict[str, object]) -> None:
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    record.update(payload)
    try:
        journal_path = Path(__file__).resolve().parents[1] / "library" / "store" / "journal.log"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover - logging best effort
        pass


__all__ = ["extract_session_facts"]
