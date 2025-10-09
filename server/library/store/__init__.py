"""Sous-package utilitaires pour la persistance de la bibliothèque."""

from .manifest import (
    ensure_manifest,
    load_manifest,
    manifest_path,
    resolve_extraction_dir,
    update_manifest,
)

__all__ = [
    "ensure_manifest",
    "load_manifest",
    "manifest_path",
    "resolve_extraction_dir",
    "update_manifest",
]

