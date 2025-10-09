import importlib.util
import json
from pathlib import Path

DOCID_MODULE_PATH = Path(__file__).resolve().parents[1] / "server" / "utils" / "docid.py"
docid_spec = importlib.util.spec_from_file_location("server.utils.docid", DOCID_MODULE_PATH)
assert docid_spec and docid_spec.loader
docid_module = importlib.util.module_from_spec(docid_spec)
docid_spec.loader.exec_module(docid_module)
doc_id_to_fs_path = docid_module.doc_id_to_fs_path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_library_fs_v2.py"
spec = importlib.util.spec_from_file_location("migrate_library_fs_v2", MODULE_PATH)
assert spec and spec.loader
migration_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration_module)


def test_migrate_moves_legacy_directories(tmp_path: Path):
    library_root = tmp_path / "library"
    doc_id = "sha256:" + "1" * 64
    legacy_dir = library_root / "extracted" / doc_id
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (legacy_dir / "segments.jsonl").write_text("", encoding="utf-8")

    migrated = migration_module.migrate(library_root, dry_run=False, shard=True)
    assert migrated == 1

    target_dir = doc_id_to_fs_path(library_root / "extracted", doc_id, shard=True)
    assert target_dir.exists()
    assert not legacy_dir.exists()

    manifest = json.loads((target_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["doc_id"] == doc_id
    assert manifest["algo"] == "sha256"
    assert manifest["hash"] == "1" * 64
    assert "migrated_at" in manifest
