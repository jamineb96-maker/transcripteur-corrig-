"""Pydantic schema and normalisation helpers for the LLM generated plan."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA_VERSION = "1.0.0"

RESOURCE_TYPES = [
    "Article",
    "Guide",
    "Revue systématique",
    "Méta-analyse",
    "Essai randomisé",
    "Observationnelle",
    "Cas clinique",
    "Qualitatif",
    "Chapitre",
    "Rapport",
    "Site web",
    "Livre",
]

EVIDENCE_LEVELS = ["Très élevé", "Élevé", "Modéré", "Faible", "Théorique"]
EVIDENCE_STRENGTH = ["Très élevé", "Élevé", "Modéré", "Faible", "Théorique"]
EVIDENCE_TYPES = [
    "Essai randomisé",
    "Observationnelle",
    "Cas clinique",
    "Qualitatif",
    "Revue systématique",
    "Méta-analyse",
    "Guide",
    "Article",
]

NORMALIZE_MAP = {
    "moderate": "Modéré",
    "modéré": "Modéré",
    "modere": "Modéré",
    "guideline": "Guide",
    "guide": "Guide",
    "meta analyse": "Méta-analyse",
    "meta-analyse": "Méta-analyse",
    "metaanalyse": "Méta-analyse",
    "trial": "Essai randomisé",
    "randomized trial": "Essai randomisé",
    "randomized controlled trial": "Essai randomisé",
    "case report": "Cas clinique",
    "qualitative": "Qualitatif",
    "web": "Site web",
    "site": "Site web",
}

_NORMALIZE_INDEX = {key.casefold(): value for key, value in NORMALIZE_MAP.items()}


def _normalize_choice(value: str, choices: Iterable[str]) -> str:
    cleaned = value.strip()
    if not cleaned:
        return cleaned
    lowered = cleaned.casefold()
    if lowered in _NORMALIZE_INDEX:
        return _NORMALIZE_INDEX[lowered]
    for choice in choices:
        if lowered == choice.casefold():
            return choice
    return cleaned


def _normalize_list(values: Iterable[object]) -> List[str]:
    normalised: List[str] = []
    for item in values or []:
        text = str(item).strip()
        if text:
            normalised.append(text)
    return normalised


class Evidence(BaseModel):
    type: str = Field(default="Guide")
    strength: str = Field(default="Modéré")

    model_config = ConfigDict(extra="allow")

    @field_validator("type")
    @classmethod
    def normalize_type(cls, value: str) -> str:
        return _normalize_choice(value, EVIDENCE_TYPES)

    @field_validator("strength")
    @classmethod
    def normalize_strength(cls, value: str) -> str:
        return _normalize_choice(value, EVIDENCE_STRENGTH)


class Quote(BaseModel):
    text: str
    pages: List[int] = Field(default_factory=list)
    segment_ids: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("pages", mode="before")
    @classmethod
    def normalise_pages(cls, value):  # type: ignore[override]
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            integers = []
            for item in value:
                try:
                    integers.append(int(item))
                except (TypeError, ValueError):
                    continue
            return integers
        return []

    @field_validator("segment_ids", mode="before")
    @classmethod
    def normalise_segments(cls, value):  # type: ignore[override]
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []


class ProposedNotion(BaseModel):
    candidate_notion_id: str
    title: str
    summary: str
    clinical_uses: List[str] = Field(default_factory=list)
    key_quotes: List[Quote] = Field(default_factory=list)
    limitations_risks: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    evidence: Evidence = Field(default_factory=Evidence)
    source_spans: List[str] = Field(default_factory=list)
    autosuggest_pre: bool = False
    autosuggest_post: bool = False
    priority: float = Field(default=0.0, ge=0.0, le=1.0)

    model_config = ConfigDict(extra="allow")

    @field_validator("candidate_notion_id")
    @classmethod
    def normalize_candidate(cls, value: str) -> str:
        return value.strip()

    @field_validator("title", "summary")
    @classmethod
    def normalize_text_fields(cls, value: str) -> str:
        return value.strip()

    @field_validator(
        "clinical_uses",
        "limitations_risks",
        "tags",
        "source_spans",
        mode="before",
    )
    @classmethod
    def normalize_lists(cls, value):  # type: ignore[override]
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return _normalize_list(value)
        if isinstance(value, str):
            return _normalize_list(value.split(","))
        return []


class PlanV1(BaseModel):
    schema_version: str = Field(default=SCHEMA_VERSION)
    doc_id: str
    resource_type: Optional[str] = None
    evidence_level: Optional[str] = None
    domains: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    proposed_notions: List[ProposedNotion] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")

    @field_validator("schema_version")
    @classmethod
    def enforce_version(cls, value: str) -> str:
        return SCHEMA_VERSION

    @field_validator("doc_id")
    @classmethod
    def normalize_doc_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("resource_type")
    @classmethod
    def normalize_resource_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_choice(value, RESOURCE_TYPES)

    @field_validator("evidence_level")
    @classmethod
    def normalize_evidence_level(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_choice(value, EVIDENCE_LEVELS)

    @field_validator("domains", "keywords", mode="before")
    @classmethod
    def normalize_string_lists(cls, value):  # type: ignore[override]
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return _normalize_list(value)
        if isinstance(value, str):
            return _normalize_list(value.split(","))
        return []

    @field_validator("notes")
    @classmethod
    def normalize_notes(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


def normalize_plan_payload(payload: Dict[str, object], *, doc_id: Optional[str] = None) -> Dict[str, object]:
    """Prepare the raw payload before validation."""

    data = dict(payload or {})
    if doc_id and not data.get("doc_id"):
        data["doc_id"] = doc_id
    if "proposed_notions" not in data or data["proposed_notions"] is None:
        data["proposed_notions"] = []
    if "domains" not in data or data["domains"] is None:
        data["domains"] = []
    if "keywords" not in data or data["keywords"] is None:
        data["keywords"] = []
    if "notes" in data and isinstance(data["notes"], str):
        data["notes"] = data["notes"].strip()
    if "resource_type" in data and isinstance(data["resource_type"], str):
        data["resource_type"] = _normalize_choice(data["resource_type"], RESOURCE_TYPES)
    if "evidence_level" in data and isinstance(data["evidence_level"], str):
        data["evidence_level"] = _normalize_choice(data["evidence_level"], EVIDENCE_LEVELS)
    notions = data.get("proposed_notions")
    if isinstance(notions, list):
        normalised_notions = []
        for notion in notions:
            if not isinstance(notion, dict):
                continue
            item = dict(notion)
            if "evidence" in item and isinstance(item["evidence"], dict):
                evidence = item["evidence"]
                if "type" in evidence and isinstance(evidence["type"], str):
                    evidence["type"] = _normalize_choice(evidence["type"], EVIDENCE_TYPES)
                if "strength" in evidence and isinstance(evidence["strength"], str):
                    evidence["strength"] = _normalize_choice(evidence["strength"], EVIDENCE_STRENGTH)
            normalised_notions.append(item)
        data["proposed_notions"] = normalised_notions
    return data


def get_plan_json_schema() -> Dict[str, object]:
    """Expose the JSON schema used in prompts and diagnostics."""

    return PlanV1.model_json_schema()


__all__ = [
    "PlanV1",
    "SCHEMA_VERSION",
    "RESOURCE_TYPES",
    "EVIDENCE_LEVELS",
    "EVIDENCE_TYPES",
    "NORMALIZE_MAP",
    "normalize_plan_payload",
    "get_plan_json_schema",
    "ValidationError",
]
