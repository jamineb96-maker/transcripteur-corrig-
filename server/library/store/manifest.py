"""Gestion des manifestes d'extraction pour la bibliothèque clinique."""

from __future__ import annotations

import json
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping

from server.utils.docid import doc_id_to_fs_path, ensure_dir, legacy_fs_path, parse_doc_id
from server.utils.fs_atomic import atomic_write

LOGGER = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"


def resolve_extraction_dir(root: Path, doc_id: str, *, shard: bool, feature_v2: bool) -> Path:
    """Retourne le dossier d'extraction canonique pour ``doc_id``."""

    if feature_v2:
        target_dir = doc_id_to_fs_path(root, doc_id, shard=shard)
    else:
        target_dir = legacy_fs_path(root, doc_id)
    return ensure_dir(target_dir)


def manifest_path(extraction_dir: Path) -> Path:
    return extraction_dir / MANIFEST_FILENAME


def _normalise_manifest(data: Mapping[str, Any] | None) -> Dict[str, Any]:
    manifest = dict(data or {})
    manifest.setdefault("prefill", {})
    manifest.setdefault("user_overrides", {})
    manifest.setdefault("history", [])
    return manifest


def load_manifest(extraction_dir: Path) -> Dict[str, Any]:
    """Charge ``manifest.json`` si présent, sinon retourne un dict vide."""

    path = manifest_path(extraction_dir)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Manifest illisible", extra={"path": str(path), "error": str(exc)})
        return {}
    if not isinstance(payload, dict):
        return {}
    return _normalise_manifest(payload)


def _write_manifest(extraction_dir: Path, manifest: Mapping[str, Any]) -> Dict[str, Any]:
    ensure_dir(extraction_dir)
    now = datetime.now(timezone.utc).isoformat()
    payload = dict(manifest)
    payload.setdefault("created_at", now)
    payload["updated_at"] = now
    normalised = _normalise_manifest(payload)

    def _writer(tmp_path: Path) -> None:
        tmp_path.write_text(json.dumps(normalised, ensure_ascii=False, indent=2), encoding="utf-8")

    atomic_write(manifest_path(extraction_dir), _writer)
    return normalised


def ensure_manifest(
    doc_id: str,
    extraction_dir: Path,
    *,
    source_filename: str | None,
    file_size_bytes: int | None,
) -> Dict[str, Any]:
    """Garantit la présence d'un manifeste minimal pour ``doc_id``."""

    existing = load_manifest(extraction_dir)
    algo, digest = parse_doc_id(doc_id)
    if existing:
        manifest = dict(existing)
        manifest.setdefault("doc_id", doc_id)
        manifest.setdefault("algo", algo)
        manifest.setdefault("hash", digest)
        if source_filename is not None:
            manifest["source_filename"] = source_filename
        if file_size_bytes is not None:
            manifest["bytes"] = file_size_bytes
        return _write_manifest(extraction_dir, manifest)

    manifest = {
        "doc_id": doc_id,
        "algo": algo,
        "hash": digest,
        "source_filename": source_filename,
        "bytes": file_size_bytes,
        "language": None,
        "prefill": {},
        "user_overrides": {},
        "history": [],
    }
    return _write_manifest(extraction_dir, manifest)


def update_manifest(extraction_dir: Path, updates: Mapping[str, Any]) -> Dict[str, Any]:
    """Fusionne ``updates`` dans le manifeste et le ré-écrit."""

    manifest = load_manifest(extraction_dir)
    manifest.update(dict(updates))
    return _write_manifest(extraction_dir, manifest)


def append_manifest_history(extraction_dir: Path, entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Ajoute une entrée horodatée dans ``manifest.history``."""

    manifest = load_manifest(extraction_dir)
    history = list(manifest.get("history") or [])
    payload = dict(entry)
    payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    history.append(payload)
    manifest["history"] = history
    return _write_manifest(extraction_dir, manifest)


__all__ = [
    "ensure_manifest",
    "load_manifest",
    "manifest_path",
    "resolve_extraction_dir",
    "append_manifest_history",
    "update_manifest",
]

