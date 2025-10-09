import pytest

from server.services import patients as patients_service


SAMPLE_PATIENTS = [
    {"id": "caroline", "displayName": "Caroline Durand", "email": "caroline@example.test"},
    {"id": "jeanb", "displayName": "Jean-Baptiste Lefèvre", "email": "jb@example.test"},
    {"id": "maelle", "displayName": "Maëlle D'Angelo", "email": "maelle@example.test"},
    {"id": "alex-dup", "displayName": "Alex Dupont"},
    {"id": "alex-ler", "displayName": "Alex Leroux"},
]


@pytest.fixture(autouse=True)
def patch_patient_listing(monkeypatch):
    monkeypatch.setattr(patients_service, "_list_patient_items", lambda: list(SAMPLE_PATIENTS))
    yield


def test_exact_match_single_candidate():
    matches = patients_service.find_patients_by_firstname("Caroline")
    assert matches == [
        {
            "id": "caroline",
            "display": "Caroline Durand",
            "email": "caroline@example.test",
        }
    ]


def test_hyphenated_firstname_matches():
    matches = patients_service.find_patients_by_firstname("Jean-Baptiste")
    assert matches == [
        {
            "id": "jeanb",
            "display": "Jean-Baptiste Lefèvre",
            "email": "jb@example.test",
        }
    ]


def test_accented_firstname_matches():
    matches = patients_service.find_patients_by_firstname("Maëlle")
    assert matches == [
        {
            "id": "maelle",
            "display": "Maëlle D'Angelo",
            "email": "maelle@example.test",
        }
    ]


def test_ambiguous_firstname_returns_multiple():
    matches = patients_service.find_patients_by_firstname("Alex")
    identifiers = {match["id"] for match in matches}
    assert identifiers == {"alex-dup", "alex-ler"}
    assert all(match.get("email") in {None, ""} for match in matches)
