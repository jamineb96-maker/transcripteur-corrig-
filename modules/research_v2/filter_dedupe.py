"""Filtrage qualité et déduplication des candidats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, List, Tuple

from .collector import CandidateDocument
from .policy import ResearchPolicy
from .sources import SourceRegistry


@dataclass
class FilterDecision:
    url: str
    kept: bool
    reason: str


def _tokenise(text: str) -> set[str]:
    return {token.lower() for token in text.split() if len(token) > 3}


def _jaccard(a: str, b: str) -> float:
    tokens_a = _tokenise(a)
    tokens_b = _tokenise(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union else 0.0


def filter_candidates(
    candidates: Iterable[CandidateDocument],
    registry: SourceRegistry,
    policy: ResearchPolicy,
    now: datetime,
) -> Tuple[List[CandidateDocument], List[FilterDecision]]:
    """Filtre les candidats selon la politique et renvoie les décisions."""

    filtered: List[CandidateDocument] = []
    decisions: List[FilterDecision] = []

    freshness_years = policy.freshness_windows.clinical_general_years
    freshness_cutoff = now - timedelta(days=365 * freshness_years)

    for doc in candidates:
        info = registry.lookup(doc.url)
        if registry.is_blocked(doc.url):
            decisions.append(FilterDecision(url=doc.url, kept=False, reason="blocked_domain"))
            continue
        if doc.published_at and doc.published_at < freshness_cutoff:
            decisions.append(FilterDecision(url=doc.url, kept=False, reason="stale"))
            continue
        if info is None and len(doc.content or "") < 240:
            decisions.append(FilterDecision(url=doc.url, kept=False, reason="low_quality"))
            continue
        filtered.append(doc)
        decisions.append(FilterDecision(url=doc.url, kept=True, reason="accepted_initial"))
    return filtered, decisions


def deduplicate_candidates(
    candidates: Iterable[CandidateDocument],
    similarity_threshold: float = 0.85,
) -> Tuple[List[CandidateDocument], List[FilterDecision]]:
    """Supprime les doublons par domaine puis par similarité."""

    kept: List[CandidateDocument] = []
    decisions: List[FilterDecision] = []
    domains_seen: set[str] = set()

    for doc in candidates:
        if doc.domain in domains_seen:
            decisions.append(FilterDecision(url=doc.url, kept=False, reason="duplicate_domain"))
            continue
        duplicate = False
        for previous in kept:
            if _jaccard(doc.content or "", previous.content or "") >= similarity_threshold:
                decisions.append(FilterDecision(url=doc.url, kept=False, reason="duplicate_content"))
                duplicate = True
                break
        if duplicate:
            continue
        domains_seen.add(doc.domain)
        kept.append(doc)
        decisions.append(FilterDecision(url=doc.url, kept=True, reason="kept"))
    return kept, decisions


__all__ = ["FilterDecision", "filter_candidates", "deduplicate_candidates"]
