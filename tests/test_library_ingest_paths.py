import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(Path(__file__).resolve().parents[1]))

pytest.importorskip("pdfminer.high_level")

from modules.library_ingest import InvalidDocumentId, persist_extraction
from server.utils.docid import doc_id_to_fs_path


def test_persist_extraction_creates_sharded_layout(tmp_path: Path):
    doc_id = "sha256:" + "1" * 64
    pages = [
        {"page": 1, "text": "hello", "has_ocr": False},
        {"page": 2, "text": "world", "has_ocr": True},
    ]
    segments = [
        {"segment_id": "seg_001", "pages": [1, 2], "text": "hello world", "token_estimate": 2}
    ]

    target_dir = persist_extraction(
        doc_id,
        pages,
        segments,
        extracted_root=tmp_path,
        source_filename="upload.pdf",
        file_size_bytes=2048,
        tags=["test"],
        options={"autosuggest": True},
    )

    expected_dir = doc_id_to_fs_path(tmp_path, doc_id, shard=True)
    assert target_dir == expected_dir
    assert target_dir.exists()

    pages_path = target_dir / "pages" / "pages.jsonl"
    segments_path = target_dir / "segments.jsonl"
    manifest_path = target_dir / "manifest.json"

    assert pages_path.exists()
    assert segments_path.exists()
    assert manifest_path.exists()

    pages_lines = pages_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(pages_lines) == len(pages)

    segments_lines = segments_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(segments_lines) == len(segments)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["doc_id"] == doc_id
    assert manifest["algo"] == "sha256"
    assert manifest["hash"] == "1" * 64
    assert manifest["source_filename"] == "upload.pdf"
    assert manifest["bytes"] == 2048
    assert manifest["tags"] == ["test"]
    assert manifest["options"] == {"autosuggest": True}
    assert manifest["pages"] == len(pages)
    assert manifest["segments"] == len(segments)


def test_persist_extraction_invalid_docid(tmp_path: Path):
    with pytest.raises(InvalidDocumentId):
        persist_extraction("not-a-doc", [], [], extracted_root=tmp_path)
