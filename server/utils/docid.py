"""Utilitaires de validation et de mapping pour les identifiants de document.

Ce module encapsule la logique de conversion entre les identifiants exposés par
l'API (``doc_id``) et leur représentation sur le système de fichiers.
"""

from __future__ import annotations

import logging
import os
import re
from os import PathLike
from pathlib import Path

LOGGER = logging.getLogger(__name__)

_DOC_ID_RE = re.compile(r"^(?P<algo>[a-z0-9]{3,15}):(?P<hash>[a-f0-9]{32,128})$")
_FORBIDDEN_CHARS = set('<>:"/\\|?*')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}


def parse_doc_id(doc_id: str) -> tuple[str, str]:
    """Valide et découpe un ``doc_id``.

    Le format attendu est ``<algo>:<hex>`` où ``algo`` est en minuscules et
    ``hex`` est une chaîne hexadécimale (longueur 32 à 128).
    """

    if not isinstance(doc_id, str):
        raise ValueError("doc_id doit être une chaîne de caractères")
    candidate = doc_id.strip()
    match = _DOC_ID_RE.match(candidate)
    if not match:
        raise ValueError(f"doc_id invalide : {doc_id!r}")
    algo = match.group("algo")
    digest = match.group("hash")
    return algo, digest


def _ensure_safe_component(component: str, *, name: str) -> str:
    if any(ord(char) < 32 for char in component):
        raise ValueError(f"composant {name} contient des caractères de contrôle")
    if any(char in _FORBIDDEN_CHARS for char in component):
        raise ValueError(f"composant {name} contient un caractère réservé")
    upper = component.upper()
    if upper in _WINDOWS_RESERVED:
        raise ValueError(f"composant {name} correspond à un nom réservé Windows")
    if component.endswith(" ") or component.endswith("."):
        # Windows interdit les espaces ou points terminaux.
        raise ValueError(f"composant {name} ne doit pas se terminer par espace ou point")
    return component


def doc_id_to_fs_path(root: Path | str | PathLike[str], doc_id: str, shard: bool = True) -> Path:
    """Convertit un ``doc_id`` en chemin système.

    Args:
        root: Racine des documents extraits.
        doc_id: Identifiant ``<algo>:<hash>``.
        shard: Quand ``True``, répartit les fichiers selon le schéma
            ``algo/h0h1/h2h3/hash`` pour limiter la densité d'un dossier.
    """

    algo, digest = parse_doc_id(doc_id)
    algo = _ensure_safe_component(algo, name="algo")
    digest = _ensure_safe_component(digest, name="hash")

    parts: list[str] = [algo]
    if shard and len(digest) >= 4:
        parts.extend([digest[0:2], digest[2:4]])
    elif shard and len(digest) >= 2:
        parts.append(digest[0:2])
    parts.append(digest)

    fs_path = Path(root)
    for part in parts:
        fs_path /= part
    LOGGER.debug("doc_id_to_fs_path", extra={"doc_id": doc_id, "fs_path": str(fs_path), "shard": shard})
    return fs_path


def legacy_fs_path(root: Path | str | PathLike[str], doc_id: str) -> Path:
    """Reconstitue le chemin historique ``algo:hash`` pour compatibilité."""

    algo, digest = parse_doc_id(doc_id)
    component = f"{algo}:{digest}"
    if os.name == "nt" and ":" in component:
        component = component.replace(":", "_")
    legacy_path = Path(root) / component
    LOGGER.debug("legacy_fs_path", extra={"doc_id": doc_id, "fs_path": str(legacy_path)})
    return legacy_path


def ensure_dir(path: Path | str | PathLike[str]) -> Path:
    """Crée le répertoire de manière idempotente avec journalisation."""

    candidate = Path(path)
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        LOGGER.error("Impossible de créer le répertoire %s", candidate, exc_info=True)
        raise
    else:
        LOGGER.debug("ensure_dir", extra={"path": str(candidate)})
    return candidate


__all__ = [
    "doc_id_to_fs_path",
    "ensure_dir",
    "legacy_fs_path",
    "parse_doc_id",
]
