"""Helpers for locating patient-specific storage folders."""

from __future__ import annotations

from pathlib import Path

from ..util import slugify
from . import patients_repo


def _clean_subpath(name: str) -> Path:
    candidate = Path(name or "").parts
    safe_parts = []
    for part in candidate:
        if part in {"", "."}:
            continue
        if part == "..":
            raise ValueError("sub-directory cannot ascend")
        safe_parts.append(part)
    if not safe_parts:
        raise ValueError("sub-directory is required")
    return Path(*safe_parts)


def ensure_patient_subdir(slug: str, subdir: str) -> Path:
    """
    Retourne un Path vers le sous-dossier d'archives du patient, en le créant si besoin.
    Compatible avec l'ancien modèle (ARCHIVES_ROOT) et le nouveau (resolve_patient_archive).
    """
    patient_slug = slugify(slug or "unknown")

    base = None
    # Nouveau monde : fonction de résolution fournie par patients_repo
    if hasattr(patients_repo, "resolve_patient_archive"):
        resolved = patients_repo.resolve_patient_archive(patient_slug)
        base = Path(resolved)
    else:
        # Ancien monde ou fallback
        root = getattr(patients_repo, "ARCHIVES_ROOT", None)
        if root is None:
            root = Path(__file__).resolve().parents[2] / "instance" / "archives"
        else:
            root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        base = root / patient_slug

    base.mkdir(parents=True, exist_ok=True)

    # Normaliser le sous-chemin demandé
    safe_sub = _clean_subpath(subdir or "")
    target = base / safe_sub
    target.mkdir(parents=True, exist_ok=True)
    return target


__all__ = ["ensure_patient_subdir"]
