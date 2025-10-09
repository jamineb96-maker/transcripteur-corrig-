"""Consolidation of local and web evidence into a knowledge pack."""

from __future__ import annotations

import json
import time
from typing import Dict, Iterable, List

from .schemas import (
    CitationCandidate,
    CitationRef,
    EvidenceItemLocal,
    EvidenceItemWeb,
    KnowledgeAxis,
    KnowledgePack,
    SessionFacts,
)


def _log_event(event: str, payload: Dict[str, object]) -> None:
    from pathlib import Path

    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    record.update(payload)
    try:
        journal_path = Path(__file__).resolve().parents[1] / "library" / "store" / "journal.log"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover
        pass


def _axis_labels(facts: SessionFacts) -> List[str]:
    labels: List[str] = []
    labels.extend(facts.themes[:4])
    labels.extend([f"Pharmacologie – {med.get('name')}" for med in facts.meds[:2] if isinstance(med, dict) and med.get("name")])
    labels.extend([f"Demande – {ask[:60]}" for ask in facts.asks[:2]])
    if not labels:
        labels = ["Cadre critique matérialiste"]
    while len(labels) < 4:
        labels.append(f"Cadre situé {len(labels)+1}")
    return labels[:7]


def _citations_from_items(items: Iterable[EvidenceItemLocal | EvidenceItemWeb]) -> List[CitationCandidate]:
    candidates: List[CitationCandidate] = []
    for item in items:
        if isinstance(item, EvidenceItemLocal):
            candidates.append(
                CitationCandidate(
                    short=item.title,
                    source=item.doc_id,
                    pages=item.pages,
                    url=None,
                )
            )
        else:
            candidates.append(
                CitationCandidate(
                    short=item.title,
                    source=item.outlet,
                    pages=None,
                    url=item.url,
                )
            )
    return candidates


def _phrases_appui(label: str, facts: SessionFacts, local: List[EvidenceItemLocal], web: List[EvidenceItemWeb]) -> List[str]:
    phrases: List[str] = []
    if facts.quotes:
        phrases.append(f"Repère subjectif : « {facts.quotes[0]} »")
    if local:
        phrases.append(
            f"Lecture située : {local[0].title} ({local[0].year}) souligne un cadrage matérialiste mobilisable."
        )
    if web:
        phrases.append(
            f"Trace web : {web[0].outlet} ({web[0].date or 'date inconnue'}) rappelle les conditions minimales de filets."
        )
    while len(phrases) < 2:
        phrases.append("Piste critique à documenter avec prudence explicite.")
    return phrases[:4]


def _citations_for_axis(local: List[EvidenceItemLocal], web: List[EvidenceItemWeb]) -> List[CitationRef]:
    refs: List[CitationRef] = []
    for item in local[:2]:
        refs.append(
            CitationRef(
                type="local",
                ref=item.doc_id,
                pages=item.pages,
                url=None,
            )
        )
    for item in web[:1]:
        refs.append(
            CitationRef(
                type="web",
                ref=item.outlet,
                pages=None,
                url=item.url,
            )
        )
    return refs


def build_knowledge_pack(
    session_facts: SessionFacts,
    local_items: List[EvidenceItemLocal],
    web_items: List[EvidenceItemWeb],
) -> KnowledgePack:
    start = time.perf_counter()
    labels = _axis_labels(session_facts)
    axes: List[KnowledgeAxis] = []
    for index, label in enumerate(labels):
        local_slice = local_items[index : index + 2]
        web_slice = web_items[index : index + 1]
        rationale = (
            f"Axe {index + 1}: {label}. Consolidation critique des conditions de vie et des repères non prescriptifs."
        )
        phrases = _phrases_appui(label, session_facts, local_slice, web_slice)
        citations = _citations_for_axis(local_slice, web_slice)
        axes.append(
            KnowledgeAxis(
                label=label,
                rationale=rationale,
                phrases_appui=phrases,
                citations=citations,
            )
        )
    axes = axes[:7]
    citation_candidates = _citations_from_items([*local_items, *web_items])
    hypotheses = []
    base_context = session_facts.context or {}
    if base_context.get("travail"):
        hypotheses.append("Hypothèse située : le travail reste un foyer de contraintes matérielles explicites.")
    if base_context.get("logement"):
        hypotheses.append("Hypothèse située : logement instable, à croiser avec les filets institutionnels disponibles.")
    if session_facts.flags.get("risques"):
        hypotheses.append("Risques repérés : à documenter sans dramatisation, mais à garder en veille continue.")
    if not hypotheses:
        hypotheses.append("Hypothèse située : consolider les filets de continuité sans injonctions de performance.")
    while len(hypotheses) < 2:
        hypotheses.append("Hypothèse située complémentaire à co-construire avec la personne.")
    pistes = [
        "Poursuivre une lecture matérialiste des déterminants sans moraline.",
        "Vérifier l'accessibilité des ressources institutionnelles déjà évoquées.",
        "Proposer des filets de continuité plutôt qu'un plan d'action prescriptif.",
    ]
    if session_facts.meds:
        pistes.append("Coordonner avec la prescription pour ajuster sans injonction comportementale.")
    if web_items:
        pistes.append("Partager la source web la plus solide en précisant le niveau de preuve.")
    pistes = pistes[:6]
    bundle = KnowledgePack(
        axes=axes,
        citations_candidates=citation_candidates,
        hypotheses_situees=hypotheses[:4],
        pistes_regulation=pistes,
    )
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event("post_v2_consolidate", {"axes": len(axes), "ms": duration_ms})
    return bundle


__all__ = ["build_knowledge_pack"]
