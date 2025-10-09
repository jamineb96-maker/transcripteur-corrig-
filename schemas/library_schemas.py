"""Schémas de validation pour les échanges JSON de la Bibliothèque."""
from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field, ValidationError, field_validator


class SchemaValidationError(ValueError):
    """Erreur levée lorsque la validation stricte échoue."""


ALLOWED_EVIDENCE_TYPES = {"revue", "essai", "cohorte", "qualitatif", "theorique"}
ALLOWED_STRENGTH = {"faible", "moderee", "forte"}


class EvidenceModel(BaseModel):
    type: str
    strength: str

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in ALLOWED_EVIDENCE_TYPES:
            raise ValueError(f"type de preuve invalide : {value}")
        return value

    @field_validator("strength")
    @classmethod
    def validate_strength(cls, value: str) -> str:
        if value not in ALLOWED_STRENGTH:
            raise ValueError(f"force de preuve invalide : {value}")
        return value


class QuoteModel(BaseModel):
    text: str
    pages: List[int] = Field(default_factory=list)
    segment_ids: List[str] = Field(default_factory=list)


class ProposedNotionModel(BaseModel):
    title: str
    summary: str
    clinical_uses: List[str]
    key_quotes: List[QuoteModel]
    limitations_risks: List[str]
    tags: List[str]
    evidence: EvidenceModel
    source_spans: List[str]
    autosuggest_pre: bool
    autosuggest_post: bool
    priority: float = Field(ge=0.0, le=1.0)
    candidate_notion_id: str

    @field_validator("clinical_uses", "limitations_risks", "tags", "source_spans")
    @classmethod
    def ensure_list(cls, value: List[str]) -> List[str]:
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("candidate_notion_id")
    @classmethod
    def validate_candidate(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("candidate_notion_id obligatoire")
        return value


class PlanPayloadModel(BaseModel):
    doc_id: str
    proposed_notions: List[ProposedNotionModel] = Field(default_factory=list)

    @field_validator("doc_id")
    @classmethod
    def validate_doc_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("doc_id manquant")
        return value


def validate_plan_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Valide la structure du plan de notions renvoyée par le LLM."""

    try:
        model = PlanPayloadModel.model_validate(payload)
    except ValidationError as exc:  # pragma: no cover - délègue aux tests ciblés
        raise SchemaValidationError(exc.errors()) from exc
    return model.model_dump()


__all__ = ["SchemaValidationError", "validate_plan_payload"]
