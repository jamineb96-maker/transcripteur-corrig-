import importlib
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server import create_app

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DATA_PATH = INSTANCE_DIR / "patients.json"


class FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.current = start

    def time(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


@pytest.fixture()
def app_factory(monkeypatch):
    def _create_app(env: dict[str, str] | None = None, setup=None):
        monkeypatch.delenv("DEMO_PATIENTS", raising=False)
        env = env or {}
        for key, value in env.items():
            monkeypatch.setenv(key, value)

        INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            INSTANCE_DATA_PATH.unlink()
        except FileNotFoundError:
            pass

        from server.services import patients_repo as repo_module
        importlib.reload(repo_module)
        repo_module.invalidate_cache()

        if setup is not None:
            setup(repo_module)

        from server.services import patients as patients_module
        importlib.reload(patients_module)

        app = create_app()
        app.config.update({"TESTING": True})
        return app

    return _create_app


def _make_patient(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def test_patients_endpoint_meta_creation_and_cache_refresh(tmp_path, app_factory, monkeypatch):
    root = tmp_path / "archives"
    _make_patient(root, "Alice")
    _make_patient(root, "Bob")

    clock = FakeClock()

    def _setup(repo_module):
        monkeypatch.setattr(repo_module, "time", clock)

    app = app_factory({"PATIENTS_DIR": str(root)}, setup=_setup)

    with app.test_client() as client:
        response = client.get("/api/patients")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["ok"] is True
        assert payload["success"] is True
        assert payload["dir_abs"] == str(root.resolve())
        assert payload["source"] == "archives"
        assert payload["count"] == 2
        assert all((root / name / "meta.json").exists() for name in ("Alice", "Bob"))
        assert all("path" in item for item in payload["items"])

        clock.advance(10)
        _make_patient(root, "Charlie")

        cached = client.get("/api/patients")
        cached_payload = cached.get_json()
        assert cached_payload["count"] == 2, "Cache TTL 60s doit conserver l'état"

        refreshed = client.get("/api/patients?refresh=1")
        refreshed_payload = refreshed.get_json()
        assert refreshed_payload["count"] == 3
        assert any(item["id"] == "charlie" for item in refreshed_payload["items"])
        assert (root / "Charlie" / "meta.json").exists(), "meta.json doit être créé automatiquement"

        clock.advance(61)
        _make_patient(root, "Dana")

        expired = client.get("/api/patients")
        expired_payload = expired.get_json()
        assert expired_payload["count"] == 4
        ids = [item["id"] for item in expired_payload["items"]]
        assert ids == sorted(ids), "Les identifiants doivent être triés alphabétiquement"


def test_demo_flag_returns_seed(app_factory):
    app = app_factory({"DEMO_PATIENTS": "1"})

    with app.test_client() as client:
        response = client.get("/api/patients")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["success"] is True
        names = {item["displayName"] for item in payload["patients"]}
        assert names == {"Caroline", "Martin", "Jean"}

        health = client.get("/api/health")
        assert health.status_code == 200
        health_payload = health.get_json()
        data = health_payload.get("data", health_payload)
        assert data["patients_source"] == "demo"
        assert isinstance(data["patients_dir_abs"], str)
        assert data["openai_configured"] is False


def test_patients_endpoint_supports_relative_patients_dir(tmp_path, app_factory):
    root = tmp_path / "relative" / "archives"
    _make_patient(root, "Emma")
    _make_patient(root, "Noah")

    relative_path = os.path.relpath(root, BASE_DIR)
    app = app_factory({"PATIENTS_DIR": relative_path})

    with app.test_client() as client:
        response = client.get("/api/patients")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["ok"] is True
        assert payload["success"] is True
        assert payload["dir_abs"] == str(root.resolve())
        assert payload["count"] == 2
        returned = {item["displayName"] for item in payload["items"]}
        assert returned == {"Emma", "Noah"}


def test_patients_endpoint_merges_multiple_roots_and_nested_archives(tmp_path, app_factory):
    root_a = tmp_path / "primary"
    root_b = tmp_path / "secondary"
    root_c = tmp_path / "nested"

    _make_patient(root_a, "Alice")
    _make_patient(root_b, "Eve")
    _make_patient(root_c / "Archive A-G", "Caroline")

    env = {
        "PATIENTS_DIR": os.pathsep.join([str(root_a), str(root_b)]),
        "PATIENTS_ARCHIVES_DIRS": str(root_c),
    }
    app = app_factory(env)

    with app.test_client() as client:
        response = client.get("/api/patients")
        assert response.status_code == 200
        payload = response.get_json()

    resolved_roots = {str(path.resolve()) for path in (root_a, root_b, root_c)}
    assert payload["count"] == 3
    assert payload["dir_abs"] == str(root_a.resolve())
    assert set(payload.get("roots", [])) == resolved_roots
    returned = {item["displayName"] for item in payload["items"]}
    assert returned == {"Alice", "Caroline", "Eve"}
