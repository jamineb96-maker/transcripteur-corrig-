"""Synthèse structurée des résultats par facette."""

from __future__ import annotations

from typing import Dict, Iterable, List

from .collector import CandidateDocument
from .faceting import Facet
from .scorer import FacetScores
from .sources import SourceRegistry


def _format_date(doc: CandidateDocument) -> str:
    if doc.published_at is None:
        return ""
    return doc.published_at.date().isoformat()


def build_citations(docs: Iterable[CandidateDocument], registry: SourceRegistry) -> List[Dict[str, str]]:
    citations: List[Dict[str, str]] = []
    for doc in docs:
        info = registry.lookup(doc.url)
        citations.append(
            {
                "title": doc.title or doc.domain,
                "url": doc.url,
                "date": _format_date(doc),
                "jurisdiction": (info.jurisdiction if info else doc.jurisdiction or "INT"),
                "evidence_level": (info.evidence_level if info else doc.evidence_level or "unknown"),
                "comment": doc.snippet[:220],
            }
        )
    return citations


def synthesise(
    facet: Facet,
    docs: Iterable[CandidateDocument],
    scores: FacetScores,
    registry: SourceRegistry,
) -> Dict[str, object]:
    docs_list = list(docs)
    if not docs_list:
        return {
            "synthesis": {
                "evidence": "Sources insuffisantes pour formuler une synthèse fiable.",
                "determinants": "Données manquantes sur les droits et les déterminants.",
                "feasibility": "Aucune proposition tant que la collecte n'est pas consolidée.",
                "coordination": "Reprendre la recherche avec un appui institutionnel.",
            },
            "citations": [],
        }

    top = docs_list[:2]
    evidence_sentences = []
    for doc in top:
        evidence_sentences.append(
            f"{doc.title or doc.domain} ({_format_date(doc) or 'n.d.'}) souligne {doc.snippet[:140]}"
        )

    evidence_text = " ".join(evidence_sentences)
    determinants_text = (
        "Repérage des déterminants matériels : délais d'accès, coûts directs, ruptures de soins, "
        "et inégalités territoriales identifiées dans les sources récentes."
    )
    feasibility_text = (
        "Ce que cela change ici et maintenant : prioriser les démarches accessibles (téléconsultations, "
        "services publics locaux, associations de patientes) et documenter les obstacles rencontrés."
    )
    coordination_text = (
        "Coordination : préparer un échange avec les équipes douleur, le service social du centre hospitalier "
        "et la médecine générale pour articuler droits, suivi et aménagements."
    )

    return {
        "synthesis": {
            "evidence": evidence_text,
            "determinants": determinants_text,
            "feasibility": "Fenêtres de faisabilité : " + feasibility_text,
            "coordination": coordination_text,
        },
        "citations": build_citations(docs_list, registry),
    }


__all__ = ["synthesise", "build_citations"]
