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

from server.services.clinical_service import ClinicalService
from server.services.clinical_repo import ClinicalRepo


def _make_service(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    service = ClinicalService(repo=repo)
    return service, repo


def test_overview_includes_latest_plan(tmp_path):
    service, repo = _make_service(tmp_path)
    repo.write_patient_meta("adele", {"display_name": "Adèle"})
    repo.write_session_files("adele", "2025-01-01_1", {"plan.txt": "- [ ] fermer dossier"})

    overview = service.get_patient_overview("adele")
    assert overview["meta"]["display_name"] == "Adèle"
    assert overview["latest_plan"]["undone"] == ["- [ ] fermer dossier"]


def test_find_topics_returns_matches(tmp_path):
    service, repo = _make_service(tmp_path)
    repo.write_session_files(
        "adele",
        "2025-01-01_1",
        {"segments.json": {"segments": [{"topic": "fatigue", "text": "fatigue intense"}]}},
    )

    results = service.find_topics("adele", "fatigue")
    assert results["matches"]
    assert results["matches"][0]["topic"] == "fatigue"
