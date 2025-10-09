"""Tests for the /api/post-session/upload-audio endpoint."""

from __future__ import annotations

import io
import os
import re
import sys
from typing import Generator

import pytest

pytest.importorskip("flask")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server import create_app
from server.blueprints import post_session


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Generator:
    upload_root = tmp_path_factory.mktemp("uploads")
    monkeypatch.setattr(post_session, "_UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(post_session, "_MAX_UPLOAD_BYTES", 50 * 1024 * 1024)
    app = create_app()
    app.config.update({"TESTING": True})
    with app.test_client() as client:
        yield client


def test_upload_audio_relpath_and_metadata(client) -> None:
    response = client.post(
        "/api/post-session/upload-audio",
        data={
            "file": (io.BytesIO(b"test audio"), "session.mp3"),
            "patient": "Jean Dupont",
            "duration": "123.45",
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True

    relpath = payload["relpath"]
    assert payload["file_id"] == relpath
    assert payload["path_rel"] == relpath

    # relpath should include the slugified patient and a timestamped directory.
    assert re.match(
        r"^jean-dupont/\d{4}-\d{2}-\d{2}_\d{6}/[0-9a-f]{32}_session\.mp3$",
        relpath,
    )

    # The file should be stored under the patched uploads directory.
    stored_path = post_session._UPLOAD_ROOT / relpath
    assert stored_path.exists()

    # Duration should be forwarded when provided.
    assert pytest.approx(123.45) == payload["duration"]
    assert payload["patient"] == "Jean Dupont"


def test_upload_audio_rejects_unsupported_extension(client) -> None:
    response = client.post(
        "/api/post-session/upload-audio",
        data={
            "file": (io.BytesIO(b"audio"), "session.flac"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload == {
        "ok": False,
        "message": "Format audio non supporté. Extensions autorisées: .mp3, .wav, .m4a.",
    }


def test_upload_audio_rejects_file_too_large(monkeypatch, client) -> None:
    monkeypatch.setattr(post_session, "_MAX_UPLOAD_BYTES", 10)
    response = client.post(
        "/api/post-session/upload-audio",
        data={
            "file": (io.BytesIO(b"0123456789ABC"), "session.mp3"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload == {
        "ok": False,
        "message": "Fichier trop volumineux (limite 0 Mo).",
    }

