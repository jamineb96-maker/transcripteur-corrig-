"""Pipeline de recherche pré-session v2."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from .audit import configure_logger, log_json
from .collector import CandidateDocument, Collector
from .faceting import Facet, extract_facets
from .filter_dedupe import FilterDecision, deduplicate_candidates, filter_candidates
from .policy import ResearchPolicy, load_policy
from .queries import QueryContext, generate_queries
from .renderer import render_audit, render_facet, render_payload
from .scorer import FacetScores, compute_scores, passes_gating
from .sources import SourceRegistry, load_registry
from .synthesizer import synthesise


@dataclass
class ResearchOptions:
    location: str = "France"
    sensitivity: str = "standard"
    enable_v2: bool = False


def _collect_for_facet(
    facet: Facet,
    collector: Collector,
    registry: SourceRegistry,
    policy: ResearchPolicy,
    query_context: QueryContext,
    now: datetime,
) -> Dict[str, Any]:
    queries = generate_queries(facet, query_context)
    raw_docs = collector.collect(facet, queries, registry)
    filtered, initial_decisions = filter_candidates(raw_docs, registry, policy, now)
    deduped, dedupe_decisions = deduplicate_candidates(filtered)
    scores = compute_scores(deduped, registry, policy, now)

    reasons: List[str] = []
    status = "ok"

    if len(raw_docs) < policy.thresholds.min_candidates_per_facet:
        reasons.append("collecte_insuffisante")
    if scores.whitelist_count < policy.thresholds.min_whitelist_per_facet:
        reasons.append("whitelist_insuffisante")
    if policy.thresholds.require_fr_or_eu and scores.fr_or_eu_count == 0:
        reasons.append("pas_de_source_fr_eu")
    if not passes_gating(scores, policy):
        reasons.append("scores_insuffisants")

    if reasons:
        status = "insuffisant"

    synthesis_docs: Iterable[CandidateDocument] = deduped if status == "ok" else []
    synthesis_block = synthesise(facet, synthesis_docs, scores, registry)

    return {
        "facet": facet,
        "queries": queries,
        "raw_documents": raw_docs,
        "documents": list(synthesis_docs),
        "scores": scores,
        "status": status,
        "reasons": reasons,
        "synthesis": synthesis_block,
        "decisions": initial_decisions + dedupe_decisions,
    }


def run_research_v2(
    plan: Dict[str, Any],
    raw_context: Dict[str, Any],
    options: Optional[ResearchOptions] = None,
    registry: Optional[SourceRegistry] = None,
    policy: Optional[ResearchPolicy] = None,
    collector: Optional[Collector] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    options = options or ResearchOptions()
    registry = registry or load_registry()
    policy = policy or load_policy()
    collector = collector or Collector()
    now = now or datetime.utcnow()

    logger = configure_logger()
    session_id = os.environ.get("PRESESSION_SESSION_ID") or str(uuid4())
    started_at = now

    facets = extract_facets(raw_context)
    context = QueryContext(location=options.location, sensitivity=options.sensitivity)

    facet_blocks: List[Dict[str, Any]] = []
    all_decisions: List[FilterDecision] = []

    for facet in facets:
        block = _collect_for_facet(facet, collector, registry, policy, context, now)
        facet_rendered = render_facet(
            facet=facet,
            queries=block["queries"],
            documents=block["documents"],
            scores=block["scores"],
            status=block["status"],
            reasons=block["reasons"],
            policy=policy,
            synthesis_block=block["synthesis"],
        )
        facet_blocks.append(facet_rendered)
        all_decisions.extend(block["decisions"])

    audit_block = render_audit(session_id=session_id, started_at=started_at, decisions=all_decisions)
    payload = render_payload(facet_blocks, audit_block)

    log_json(
        logger,
        {
            "session_id": session_id,
            "started_at": started_at.isoformat(),
            "facets": [
                {
                    "name": facet_block["name"],
                    "status": facet_block["status"],
                    "reasons": facet_block["status_reasons"],
                    "scores": facet_block["scores"],
                }
                for facet_block in facet_blocks
            ],
        },
    )

    return payload


__all__ = ["run_research_v2", "ResearchOptions"]
