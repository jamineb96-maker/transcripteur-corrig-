import os
import sys

import pytest


pytest.importorskip("flask")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.services import patients_repo


def test_scan_root_keeps_special_directory_names(tmp_path):
    root = tmp_path
    (root / "System Volume Information").mkdir()
    (root / "Thumbs.db").mkdir()
    (root / ".DS_Store").mkdir()
    (root / "desktop.ini").mkdir()
    (root / "_prefixed").mkdir()

    entries, diagnostics = patients_repo._scan_root(root)

    names = {entry.display_name for entry in entries}
    assert names == {"System Volume Information", "Thumbs.db"}

    assert diagnostics["total_entries"] == 5
    assert diagnostics["kept"] == 2
    dropped = {(item["name"], item["reason"]) for item in diagnostics["dropped"]}
    assert ("desktop.ini", "ignored_name") in dropped
    assert (".DS_Store", "ignored_prefix") in dropped
    assert ("_prefixed", "ignored_prefix") in dropped


def test_scan_root_descends_into_container_archives(tmp_path):
    root = tmp_path
    container = root / "Archive A-G"
    caroline = container / "Caroline"
    caroline.mkdir(parents=True)
    (caroline / "meta.json").write_text("{}", encoding="utf-8")

    entries, diagnostics = patients_repo._scan_root(root)

    assert {entry.display_name for entry in entries} == {"Caroline"}
    assert diagnostics["kept"] == 1
    assert diagnostics["total_entries"] == 1
