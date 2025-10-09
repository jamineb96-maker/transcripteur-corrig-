"""Migration utilitaire vers la structure de fichiers Library FS v2."""

from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:  # pragma: no cover - import facultatif selon l'environnement
    from server.utils.docid import doc_id_to_fs_path, ensure_dir, parse_doc_id
except ModuleNotFoundError:  # pragma: no cover - fallback pour les scripts isolés
    DOCID_PATH = Path(__file__).resolve().parents[1] / "server" / "utils" / "docid.py"
    SPEC = importlib.util.spec_from_file_location("server.utils.docid", DOCID_PATH)
    if SPEC is None or SPEC.loader is None:
        raise
    DOCID_MODULE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(DOCID_MODULE)
    doc_id_to_fs_path = DOCID_MODULE.doc_id_to_fs_path  # type: ignore[attr-defined]
    ensure_dir = DOCID_MODULE.ensure_dir  # type: ignore[attr-defined]
    parse_doc_id = DOCID_MODULE.parse_doc_id  # type: ignore[attr-defined]

LOGGER = logging.getLogger("library.migrate")


def _atomic_write_text(path: Path, payload: str) -> None:
    target = Path(path)
    ensure_dir(target.parent)
    tmp_dir = ensure_dir(target.parent / "tmp")
    tmp_path = tmp_dir / f"{target.name}.{uuid.uuid4().hex}.tmp"
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, target)


def _discover_legacy_dirs(extracted_root: Path) -> Iterable[Path]:
    for entry in sorted(extracted_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            parse_doc_id(entry.name)
        except ValueError:
            continue
        yield entry


def _update_manifest(target_dir: Path, doc_id: str, algo: str, digest: str) -> None:
    manifest_path = target_dir / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                manifest = {}
        except json.JSONDecodeError:
            manifest = {}
    manifest.setdefault("doc_id", doc_id)
    manifest.setdefault("algo", algo)
    manifest.setdefault("hash", digest)
    manifest.setdefault("migrated_at", datetime.now(timezone.utc).isoformat())
    _atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))


def migrate(library_root: Path, dry_run: bool = False, shard: bool = True) -> int:
    extracted_root = library_root / "extracted"
    if not extracted_root.exists():
        LOGGER.info("Aucun répertoire 'extracted' trouvé dans %s", library_root)
        return 0

    migrated = 0
    for legacy_dir in _discover_legacy_dirs(extracted_root):
        doc_id = legacy_dir.name
        try:
            algo, digest = parse_doc_id(doc_id)
        except ValueError:
            LOGGER.warning("Ignoré : nom de dossier incompatible %s", legacy_dir)
            continue
        target_dir = doc_id_to_fs_path(extracted_root, doc_id, shard=shard)
        if target_dir.exists():
            LOGGER.info("Cible déjà existante, sautée : %s", target_dir)
            continue
        LOGGER.info("Déplacement %s -> %s", legacy_dir, target_dir)
        if dry_run:
            migrated += 1
            continue
        ensure_dir(target_dir.parent)
        shutil.move(str(legacy_dir), str(target_dir))
        _update_manifest(target_dir, doc_id, algo, digest)
        migrated += 1
    LOGGER.info("Migration terminée : %s dossiers traités", migrated)
    return migrated


def _default_library_root() -> Path:
    env_root = os.getenv("LIBRARY_ROOT")
    if env_root:
        return Path(env_root)
    return Path("instance") / "library"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migre les extractions vers le format FS v2")
    parser.add_argument("--library-root", type=Path, default=None, help="Chemin racine de la bibliothèque")
    parser.add_argument("--flat", action="store_true", help="Désactive le sharding h0h1/h2h3 pour la cible")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Simule la migration sans modifier le disque")
    parser.add_argument("--apply", dest="dry_run", action="store_false", help="Applique la migration sur disque")
    parser.add_argument("--verbose", action="store_true", help="Active les logs détaillés")
    parser.set_defaults(dry_run=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")

    library_root = args.library_root or _default_library_root()
    library_root = library_root.expanduser().resolve()
    ensure_dir(library_root)
    LOGGER.info(
        "Migration déclenchée",
        extra={"library_root": str(library_root), "dry_run": args.dry_run, "shard": not args.flat},
    )
    migrate(library_root, dry_run=args.dry_run, shard=not args.flat)
    return 0


if __name__ == "__main__":  # pragma: no cover - exécution CLI
    raise SystemExit(main())
