"""v1.0 – Recherche unifiée post‑séance (RAG + web contrôlé).

Le service ``run_unified_research`` orchestre :
    * l'extraction automatique de mots-clés matériels et pharmacologiques ;
    * la requête de la bibliothèque locale (RAG) via ``LocalSearchEngine`` ;
    * la sollicitation optionnelle d'une recherche web (OpenAI) ;
    * la génération de cartes critiques structurées selon le format imposé ;
    * la production d'un bloc bibliographique court prêt pour le méga-prompt.

Toutes les réponses sont normalisées via ``normalize_punctuation`` et les citations
sont raccourcies à ≤ 10 mots grâce à ``trim_quotes``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from modules.research_engine import search_web_openai

from server.services.library_search import LocalSearchEngine
from server.services.openai_client import DEFAULT_TEXT_MODEL, get_openai_client
from server.utils.fr_text import normalize_punctuation, trim_quotes

_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "post_session" / "recherche_fr.txt"
_LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "post_session.log"

_STOPWORDS = {
    "je",
    "tu",
    "il",
    "elle",
    "nous",
    "vous",
    "ils",
    "elles",
    "les",
    "des",
    "une",
    "dans",
    "avec",
    "pour",
    "sur",
    "par",
    "aux",
    "ses",
    "leurs",
    "mais",
    "plus",
    "tout",
    "tous",
    "faire",
    "avoir",
    "être",
    "entre",
    "chez",
    "depuis",
    "vers",
}


@dataclass(frozen=True)
class ResearchConfig:
    search_external: bool = True
    timeout_sec: int = 20
    rag_topk: int = 6
    web_topk: int = 4
    min_year: int = 2015
    language: str = "fr"
    model: str = DEFAULT_TEXT_MODEL


def _load_config(overrides: Optional[Dict[str, object]] = None) -> ResearchConfig:
    overrides = overrides or {}
    env_search = os.getenv("POSTSESSION_SEARCH_EXTERNAL", "on").lower()
    search_external = env_search not in {"0", "off", "false", "no"}
    search_external = bool(overrides.get("search_external", search_external))
    timeout_sec = int(os.getenv("POSTSESSION_SEARCH_TIMEOUT_SEC", "20") or 20)
    rag_topk = int(os.getenv("POSTSESSION_RAG_TOPK", "6") or 6)
    web_topk = int(os.getenv("POSTSESSION_WEB_TOPK", "4") or 4)
    min_year = int(os.getenv("POSTSESSION_MIN_YEAR", "2015") or 2015)
    language = os.getenv("POSTSESSION_LANG", "fr") or "fr"
    model = os.getenv("POSTSESSION_RESEARCH_MODEL", DEFAULT_TEXT_MODEL) or DEFAULT_TEXT_MODEL
    return ResearchConfig(
        search_external=search_external,
        timeout_sec=timeout_sec,
        rag_topk=max(1, rag_topk),
        web_topk=max(0, web_topk),
        min_year=min_year,
        language=language,
        model=model,
    )


_ENGINE: Optional[LocalSearchEngine] = None
_LOGGER: Optional[logging.Logger] = None


def _get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    logger = logging.getLogger("assist.post_session.research")
    if not logger.handlers:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    _LOGGER = logger
    return logger


def _engine() -> Optional[LocalSearchEngine]:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    try:
        _ENGINE = LocalSearchEngine()
    except Exception:
        _ENGINE = None
    return _ENGINE


def _extract_keywords(transcript: str) -> List[str]:
    tokens = re.findall(r"[\wÀ-ÖØ-öø-ÿ]{3,}", transcript.lower())
    counts: Dict[str, int] = {}
    for token in tokens:
        if token in _STOPWORDS:
            continue
        counts[token] = counts.get(token, 0) + 1
    sorted_tokens = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [token for token, _ in sorted_tokens[:20]]


def _extract_year_mentions(transcript: str) -> List[int]:
    years = set()
    for match in re.finditer(r"(20\d{2})", transcript):
        try:
            years.add(int(match.group(1)))
        except ValueError:
            continue
    return sorted(years)


def _search_internal(keywords: Sequence[str], config: ResearchConfig) -> List[Dict[str, object]]:
    engine = _engine()
    if engine is None:
        return []
    queries = [" ".join(keywords[:6])]
    queries.extend(keywords[: config.rag_topk])
    hits = engine.search([query for query in queries if query], top_k=config.rag_topk)
    results: List[Dict[str, object]] = []
    seen: set[Tuple[str, int]] = set()
    for hit in hits:
        doc_id = str(hit.get("doc_id"))
        page = int(hit.get("page") or 0)
        key = (doc_id, page)
        if key in seen:
            continue
        seen.add(key)
        try:
            year = int(hit.get("year")) if hit.get("year") else None
        except (TypeError, ValueError):
            year = None
        if year is not None and year < config.min_year:
            continue
        results.append(
            {
                "doc_id": doc_id,
                "page": page,
                "title": hit.get("title") or "Document clinique",
                "year": year,
                "type": hit.get("type") or "Article",
                "level": hit.get("level"),
                "domains": hit.get("domain") or hit.get("domains") or [],
                "snippet": hit.get("snippet") or hit.get("text", "")[:260],
                "score": hit.get("score"),
            }
        )
    return results[: config.rag_topk]


def _search_external(keywords: Sequence[str], config: ResearchConfig) -> List[Dict[str, object]]:
    if not config.search_external or not keywords or config.web_topk <= 0:
        return []
    query = " ".join(keywords[:12])
    try:
        results = search_web_openai(query, k=config.web_topk)
    except Exception:
        return []
    formatted: List[Dict[str, object]] = []
    for item in results[: config.web_topk]:
        formatted.append(
            {
                "title": item.get("title", "Source externe"),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "type": "web",
                "year": None,
            }
        )
    return formatted


def _load_prompt() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Produis des cartes JSON.".strip()


def _build_context(transcript: str, keywords: Sequence[str], internal: Sequence[Dict[str, object]], external: Sequence[Dict[str, object]]) -> str:
    transcript_excerpt = transcript[:1600]
    lines = [
        _load_prompt(),
        f"MOTS-CLES: {', '.join(keywords[:12])}",
        f"ANNEES_MENTIONNEES: {', '.join(str(year) for year in _extract_year_mentions(transcript)) or 'aucune'}",
        "[INTERNES]",
    ]
    for hit in internal:
        domains = ", ".join(hit.get("domains", []) or [])
        line = (
            f"- {hit.get('title')} ({hit.get('year') or 's.d.'}) | {hit.get('type')} | p.{hit.get('page')} | {domains} | {hit.get('snippet')}"
        )
        lines.append(line)
    lines.append("[EXTERNES]")
    for item in external:
        lines.append(f"- {item.get('title')} | {item.get('url')} | {item.get('snippet')}")
    lines.append("[TRANSCRIPT_RESUME]")
    lines.append(transcript_excerpt)
    return "\n".join(lines)


def _call_llm(context: str, config: ResearchConfig) -> Optional[Dict[str, object]]:
    client = get_openai_client()
    if client is None:
        return None
    messages = [
        {"role": "system", "content": "Tu produis un JSON valide avec des cartes critiques."},
        {"role": "user", "content": context},
    ]
    try:  # pragma: no cover - dépend de l'API externe
        response = client.chat.completions.create(  # type: ignore[attr-defined]
            model=config.model,
            messages=messages,
            temperature=0.2,
        )
    except Exception:
        return None
    try:
        content = response.choices[0].message.content or ""
        return json.loads(content)
    except Exception:
        return None


def _normalize_implications(raw: object) -> List[str]:
    if isinstance(raw, (list, tuple)):
        return [normalize_punctuation(str(item)) for item in raw if item]
    if isinstance(raw, str) and raw.strip():
        return [normalize_punctuation(part.strip()) for part in raw.split(";") if part.strip()]
    return []


def _sanitize_cards(cards: Sequence[Dict[str, object]], config: ResearchConfig) -> List[Dict[str, object]]:
    sanitized: List[Dict[str, object]] = []
    seen_keys: set[str] = set()
    for card in cards:
        if not isinstance(card, dict):
            continue
        these = normalize_punctuation(card.get("these", ""))
        if not these:
            continue
        source = card.get("source") or {}
        ref_key = str(source.get("ref") or source.get("url") or these)
        if ref_key in seen_keys:
            continue
        seen_keys.add(ref_key)
        citation = trim_quotes(normalize_punctuation(card.get("citation_courte", "")))
        entry = {
            "these": these,
            "implications": _normalize_implications(card.get("implications")),
            "citation_courte": citation,
            "source": {
                "type": source.get("type") or "",
                "auteurs": normalize_punctuation(source.get("auteurs", "")),
                "annee": source.get("annee") or source.get("year"),
                "ref": normalize_punctuation(source.get("ref", "")),
                "url": source.get("url", ""),
            },
            "limite": normalize_punctuation(card.get("limite", "")),
        }
        year = entry["source"].get("annee")
        try:
            if year is not None and int(year) < config.min_year:
                continue
        except (TypeError, ValueError):
            pass
        sanitized.append(entry)
    return sanitized


def _fallback_cards(internal: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    cards: List[Dict[str, object]] = []
    for hit in internal[:3]:
        cards.append(
            {
                "these": normalize_punctuation(f"{hit.get('title')} (pertinence clinique locale)"),
                "implications": [
                    normalize_punctuation("Relier les constats aux conditions matérielles décrites."),
                    normalize_punctuation("Identifier un ajustement concret faisable à court terme."),
                ],
                "citation_courte": "« extrait bibliothèque »",
                "source": {
                    "type": hit.get("type") or "Article",
                    "auteurs": hit.get("title") or "Auteur inconnu",
                    "annee": hit.get("year") or "s.d.",
                    "ref": f"p.{hit.get('page')} (score {hit.get('score')})",
                    "url": "",
                },
                "limite": normalize_punctuation("Analyse automatique sans revue méthodologique explicite."),
            }
        )
    return cards


def _build_biblio(cards: Sequence[Dict[str, object]]) -> List[str]:
    biblio: List[str] = []
    seen: set[str] = set()
    for card in cards:
        source = card.get("source", {})
        authors = source.get("auteurs") or "Auteur inconnu"
        year = source.get("annee") or "s.d."
        ref = source.get("ref") or card.get("these", "")
        label = normalize_punctuation(f"{authors} ({year}). {ref}.")
        if label in seen:
            continue
        seen.add(label)
        biblio.append(label)
    return biblio


def run_unified_research(transcript: str, overrides: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    transcript = (transcript or "").strip()
    if not transcript:
        raise ValueError("empty_transcript")
    config = _load_config(overrides)
    keywords = _extract_keywords(transcript)
    internal_hits = _search_internal(keywords, config)
    external_hits = _search_external(keywords, config)
    context = _build_context(transcript, keywords, internal_hits, external_hits)
    logger = _get_logger()
    logger.info(
        "research_unified_start len=%d internal=%d external=%d", len(transcript), len(internal_hits), len(external_hits)
    )
    payload = _call_llm(context, config)
    cards_raw = payload.get("cards") if isinstance(payload, dict) else None
    if not cards_raw:
        logger.warning("research_unified_fallback")
        cards = _fallback_cards(internal_hits)
    else:
        cards = _sanitize_cards(cards_raw, config)
        if not cards:
            cards = _fallback_cards(internal_hits)
    biblio = _build_biblio(cards)
    logger.info("research_unified_done cards=%d", len(cards))
    return {
        "cards": cards,
        "biblio": biblio,
        "keywords": keywords,
        "internal_hits": internal_hits,
        "external_hits": external_hits,
    }


__all__ = ["run_unified_research"]
