import importlib.machinery
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_namespace(name: str, path: Path) -> None:
    module = sys.modules.get(name)
    if module is not None:
        return
    namespace = types.ModuleType(name)
    namespace.__path__ = [str(path)]  # type: ignore[attr-defined]
    namespace.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    sys.modules[name] = namespace


_ensure_namespace("server", ROOT / "server")
_ensure_namespace("server.services", ROOT / "server" / "services")
_ensure_namespace("server.util", ROOT / "server" / "util")

import pytest

from server.services.clinical_repo import ClinicalRepo, ClinicalRepoError


def test_repo_creates_structure(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    patient_meta = {"slug": "adele", "display_name": "Adèle"}
    repo.write_patient_meta("adele", patient_meta)

    stored = repo.read_patient_meta("adele")
    assert stored["display_name"] == "Adèle"
    assert (tmp_path / "records" / "adele" / "patient_meta.json").exists()


def test_session_roundtrip(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    payload = {
        "transcript.txt": "Bonjour", 
        "segments.json": {"segments": [{"topic": "test", "text": "bonjour"}]},
        "plan.txt": "- [ ] tâche",
    }
    repo.write_session_files("adele", "2025-01-01_1", payload)

    data = repo.read_session("adele", "2025-01-01_1")
    assert data["files"]["transcript.txt"] == "Bonjour"
    assert data["files"]["plan.txt"].startswith("- [ ]")
    assert data["files"]["segments.json"]["segments"][0]["topic"] == "test"


def test_list_patients_returns_known_entries(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    repo.write_patient_meta("adele", {"display_name": "Adèle"})
    repo.write_patient_meta("boris", {"display_name": "Boris"})

    patients = repo.list_patients()
    assert {patient["slug"] for patient in patients} == {"adele", "boris"}


def test_invalid_patient_file_raises(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    with pytest.raises(ClinicalRepoError):
        repo.read_patient_file("adele", "unknown.json")


def test_iterates_sessions_sorted(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    repo.write_session_files("adele", "2025-02-01_1", {"plan.txt": "x"})
    repo.write_session_files("adele", "2025-01-01_2", {"plan.txt": "x"})

    sessions = repo.list_sessions("adele")
    assert [handle.path for handle in sessions] == ["2025-01-01_2", "2025-02-01_1"]

