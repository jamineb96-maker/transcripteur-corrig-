"""Génération de requêtes de recherche cliniques prêtes pour l'index local."""
from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Sequence

from .pii_guard import is_pii_token

LOGGER = logging.getLogger("assist.research.queries")

STOPLIST: frozenset[str] | None = None
LEXICON: frozenset[str] | None = None
IDF_CACHE: Dict[str, float] | None = None
IDF_TOTAL: int = 0
QUERY_DOMAIN_MAP: dict[str, List[str]] = {}

WORD_PATTERN = re.compile(r"[a-zA-Z\u00C0-\u017F]+")

DOMAIN_KEYWORDS = {
    "trauma": "trauma complexe",
    "traumatisme": "trauma complexe",
    "traumatique": "trauma complexe",
    "assertivite": "assertivité relationnelle",
    "alliance": "alliance thérapeutique",
    "therapeutique": "alliance thérapeutique",
    "fatigue": "fatigue décisionnelle",
    "decisionnelle": "fatigue décisionnelle",
    "anxiete": "anxiété",
}


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def _load_stoplist() -> frozenset[str]:
    path = _data_dir() / "stoplist_fr.txt"
    if not path.exists():
        LOGGER.warning("Stoplist manquante (%s)", path)
        return frozenset()
    words = [line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return frozenset(words)


@lru_cache(maxsize=1)
def _load_lexicon() -> frozenset[str]:
    path = _data_dir() / "lexique_clinique.txt"
    if not path.exists():
        LOGGER.warning("Lexique clinique manquant (%s)", path)
        return frozenset()
    return frozenset(line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _normalise_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _tokenise(text: str) -> List[str]:
    return WORD_PATTERN.findall(text)


def _stem(token: str) -> str:
    if len(token) <= 3:
        return token
    for suffix in ("aux", "euses", "euse", "trices", "trice", "ment", "tion", "s", "es"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            return token[: -len(suffix)]
    return token


def _ensure_idf() -> Dict[str, float]:
    global IDF_CACHE, IDF_TOTAL
    if IDF_CACHE is not None:
        return IDF_CACHE

    index_dir = Path(__file__).resolve().parent.parent / "library" / "store"
    candidates = [index_dir / "library_index.jsonl", index_dir / "library_index_sample.jsonl"]
    documents: List[Sequence[str]] = []
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    combined = " ".join(
                        str(payload.get(key, ""))
                        for key in ("title", "text", "keywords", "domains", "summary", "notes")
                    )
                    normalised = _normalise_text(combined)
                    tokens = { _stem(tok) for tok in _tokenise(normalised) if tok }
                    if tokens:
                        documents.append(tokens)
        except OSError:
            LOGGER.warning("Lecture impossible de %s", path, exc_info=True)
    if not documents:
        IDF_CACHE = {}
        IDF_TOTAL = 0
        return IDF_CACHE

    df_counter = Counter[str]()
    for tokens in documents:
        for token in tokens:
            df_counter[token] += 1
    total_docs = max(len(documents), 1)
    IDF_TOTAL = total_docs
    IDF_CACHE = {token: math.log((1 + total_docs) / (1 + df)) + 1 for token, df in df_counter.items()}
    return IDF_CACHE


def _detect_capitalised_tokens(text: str) -> set[str]:
    banned: set[str] = set()
    for match in re.finditer(r"\b([A-Z][\w\-]{2,})\b", text or ""):
        token = match.group(1)
        normalized = _normalise_text(token)
        if normalized and normalized not in _load_lexicon():
            banned.add(normalized)
    return banned


def _assign_domains(tokens: Sequence[str]) -> List[str]:
    domains: set[str] = set()
    for token in tokens:
        domain = DOMAIN_KEYWORDS.get(token)
        if domain:
            domains.add(domain)
    return sorted(domains)


def build_queries_fr(
    text: str,
    *,
    patient_names: List[str],
    places: List[str] | None = None,
    top_n: int = 12,
) -> List[str]:
    """Construit une liste de requêtes thématiques prêtes pour la recherche locale."""

    if not text:
        return []

    stoplist = _load_stoplist()
    lexicon = _load_lexicon()
    idf = _ensure_idf()

    normalized_text = _normalise_text(text)
    original_banned = _detect_capitalised_tokens(text)

    banned_tokens = { _normalise_text(name) for name in patient_names or [] }
    if places:
        banned_tokens.update(_normalise_text(place) for place in places if place)
    banned_tokens.update(original_banned)

    tokens = [_stem(tok) for tok in _tokenise(normalized_text)]

    filtered_tokens: List[str] = []
    for token in tokens:
        if not token:
            continue
        if token in stoplist:
            continue
        if token in banned_tokens:
            continue
        if is_pii_token(token, {"names": patient_names, "places": places or []}):
            continue
        filtered_tokens.append(token)

    if not filtered_tokens:
        return []

    tf_counts = Counter(filtered_tokens)
    candidates: Dict[str, float] = defaultdict(float)

    for size in (1, 2, 3):
        if len(filtered_tokens) < size:
            continue
        for idx in range(len(filtered_tokens) - size + 1):
            window = filtered_tokens[idx : idx + size]
            if any(token in banned_tokens for token in window):
                continue
            key = " ".join(window)
            if len(key) <= 3:
                continue
            if all(tok in lexicon or tf_counts[tok] > 1 for tok in window):
                score = 0.0
                for tok in window:
                    idf_score = idf.get(tok, 1.5)
                    score += tf_counts[tok] * idf_score
                score /= size
                if score > candidates[key]:
                    candidates[key] = score
                    domains = _assign_domains(window)
                    if domains:
                        QUERY_DOMAIN_MAP[key] = domains
    if not candidates:
        return []

    ordered = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
    results = []
    seen = set()
    for phrase, _ in ordered:
        if phrase in seen:
            continue
        seen.add(phrase)
        results.append(phrase)
        if len(results) >= top_n:
            break
    return results

