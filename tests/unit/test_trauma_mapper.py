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

from server.services.clinical_repo import ClinicalRepo  # noqa: E402
from server.services.trauma_mapper import TraumaMapper  # noqa: E402


def test_trauma_profile_fetch(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    repo.write_patient_file("adele", "somatic.json", {"resources": ["eau"]})
    repo.write_patient_file(
        "adele",
        "trauma_profile.json",
        {
            "core_patterns": [
                {
                    "name": "peur",
                    "description": "description",
                    "triggers": ["changement"],
                    "bodily_signals": ["ventre"],
                    "windows_of_feasibility": ["matin"],
                }
            ]
        },
    )

    mapper = TraumaMapper(repo=repo)
    payload = mapper.get_trauma_profile("adele")
    assert payload["profile"]["core_patterns"][0]["name"] == "peur"


def test_suggest_interpretations(tmp_path):
    repo = ClinicalRepo(instance_root=tmp_path)
    repo.write_patient_file(
        "adele",
        "trauma_profile.json",
        {
            "core_patterns": [
                {
                    "name": "bascule",
                    "description": "Anticipation du chaos",
                    "triggers": ["incertitude"],
                    "bodily_signals": ["ventre noué"],
                    "windows_of_feasibility": ["matin"],
                }
            ]
        },
    )
    repo.write_patient_file("adele", "somatic.json", {"resources": ["respiration"]})

    mapper = TraumaMapper(repo=repo)
    result = mapper.suggest_interpretations("adele", ["incertitude", "tension"])
    assert result["interpretations"]
    entry = result["interpretations"][0]
    assert entry["pattern"] == "bascule"
    assert entry["confidence"] == "faible"
