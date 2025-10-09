"""Tests de validation pour les schémas de la Bibliothèque."""
from __future__ import annotations

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

pytest.importorskip("pydantic")

from schemas.library_schemas import SchemaValidationError, validate_plan_payload


def _build_payload() -> Dict[str, object]:
    return {
        "doc_id": "sha256:abc",
        "proposed_notions": [
            {
                "title": "Notion test",
                "summary": "Résumé critique.",
                "clinical_uses": ["usage"],
                "key_quotes": [
                    {
                        "text": "Citation",
                        "pages": [1],
                        "segment_ids": ["seg_000"],
                    }
                ],
                "limitations_risks": ["risque"],
                "tags": ["tag"],
                "evidence": {"type": "revue", "strength": "moderee"},
                "source_spans": ["seg_000"],
                "autosuggest_pre": True,
                "autosuggest_post": False,
                "priority": 0.8,
                "candidate_notion_id": "notion-test",
            }
        ],
    }


def test_validate_plan_payload_accepts_valid_structure() -> None:
    payload = _build_payload()
    validated = validate_plan_payload(payload)
    assert validated["doc_id"] == payload["doc_id"]
    assert validated["proposed_notions"][0]["priority"] == pytest.approx(0.8)


def test_validate_plan_payload_rejects_missing_candidate_id() -> None:
    payload = _build_payload()
    payload["proposed_notions"][0]["candidate_notion_id"] = ""
    with pytest.raises(SchemaValidationError):
        validate_plan_payload(payload)

