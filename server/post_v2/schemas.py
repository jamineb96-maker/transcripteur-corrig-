"""Typed data schemas for post-session v2 pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Callable, Dict, List, Optional


@dataclass
class SessionFacts:
    """Signals extracted from a therapy session transcript."""

    patient: str
    date: str
    themes: List[str] = field(default_factory=list)
    meds: List[Dict[str, object]] = field(default_factory=list)
    context: Dict[str, Optional[str]] = field(default_factory=dict)
    asks: List[str] = field(default_factory=list)
    quotes: List[str] = field(default_factory=list)
    flags: Dict[str, List[str]] = field(default_factory=lambda: {"risques": [], "incertitudes": []})

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        # ensure context keys exist
        context_defaults = {"travail": None, "famille": None, "argent": None, "logement": None}
        payload["context"] = {**context_defaults, **payload.get("context", {})}
        flags = payload.get("flags", {})
        payload["flags"] = {
            "risques": list(flags.get("risques", [])),
            "incertitudes": list(flags.get("incertitudes", [])),
        }
        return payload


@dataclass
class EvidenceItemLocal:
    """Evidence chunk retrieved from the local research library."""

    title: str
    doc_id: str
    pages: str
    extract: str
    evidence_level: str
    year: int
    domains: List[str]
    chunk_id: str
    score: float

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class EvidenceItemWeb:
    """Evidence fetched from the web allow-listed sources."""

    title: str
    author: str
    outlet: str
    date: str
    url: str
    quote: str
    claim: str
    reliability_tag: str

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class CitationRef:
    type: str
    ref: str
    pages: Optional[str]
    url: Optional[str]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class KnowledgeAxis:
    label: str
    rationale: str
    phrases_appui: List[str]
    citations: List[CitationRef]

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "rationale": self.rationale,
            "phrases_appui": list(self.phrases_appui),
            "citations": [citation.to_dict() for citation in self.citations],
        }


@dataclass
class CitationCandidate:
    short: str
    source: str
    pages: Optional[str]
    url: Optional[str]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class KnowledgePack:
    axes: List[KnowledgeAxis]
    citations_candidates: List[CitationCandidate]
    hypotheses_situees: List[str]
    pistes_regulation: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "axes": [axis.to_dict() for axis in self.axes],
            "citations_candidates": [candidate.to_dict() for candidate in self.citations_candidates],
            "hypotheses_situees": list(self.hypotheses_situees),
            "pistes_regulation": list(self.pistes_regulation),
        }


@dataclass
class MegaPromptBundle:
    token_estimate: int
    system_block: str
    context_block: str
    evidence_block: str
    task_block: str
    qa_checks_block: str
    fail_safes_block: str
    style_profile_block: str
    full_prompt: str
    token_warning: bool = False

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


TokenEstimator = Callable[[str], int]

__all__ = [
    "SessionFacts",
    "EvidenceItemLocal",
    "EvidenceItemWeb",
    "KnowledgeAxis",
    "CitationRef",
    "CitationCandidate",
    "KnowledgePack",
    "MegaPromptBundle",
    "TokenEstimator",
]
