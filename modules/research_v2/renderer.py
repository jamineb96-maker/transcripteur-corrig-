"""Rendu JSON normalisé pour le front pré-session."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List

from .collector import CandidateDocument
from .faceting import Facet
from .filter_dedupe import FilterDecision
from .policy import ResearchPolicy
from .scorer import FacetScores


def render_facet(
    facet: Facet,
    queries: Dict[str, List[str]],
    documents: Iterable[CandidateDocument],
    scores: FacetScores,
    status: str,
    reasons: List[str],
    policy: ResearchPolicy,
    synthesis_block: Dict[str, object],
) -> Dict[str, object]:
    docs_list = list(documents)
    return {
        "name": facet.name,
        "label": facet.label,
        "status": status,
        "status_reasons": reasons,
        "scores": scores.as_dict(),
        "queries": queries,
        "progress": {
            "targets": {
                "candidates": facet.progress_target,
                "whitelist": policy.thresholds.min_whitelist_per_facet,
                "fr_or_eu": 1 if policy.thresholds.require_fr_or_eu else 0,
            },
            "current": {
                "candidates": len(docs_list),
                "whitelist": scores.whitelist_count,
                "fr_or_eu": scores.fr_or_eu_count,
            },
        },
        "synthesis": synthesis_block.get("synthesis", {}),
        "citations": synthesis_block.get("citations", []),
    }


def render_audit(
    session_id: str,
    started_at: datetime,
    decisions: Iterable[FilterDecision],
) -> Dict[str, object]:
    return {
        "session_id": session_id,
        "started_at": started_at.isoformat(),
        "decisions": [
            {"url": decision.url, "kept": decision.kept, "reason": decision.reason}
            for decision in decisions
        ],
    }


def render_payload(facets: List[Dict[str, object]], audit_block: Dict[str, object]) -> Dict[str, object]:
    return {
        "facets": facets,
        "audit": audit_block,
    }


__all__ = ["render_facet", "render_audit", "render_payload"]
