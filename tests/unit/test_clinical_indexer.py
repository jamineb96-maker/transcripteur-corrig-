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

from datetime import date

from server.services.clinical_indexer import ClinicalIndexer
from server.services.clinical_repo import ClinicalRepo


def test_rebuild_index_collects_topics(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    repo.write_session_files(
        "adele",
        "2025-01-01_1",
        {
            "segments.json": {
                "session_date": "2025-01-01",
                "segments": [
                    {"topic": "fatigue", "text": "..."},
                    {"topic": "sommeil", "text": "..."},
                ],
            }
        },
    )
    repo.write_session_files(
        "adele",
        "2025-02-01_2",
        {
            "segments.json": {
                "segments": [
                    {"topic": "fatigue", "text": "autre"},
                ],
            }
        },
    )

    indexer = ClinicalIndexer(repo)
    payload = indexer.rebuild_index("adele")

    assert payload["patient"] == "adele"
    assert len(payload["sessions"]) == 2
    assert payload["sessions"][0]["topics"] == ["fatigue", "sommeil"]
    assert payload["sessions"][1]["topics"] == ["fatigue"]
    assert payload["last_updated"] == date.today().isoformat()
