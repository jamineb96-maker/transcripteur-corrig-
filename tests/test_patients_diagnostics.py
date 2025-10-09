import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

pytest.importorskip("flask")

from server import create_app
from server.services import patients_repo


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("PATIENTS_DIR", raising=False)
    monkeypatch.delenv("PATIENTS_ARCHIVES_DIRS", raising=False)
    patients_repo.invalidate_cache()
    yield
    patients_repo.invalidate_cache()


def _make_patient(root: Path, name: str, display: str | None = None) -> None:
    patient_dir = root / name
    patient_dir.mkdir(parents=True, exist_ok=True)
    if display and display != name:
        (patient_dir / "meta.json").write_text(
            json.dumps({"display_name": display}, ensure_ascii=False),
            encoding="utf-8",
        )


def test_cache_diagnostics_reflects_filesystem(tmp_path, monkeypatch):
    root = tmp_path / "patients"
    root.mkdir()
    _make_patient(root, "Alice")
    _make_patient(root, "Bob", display="Bobby B")
    (root / ".ignored").mkdir()
    (root / "_system").mkdir()
    (root / "System Volume Information").mkdir()
    (root / "Thumbs.db").mkdir()

    monkeypatch.setenv("PATIENTS_DIR", str(root))

    diagnostics = patients_repo.cache_diagnostics()

    assert diagnostics["dir_abs"] == str(root.resolve())
    assert diagnostics["total_entries"] == 6
    assert diagnostics["kept"] == 4
    assert isinstance(diagnostics["dropped"], list)
    assert len(diagnostics["dropped"]) == 2
    reasons = {item["reason"] for item in diagnostics["dropped"]}
    assert reasons == {"ignored_prefix"}
codex/enrich-diagnostics-payload-with-items
    assert diagnostics["sample"] == ["Alice", "Bobby B"]
    assert diagnostics["items"] == [
        {"slug": "alice", "name": "Alice"},
        {"slug": "bobby-b", "name": "Bobby B"},
=======
    assert diagnostics["sample"] == [
        "Alice",
        "Bobby B",
        "System Volume Information",
        "Thumbs.db",
main
    ]

    # TTL: adding a new folder should not immediately change diagnostics
    _make_patient(root, "Charlie")
    diagnostics_cached = patients_repo.cache_diagnostics()
    assert diagnostics_cached["kept"] == diagnostics["kept"]
    assert diagnostics_cached["dropped"] == diagnostics["dropped"]


def test_patients_diagnostics_endpoint_returns_aggregated_payload(tmp_path, monkeypatch):
    root = tmp_path / "archives"
    root.mkdir()
    _make_patient(root, "Anna")
    _make_patient(root, "Beatrice")
    (root / "_Ignore").mkdir()
    (root / "System Volume Information").mkdir()
    (root / "Thumbs.db").mkdir()

    monkeypatch.setenv("PATIENTS_DIR", str(root))

    app = create_app()
    app.config.update({"TESTING": True})

    with app.test_client() as client:
        response = client.get("/api/patients/diagnostics")
        assert response.status_code == 200
        payload = response.get_json()

    assert payload["ok"] is True
    assert payload["dir_abs"] == str(root.resolve())
    assert payload["total_entries"] == 5
    assert payload["kept"] == 4
    assert isinstance(payload["dropped"], list)
    assert len(payload["dropped"]) == 1
    assert payload["sample"] == [
        "Anna",
        "Beatrice",
        "System Volume Information",
        "Thumbs.db",
    ]
    assert payload["source"] == "archives"
    assert payload["items"] == [
        {"slug": "anna", "name": "Anna"},
        {"slug": "beatrice", "name": "Beatrice"},
    ]
