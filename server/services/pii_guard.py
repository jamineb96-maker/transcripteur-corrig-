"""Outils minimaux pour retirer les informations personnelles identifiables."""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, Set

__all__ = ["scrub_pii", "is_pii_token"]


def _normalise(value: str) -> str:
    """Normalise une chaîne pour les comparaisons PII."""

    normalized = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return normalized.lower().strip()


def _collect_sensitive_items(patient_meta: Dict[str, object]) -> Set[str]:
    """Construit l'ensemble des éléments à supprimer (noms, alias, lieux)."""

    candidates: Set[str] = set()
    if not patient_meta:
        return candidates

    possible_keys = ("name", "names", "aliases", "alias", "places", "locations", "city", "cities")
    for key in possible_keys:
        value = patient_meta.get(key) if isinstance(patient_meta, dict) else None
        if not value:
            continue
        if isinstance(value, str):
            candidates.add(_normalise(value))
        elif isinstance(value, Iterable):
            for item in value:
                if isinstance(item, str):
                    candidates.add(_normalise(item))
    return {item for item in candidates if item}


def is_pii_token(token: str, patient_meta: Dict[str, object] | None = None) -> bool:
    """Détecte si un token correspond à une information personnelle connue."""

    if not token:
        return False
    normalized = _normalise(token)
    if not normalized:
        return False
    sensitive = _collect_sensitive_items(patient_meta or {})
    if normalized in sensitive:
        return True
    # heuristique simple : les tokens très courts ou contenant des chiffres
    # ne sont pas considérés comme PII, tandis que les tokens avec un tiret
    # ou apostrophe sont évalués par sous-parties.
    if any(sub in sensitive for sub in normalized.replace("'", " ").replace("-", " ").split()):
        return True
    return False


def scrub_pii(text: str, patient_meta: Dict[str, object] | None = None) -> str:
    """Retire les occurrences d'items sensibles d'un texte.

    Les remplacements utilisent une simple stratégie basée sur des mots entiers afin
    d'éviter les faux positifs agressifs tout en garantissant l'absence de noms
    explicites de patient·es dans les requêtes.
    """

    if not text:
        return ""
    sensitive = _collect_sensitive_items(patient_meta or {})
    if not sensitive:
        return text

    pattern = re.compile(r"\b(" + "|".join(re.escape(item) for item in sensitive if item) + r")\b", re.IGNORECASE)
    return pattern.sub("[REDACTED]", text)

