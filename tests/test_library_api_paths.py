import io
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

sys.path.insert(0, os.path.abspath(Path(__file__).resolve().parents[1]))

from server import create_app  # type: ignore  # noqa: E402
from server.blueprints import library as library_bp  # type: ignore  # noqa: E402
from server.utils.docid import doc_id_to_fs_path  # type: ignore  # noqa: E402

MINIMAL_PDF = (
    b"%PDF-1.1\n"
    b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
    b"2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj\n"
    b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
    b"4 0 obj<< /Length 44 >>stream\n"
    b"BT /F1 24 Tf 72 120 Td (Hello) Tj ET\n"
    b"endstream\n"
    b"endobj\n"
    b"5 0 obj<< /Type /Font /Subtype /Type1 /Name /F1 /BaseFont /Helvetica >>endobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000010 00000 n \n0000000061 00000 n \n0000000126 00000 n \n0000000225 00000 n \n0000000329 00000 n \n"
    b"trailer<< /Size 6 /Root 1 0 R >>\n"
    b"startxref\n381\n%%EOF\n"
)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    library_root = tmp_path / "library"
    monkeypatch.setenv("LIBRARY_ROOT", str(library_root))
    monkeypatch.setenv("FEATURE_LIBRARY_FS_V2", "1")
    monkeypatch.setenv("LIBRARY_FS_SHARDING", "1")
    monkeypatch.setenv("FLASK_ENV", "testing")

    class ImmediateExecutor:
        def submit(self, func, *args, **kwargs):
            func(*args, **kwargs)

            class _Result:
                def result(self):
                    return None

            return _Result()

    monkeypatch.setattr(library_bp, "EXECUTOR", ImmediateExecutor())
    monkeypatch.setattr(
        library_bp,
        "extract_text",
        lambda *_args, **_kwargs: [{"page": 1, "text": "hello", "has_ocr": False}],
    )
    monkeypatch.setattr(
        library_bp,
        "segment_pages",
        lambda _pages, **_kwargs: [{"segment_id": "seg_001", "pages": [1, 1], "text": "hello", "token_estimate": 1}],
    )
    monkeypatch.setattr(library_bp, "index_segments", lambda *_args, **_kwargs: None)

    library_bp.TASK_STATE.clear()

    app = create_app()
    app.config.update(TESTING=True)
    yield app


def test_upload_cycle_sets_status_done(app):
    client = app.test_client()
    data = {
        "file": (io.BytesIO(MINIMAL_PDF), "sample.pdf"),
        "title": "Sample",
    }

    response = client.post("/library/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    doc_id = payload["doc_id"]
    assert doc_id.startswith("sha256:")
    assert payload["status"]["status"] == "done"

    status_response = client.get(f"/library/extract/{doc_id}/status")
    assert status_response.status_code == 200
    assert status_response.get_json()["status"]["status"] == "done"


def test_status_invalid_doc_id_returns_400(app):
    client = app.test_client()
    response = client.get("/library/extract/not-a-doc/status")
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_doc_id"


def test_upload_checkbox_persists_autosuggest_defaults(app):
    client = app.test_client()
    data = {
        "file": (io.BytesIO(MINIMAL_PDF), "sample.pdf"),
        "title": "Sample",
        "autosuggest_pre_default": "on",
        "autosuggest_post_default": "1",
    }

    response = client.post("/library/upload", data=data, content_type="multipart/form-data")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["metadata"]["autosuggest_pre_default"] is True
    assert payload["metadata"]["autosuggest_post_default"] is True

    doc_id = payload["doc_id"]
    extracted_root = Path(app.config["LIBRARY_EXTRACTED_ROOT"])
    manifest_dir = doc_id_to_fs_path(extracted_root, doc_id, shard=True)
    manifest_path = manifest_dir / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["options"]["autosuggest_pre_default"] is True
    assert manifest["options"]["autosuggest_post_default"] is True
    assert manifest["metadata_form"]["autosuggest_pre_default"] is True
    assert manifest["metadata_form"]["autosuggest_post_default"] is True
