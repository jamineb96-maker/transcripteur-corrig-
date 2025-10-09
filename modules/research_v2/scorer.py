"""Scoring des candidats filtrés."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .collector import CandidateDocument
from .policy import ResearchPolicy
from .sources import SourceRegistry


@dataclass
class FacetScores:
    coverage: float
    freshness: float
    diversity: float
    aggregate: float
    whitelist_count: int
    fr_or_eu_count: int

    def as_dict(self) -> dict[str, float]:
        return {
            "coverage": self.coverage,
            "freshness": self.freshness,
            "diversity": self.diversity,
        }


def compute_scores(
    documents: Iterable[CandidateDocument],
    registry: SourceRegistry,
    policy: ResearchPolicy,
    now: datetime,
) -> FacetScores:
    docs = list(documents)
    whitelist_docs = [doc for doc in docs if registry.is_whitelisted(doc.url)]
    whitelist_count = len(whitelist_docs)

    coverage_target = max(policy.thresholds.min_whitelist_per_facet, 1)
    coverage = min(1.0, whitelist_count / coverage_target)

    freshness_scores = []
    for doc in docs:
        if doc.published_at is None:
            freshness_scores.append(0.5)
        else:
            age_days = max((now - doc.published_at).days, 0)
            window_days = 365 * policy.freshness_windows.drug_and_guideline_years
            freshness_scores.append(max(0.0, 1.0 - age_days / max(window_days, 1)))
    freshness = sum(freshness_scores) / len(freshness_scores) if freshness_scores else 0.0

    jurisdictions = {doc.jurisdiction for doc in docs if doc.jurisdiction}
    angles = {doc.angle for doc in docs}
    diversity_target = max(len(angles), 1)
    diversity = min(1.0, len(jurisdictions) / diversity_target)

    fr_or_eu_count = sum(1 for doc in docs if doc.jurisdiction in {"FR", "EU", "UE"})

    weights = policy.weights
    aggregate = (
        coverage * weights.coverage
        + freshness * weights.freshness
        + diversity * weights.diversity
    )

    return FacetScores(
        coverage=round(coverage, 3),
        freshness=round(freshness, 3),
        diversity=round(diversity, 3),
        aggregate=round(aggregate, 3),
        whitelist_count=whitelist_count,
        fr_or_eu_count=fr_or_eu_count,
    )


def passes_gating(scores: FacetScores, policy: ResearchPolicy) -> bool:
    thresholds = policy.thresholds.min_scores
    if scores.coverage < thresholds.get("coverage", 0.0):
        return False
    if scores.freshness < thresholds.get("freshness", 0.0):
        return False
    if scores.diversity < thresholds.get("diversity", 0.0):
        return False
    return True


__all__ = ["FacetScores", "compute_scores", "passes_gating"]
