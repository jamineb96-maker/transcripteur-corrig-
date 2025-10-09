import importlib.util
import sys
from pathlib import Path


def _load_service_module(name: str):
    root = Path(__file__).resolve().parents[2]
    target = root / "server" / "services" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"server.services.{name}", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


pii_guard = _load_service_module("pii_guard")
is_pii_token = pii_guard.is_pii_token
scrub_pii = pii_guard.scrub_pii


def test_is_pii_token_detects_patient_names():
    meta = {"names": ["Garance"], "aliases": ["G."], "places": ["Lyon"]}
    assert is_pii_token("garance", meta)
    assert is_pii_token("GARANCE", meta)
    assert not is_pii_token("therapie", meta)


def test_scrub_pii_replaces_sensitive_items():
    meta = {"names": ["Garance"], "places": ["Lyon"]}
    redacted = scrub_pii("Garance était à Lyon pour la séance.", meta)
    assert "Garance" not in redacted
    assert "Lyon" not in redacted
    assert redacted.count("[REDACTED]") == 2
