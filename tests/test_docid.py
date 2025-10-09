import importlib.util
import os
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = BASE_DIR / "server" / "utils" / "docid.py"
spec = importlib.util.spec_from_file_location("server.utils.docid", MODULE_PATH)
assert spec and spec.loader, "Spec de module introuvable"
docid_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(docid_module)

parse_doc_id = docid_module.parse_doc_id
doc_id_to_fs_path = docid_module.doc_id_to_fs_path
legacy_fs_path = docid_module.legacy_fs_path
ensure_dir = docid_module.ensure_dir


@pytest.mark.parametrize(
    "doc_id,expected",
    [
        ("sha256:" + "a" * 64, ("sha256", "a" * 64)),
        ("md5:" + "b" * 32, ("md5", "b" * 32)),
    ],
)
def test_parse_doc_id_valid(doc_id, expected):
    assert parse_doc_id(doc_id) == expected


@pytest.mark.parametrize(
    "doc_id",
    [
        "",  # vide
        "sha256-" + "a" * 64,  # séparateur invalide
        "sha:xyz",  # hash non hex
        "sh:" + "a" * 32,  # algo trop court
        "sha256:" + "g" * 64,  # caractères hors hex
    ],
)
def test_parse_doc_id_invalid(doc_id):
    with pytest.raises(ValueError):
        parse_doc_id(doc_id)


def test_doc_id_to_fs_path_sharding(tmp_path: Path):
    doc_id = "sha256:" + "abcd" + "1" * 60
    fs_path = doc_id_to_fs_path(tmp_path, doc_id, shard=True)
    expected = tmp_path / "sha256" / "ab" / "cd" / ("abcd" + "1" * 60)
    assert fs_path == expected
    assert ":" not in str(fs_path)


def test_doc_id_to_fs_path_no_shard(tmp_path: Path):
    doc_id = "sha256:" + "1" * 64
    fs_path = doc_id_to_fs_path(tmp_path, doc_id, shard=False)
    assert fs_path == tmp_path / "sha256" / ("1" * 64)


@pytest.mark.parametrize("platform", ["posix", "nt"])
def test_legacy_fs_path(platform, monkeypatch, tmp_path: Path):
    doc_id = "sha256:" + "1" * 64

    if platform == "nt":
        stub_os = type("StubOS", (), {"name": "nt"})()
        monkeypatch.setattr(docid_module, "os", stub_os)
        expected = tmp_path / ("sha256_" + "1" * 64)
    else:
        monkeypatch.setattr(docid_module, "os", os)
        expected = tmp_path / ("sha256:" + "1" * 64)

    assert legacy_fs_path(tmp_path, doc_id) == expected


def test_ensure_dir_idempotent(tmp_path: Path):
    target = tmp_path / "nested" / "dir"
    ensure_dir(target)
    ensure_dir(target)
    assert target.exists()
    assert target.is_dir()
