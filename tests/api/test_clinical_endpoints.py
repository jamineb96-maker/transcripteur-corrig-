import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("docx")

from server import create_app
from server.services.clinical_repo import ClinicalRepo
from server.services.clinical_service import ClinicalService
from server.services.trauma_mapper import TraumaMapper


@pytest.fixture()
def clinical_app(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    repo.write_patient_meta(
        "adele",
        {
            "slug": "adele",
            "display_name": "Adèle",
            "consent": {"research_use": False},
        },
    )
    repo.write_session_files(
        "adele",
        "2025-01-01_1",
        {
            "transcript.txt": "Bonjour",
            "plan.txt": "- [ ] objectif",
            "segments.json": {
                "session_date": "2025-01-01",
                "segments": [
                    {"topic": "fatigue", "text": "fatigue chronique"},
                ],
            },
        },
    )
    repo.write_patient_file(
        "adele",
        "trauma_profile.json",
        {
            "core_patterns": [
                {
                    "name": "bascule",
                    "description": "Anticipation",
                    "triggers": ["incertitude"],
                    "bodily_signals": ["ventre noué"],
                }
            ]
        },
    )
    repo.write_patient_file("adele", "somatic.json", {"resources": ["respiration"]})

    app = create_app()
    app.config.update({"TESTING": True})
    app.extensions["clinical_repo"] = repo
    app.extensions["clinical_service"] = ClinicalService(repo=repo)
    app.extensions["trauma_mapper"] = TraumaMapper(repo=repo)
    return app


def test_list_patients(clinical_app):
    with clinical_app.test_client() as client:
        response = client.get("/api/clinical/patients")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["success"] is True
        assert payload["data"]["patients"][0]["slug"] == "adele"


def test_overview_and_milestones(clinical_app):
    with clinical_app.test_client() as client:
        overview = client.get("/api/clinical/patient/adele/overview")
        assert overview.status_code == 200
        data = overview.get_json()["data"]
        assert data["meta"]["display_name"] == "Adèle"
        assert data["latest_plan"]["undone"] == ["- [ ] objectif"]

        milestone = client.post(
            "/api/clinical/patient/adele/milestones",
            data=json.dumps({"date": "2025-01-02", "note": "cap franchi"}),
            content_type="application/json",
        )
        assert milestone.status_code == 201
        payload = milestone.get_json()
        assert payload["data"]["milestones"]


def test_reindex_and_session_materials(clinical_app):
    with clinical_app.test_client() as client:
        reindex = client.post("/api/clinical/reindex/adele")
        assert reindex.status_code == 200
        index_payload = reindex.get_json()["data"]
        assert index_payload["patient"] == "adele"

        session = client.get("/api/clinical/patient/adele/session/2025-01-01_1/materials")
        assert session.status_code == 200
        files = session.get_json()["data"]
        assert files["segments"]["segments"][0]["topic"] == "fatigue"


def test_trauma_endpoints(clinical_app):
    with clinical_app.test_client() as client:
        trauma = client.get("/api/clinical/patient/adele/trauma")
        assert trauma.status_code == 200
        profile = trauma.get_json()["data"]
        assert profile["profile"]["core_patterns"][0]["name"] == "bascule"

        suggestions = client.post(
            "/api/clinical/patient/adele/trauma/interpretations",
            data=json.dumps({"signals": ["incertitude"]}),
            content_type="application/json",
        )
        assert suggestions.status_code == 200
        assert suggestions.get_json()["data"]["interpretations"]
