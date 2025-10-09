#!/usr/bin/env python3
"""Contrôle rapide du serveur et de la parité patients FS/API."""

from __future__ import annotations

import compileall
import json
import os
import sys
from pathlib import Path
from typing import Iterable, Tuple


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _compile_server(root: Path) -> bool:
    target = root / "server"
    return compileall.compile_dir(str(target), quiet=1)


def _iter_env_roots(base_dir: Path) -> Iterable[Path]:
    raw = os.getenv("PATIENTS_DIR") or os.getenv("PATIENTS_ARCHIVES_DIRS", "")
    if not raw:
        return []
    for segment in raw.split(os.pathsep):
        candidate = segment.strip()
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        try:
            yield path.resolve()
        except OSError:
            continue


def _resolve_roots(base_dir: Path):
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))
    try:
        from server.services import patients_repo
    except Exception as exc:  # pragma: no cover - import error surfaced to caller
        print(f"Impossible d'importer patients_repo: {exc}", file=sys.stderr)
        return [], None

    env_roots = list(_iter_env_roots(base_dir))
    if env_roots:
        return env_roots, patients_repo

    try:
        roots = patients_repo._resolve_roots()  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Erreur lors de la résolution des racines patients: {exc}", file=sys.stderr)
        return [], patients_repo

    return roots, patients_repo


def _count_patients(roots: Iterable[Path], patients_repo) -> Tuple[int, int]:
    total_entries = 0
    kept_entries = 0
    prefixes = getattr(patients_repo, "IGNORE_PREFIXES", ())
    ignored_names = set(getattr(patients_repo, "IGNORE_NAMES", set()))

    for root in roots:
        try:
            children = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError as exc:
            print(f"Impossible de parcourir {root}: {exc}", file=sys.stderr)
            continue
        for child in children:
            if not child.is_dir():
                continue
            total_entries += 1
            name = child.name.strip()
            if any(name.startswith(prefix) for prefix in prefixes):
                continue
            if name in ignored_names:
                continue
            kept_entries += 1
    return total_entries, kept_entries


def _fetch_api_count(base_dir: Path) -> Tuple[int | None, dict]:
    try:
        from server import create_app
    except Exception as exc:  # pragma: no cover - surfaced to caller
        print(f"Impossible d'importer create_app: {exc}", file=sys.stderr)
        return None, {}

    app = create_app()
    app.config.update({"TESTING": True})

    with app.test_client() as client:
        response = client.get("/api/patients")
        if response.status_code != 200:
            print(
                f"Requête /api/patients échouée: {response.status_code} {response.status}",
                file=sys.stderr,
            )
            return None, {}
        payload = response.get_json(silent=True) or {}

    count = payload.get("count")
    if not isinstance(count, int):
        patients = payload.get("patients")
        if isinstance(patients, list):
            count = len(patients)
        else:
            count = None
    return count, payload


def main() -> int:
    project_root = _project_root()

    if not _compile_server(project_root):
        print("Échec de la compilation du dossier 'server'.", file=sys.stderr)
        return 1

    roots, repo = _resolve_roots(project_root)
    if repo is None:
        return 1

    total_entries, kept_entries = _count_patients(roots, repo)

    api_count, payload = _fetch_api_count(project_root)
    if api_count is None:
        return 1

    mismatch = kept_entries != api_count

    print(
        json.dumps(
            {
                "fs_total": total_entries,
                "fs_kept": kept_entries,
                "api_count": api_count,
                "patients_roots": [str(root) for root in roots],
                "api_payload_source": payload.get("source"),
                "status": "warning" if mismatch else "ok",
            },
            ensure_ascii=False,
        )
    )

    if mismatch:
        print(
            "Écart entre le système de fichiers et /api/patients.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
