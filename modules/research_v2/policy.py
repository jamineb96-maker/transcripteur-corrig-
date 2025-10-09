"""Chargement et représentation de la politique de recherche."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

import yaml

POLICY_PATH = Path("config/research_policy.yml")


@dataclass
class Thresholds:
    min_candidates_per_facet: int
    min_whitelist_per_facet: int
    require_fr_or_eu: bool
    min_scores: Dict[str, float]


@dataclass
class Weights:
    coverage: float
    freshness: float
    diversity: float


@dataclass
class FreshnessWindows:
    clinical_general_years: int
    drug_and_guideline_years: int
    rights_and_services_months: int


@dataclass
class ResearchPolicy:
    thresholds: Thresholds
    weights: Weights
    freshness_windows: FreshnessWindows


def load_policy(path: Path = POLICY_PATH) -> ResearchPolicy:
    if not path.exists():
        raise FileNotFoundError(f"Fichier de politique introuvable: {path}")

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    thresholds_raw = raw.get("thresholds", {})
    weights_raw = raw.get("weights", {})
    freshness_raw = raw.get("freshness_windows", {})

    thresholds = Thresholds(
        min_candidates_per_facet=int(thresholds_raw.get("min_candidates_per_facet", 0)),
        min_whitelist_per_facet=int(thresholds_raw.get("min_whitelist_per_facet", 0)),
        require_fr_or_eu=bool(thresholds_raw.get("require_fr_or_eu", False)),
        min_scores={
            "coverage": float(thresholds_raw.get("min_scores", {}).get("coverage", 0.0)),
            "freshness": float(thresholds_raw.get("min_scores", {}).get("freshness", 0.0)),
            "diversity": float(thresholds_raw.get("min_scores", {}).get("diversity", 0.0)),
        },
    )

    weights = Weights(
        coverage=float(weights_raw.get("coverage", 0.0)),
        freshness=float(weights_raw.get("freshness", 0.0)),
        diversity=float(weights_raw.get("diversity", 0.0)),
    )

    freshness = FreshnessWindows(
        clinical_general_years=int(freshness_raw.get("clinical_general_years", 5)),
        drug_and_guideline_years=int(freshness_raw.get("drug_and_guideline_years", 2)),
        rights_and_services_months=int(freshness_raw.get("rights_and_services_months", 12)),
    )

    return ResearchPolicy(thresholds=thresholds, weights=weights, freshness_windows=freshness)


__all__ = [
    "Thresholds",
    "Weights",
    "FreshnessWindows",
    "ResearchPolicy",
    "load_policy",
]
