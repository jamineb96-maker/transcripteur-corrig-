"""Fonctions utilitaires pour la recherche post-séance."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, Iterator, List, Sequence

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+(?=[A-ZÉÈÀÂÎÔÛÄËÏÖÜ0-9])")
_TOKEN_PATTERN = re.compile(r"[\w\-’']+")
_STOPWORDS = {
    "a",
    "au",
    "aux",
    "ce",
    "ces",
    "cet",
    "cette",
    "dans",
    "de",
    "des",
    "du",
    "elle",
    "elles",
    "en",
    "et",
    "il",
    "ils",
    "je",
    "la",
    "le",
    "les",
    "leur",
    "leurs",
    "mais",
    "ne",
    "nous",
    "on",
    "ou",
    "par",
    "pas",
    "pour",
    "que",
    "qui",
    "se",
    "ses",
    "son",
    "sur",
    "tu",
    "un",
    "une",
    "vos",
    "vous",
}


def _strip_diacritics(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _norm(value: str) -> str:
    return _strip_diacritics(value).casefold().strip()


def ensure_text(value: str | None) -> str:
    return str(value or "").strip()


def _sentences_fr(text: str) -> List[str]:
    cleaned = unicodedata.normalize("NFKC", text or "")
    cleaned = cleaned.replace("\r", " ").strip()
    if not cleaned:
        return []
    segments: List[str] = []
    for chunk in _SENTENCE_BOUNDARY.split(cleaned):
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) < 25 and segments:
            segments[-1] = f"{segments[-1]} {chunk}".strip()
        else:
            segments.append(chunk)
    return segments


def tokenize(text: str | Sequence[str]) -> List[str]:
    if isinstance(text, str):
        normalized = _norm(text)
        tokens = [re.sub(r"[^\w-]", "", token) for token in _TOKEN_PATTERN.findall(normalized)]
        return [token for token in tokens if token]
    return [str(token).strip() for token in text if str(token).strip()]


def split_sentences(text: str) -> List[str]:
    return _sentences_fr(text)


def select_salient_sentences(
    sentences: Sequence[str],
    *,
    limit: int = 12,
    min_chars: int = 80,
    max_chars: int = 200,
) -> List[str]:
    selected: List[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        text = " ".join(sentence.split())
        if not text:
            continue
        normalized = _norm(text)
        if normalized in seen:
            continue
        if "therapeute" in normalized or "praticien" in normalized or "coach" in normalized:
            continue
        if len(text) < min_chars:
            continue
        if len(text) > max_chars:
            text = text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
        seen.add(normalized)
        selected.append(text)
        if len(selected) >= limit:
            break
    return selected


def extract_ngrams(
    source: Sequence[str] | str,
    *,
    max_n: int = 3,
    limit: int = 20,
    stopset: Iterable[str] | None = None,
) -> List[str]:
    tokens = tokenize(source)
    if not tokens:
        return []
    effective_stopset = set(stopset or _STOPWORDS)
    cleaned = [token for token in tokens if token and token not in effective_stopset]
    phrases: List[str] = []
    seen: set[str] = set()
    for n in range(1, max_n + 1):
        if n == 1:
            candidates = cleaned
        else:
            candidates = [" ".join(cleaned[idx : idx + n]) for idx in range(len(cleaned) - n + 1)]
        for gram in candidates:
            gram = gram.strip()
            if len(gram) < 5 or len(gram) > 80:
                continue
            if gram in seen:
                continue
            seen.add(gram)
            phrases.append(gram)
            if len(phrases) >= limit:
                return phrases
    return phrases


def clean_lines(text: str, *, max_lines: int = 15) -> str:
    lines = [line.strip() for line in ensure_text(text).splitlines() if line.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    return "\n".join(lines)


def sanitize_block(block: str) -> str:
    block = ensure_text(block)
    block = re.sub(r"\n{3,}", "\n\n", block)
    return block.strip()


def iter_nonempty(values: Iterable[str]) -> Iterator[str]:
    for value in values:
        cleaned = ensure_text(value)
        if cleaned:
            yield cleaned


def count_lines(text: str) -> int:
    cleaned = ensure_text(text)
    if not cleaned:
        return 0
    return cleaned.count("\n") + 1


def format_biblio_item(record: Dict[str, object]) -> str:
    author = ensure_text(record.get("author") or record.get("type") or "Auteur inconnu")
    year = ensure_text(record.get("year") or "s.d.")
    title = ensure_text(record.get("title") or "Document clinique")
    page = ensure_text(record.get("page") or record.get("page_label") or "")
    if not page:
        page = "p.n.c."
    else:
        lower_page = page.casefold()
        if not lower_page.startswith("p"):
            page = f"p.{page}"
        elif not lower_page.startswith("p."):
            suffix = page.split(".", 1)[-1]
            page = f"p.{suffix}" if suffix else "p.n.c."
    excerpt = ensure_text(record.get("excerpt") or record.get("snippet") or "")
    if len(excerpt) > 240:
        excerpt = excerpt[:239].rsplit(" ", 1)[0] + "…"
    return f"{author}, {year} — {title}, {page} : « {excerpt} »"


__all__ = [
    "_norm",
    "_sentences_fr",
    "clean_lines",
    "count_lines",
    "ensure_text",
    "extract_ngrams",
    "format_biblio_item",
    "iter_nonempty",
    "sanitize_block",
    "select_salient_sentences",
    "split_sentences",
    "tokenize",
]
