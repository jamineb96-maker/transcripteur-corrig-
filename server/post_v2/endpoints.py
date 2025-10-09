"""Service layer for post-session v2 API endpoints."""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Tuple

from .consolidate import build_knowledge_pack
from .extract_session import extract_session_facts
from .megatemplate import assemble_megaprompt
from .rag_local import search_local_evidence
from .rag_web import search_web_evidence
from .schemas import (
    CitationCandidate,
    CitationRef,
    EvidenceItemLocal,
    EvidenceItemWeb,
    KnowledgeAxis,
    KnowledgePack,
    MegaPromptBundle,
    SessionFacts,
)
from .style_profile import style_blocks


def _session_facts_from_payload(payload: Dict[str, Any]) -> SessionFacts:
    return SessionFacts(
        patient=str(payload.get("patient", "")).strip(),
        date=str(payload.get("date", "")).strip(),
        themes=list(payload.get("themes", [])),
        meds=list(payload.get("meds", [])),
        context=dict(payload.get("context", {})),
        asks=list(payload.get("asks", [])),
        quotes=list(payload.get("quotes", [])),
        flags=dict(payload.get("flags", {})) or {"risques": [], "incertitudes": []},
    )


def _local_items_from_payload(payload: List[Dict[str, Any]]) -> List[EvidenceItemLocal]:
    items: List[EvidenceItemLocal] = []
    for entry in payload:
        try:
            items.append(
                EvidenceItemLocal(
                    title=str(entry.get("title", "")),
                    doc_id=str(entry.get("doc_id", "")),
                    pages=str(entry.get("pages", "")),
                    extract=str(entry.get("extract", "")),
                    evidence_level=str(entry.get("evidence_level", "")),
                    year=int(entry.get("year", 0)),
                    domains=list(entry.get("domains", [])),
                    chunk_id=str(entry.get("chunk_id", "")),
                    score=float(entry.get("score", 0.0)),
                )
            )
        except Exception:
            continue
    return items


def _web_items_from_payload(payload: List[Dict[str, Any]]) -> List[EvidenceItemWeb]:
    items: List[EvidenceItemWeb] = []
    for entry in payload:
        try:
            items.append(
                EvidenceItemWeb(
                    title=str(entry.get("title", "")),
                    author=str(entry.get("author", "")),
                    outlet=str(entry.get("outlet", "")),
                    date=str(entry.get("date", "")),
                    url=str(entry.get("url", "")),
                    quote=str(entry.get("quote", "")),
                    claim=str(entry.get("claim", "")),
                    reliability_tag=str(entry.get("reliability_tag", "")),
                )
            )
        except Exception:
            continue
    return items


def _knowledge_pack_from_payload(payload: Dict[str, Any] | None) -> KnowledgePack | None:
    if not payload:
        return None
    axes_payload = payload.get("axes", [])
    axes: List[KnowledgeAxis] = []
    for axis in axes_payload:
        try:
            citations = [
                CitationRef(
                    type=str(ref.get("type", "")),
                    ref=str(ref.get("ref", "")),
                    pages=ref.get("pages"),
                    url=ref.get("url"),
                )
                for ref in axis.get("citations", [])
            ]
            phrases = [str(p) for p in axis.get("phrases_appui", [])]
            axes.append(
                KnowledgeAxis(
                    label=str(axis.get("label", "")),
                    rationale=str(axis.get("rationale", "")),
                    phrases_appui=phrases,
                    citations=citations,
                )
            )
        except Exception:
            continue
    candidates = [
        CitationCandidate(
            short=str(item.get("short", "")),
            source=str(item.get("source", "")),
            pages=item.get("pages"),
            url=item.get("url"),
        )
        for item in payload.get("citations_candidates", [])
    ]
    hypotheses = [str(value) for value in payload.get("hypotheses_situees", [])]
    pistes = [str(value) for value in payload.get("pistes_regulation", [])]
    return KnowledgePack(
        axes=axes,
        citations_candidates=candidates,
        hypotheses_situees=hypotheses,
        pistes_regulation=pistes,
    )


def run_extract(payload: Dict[str, Any], *, debug: bool = False) -> SessionFacts | Tuple[SessionFacts, Dict[str, Any]]:
    patient = str(payload.get("patient", "")).strip()
    date = str(payload.get("date", "")).strip()
    transcript = str(payload.get("transcript", ""))
    result = extract_session_facts(transcript, patient, date, debug=debug)
    return result


def run_rag_local(
    session_payload: Dict[str, Any],
    filters: Dict[str, Any] | None = None,
    *,
    debug: bool = False,
) -> List[EvidenceItemLocal] | Tuple[List[EvidenceItemLocal], Dict[str, Any]]:
    facts = _session_facts_from_payload(session_payload)
    return search_local_evidence(facts, filters=filters or {}, debug=debug)


def run_rag_web(session_payload: Dict[str, Any]) -> List[EvidenceItemWeb]:
    facts = _session_facts_from_payload(session_payload)
    return search_web_evidence(facts)


def run_consolidate(payload: Dict[str, Any]) -> KnowledgePack:
    facts = _session_facts_from_payload(payload)
    local_items = _local_items_from_payload(payload.get("local", []))
    web_items = _web_items_from_payload(payload.get("web", []))
    return build_knowledge_pack(facts, local_items, web_items)


def run_megaprompt(payload: Dict[str, Any], token_estimator: Callable[[str], int]) -> MegaPromptBundle:
    facts = _session_facts_from_payload(payload.get("session_facts", payload))
    transcript = str(payload.get("transcript", ""))
    local_items = _local_items_from_payload(payload.get("local", []))
    web_items = _web_items_from_payload(payload.get("web", []))
    kp_payload = payload.get("kp")
    knowledge_pack = _knowledge_pack_from_payload(kp_payload)
    if knowledge_pack is None:
        knowledge_pack = run_consolidate(
            {**facts.to_dict(), "local": payload.get("local", []), "web": payload.get("web", [])}
        )
    style_text = payload.get("style_profile") or style_blocks()
    bundle = assemble_megaprompt(
        transcript_full=transcript,
        session_facts=facts,
        local_items=local_items,
        web_items=web_items,
        kp=knowledge_pack,
        style_profile_text=style_text,
        token_estimator=token_estimator,
    )
    return bundle


def default_token_estimator(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text.split()))


__all__ = [
    "run_extract",
    "run_rag_local",
    "run_rag_web",
    "run_consolidate",
    "run_megaprompt",
    "default_token_estimator",
]
