"""v1.0 – Utilitaires de normalisation française pour les sorties LLM.

Ce module regroupe deux helpers simples utilisés par les services Post-séance :
    * ``normalize_punctuation`` : supprime les tirets longs, harmonise les guillemets
      français et nettoie les espaces insécables.
    * ``trim_quotes`` : s'assure que les citations ne dépassent pas ``max_words`` mots.

Les fonctions sont écrites pour rester idempotentes : appliquer plusieurs fois la
normalisation ne modifie plus le texte après la première passe.

Points d'extension :
    - ajouter d'autres règles typographiques (espaces fines, capitales).
    - brancher un correcteur morphologique si besoin futur.
"""

from __future__ import annotations

import re
from typing import Iterable

_NON_BREAKING_BEFORE = {":", "!", "?", ";"}


def _replace_long_dashes(text: str) -> str:
    """Remplace les tirets longs par des parenthèses légères.

    L'approche choisie est volontairement simple : lorsqu'un tiret long est suivi
    d'un segment clos par une ponctuation forte, on encapsule le segment dans des
    parenthèses. Sinon, le tiret est simplement remplacé par une parenthèse ouvrante
    suivie d'un espace, et une parenthèse fermante est ajoutée en fin de segment.
    """

    def _replace(match: re.Match[str]) -> str:
        inner = match.group("inner").strip()
        closing = match.group("closing") or ""
        if inner:
            return f" ({inner}){closing}"
        return f" ({closing}".rstrip()

    pattern = re.compile(r"\s*—\s*(?P<inner>[^—]*?)(?P<closing>[\.!?,;:]|$)")
    result = pattern.sub(_replace, text)
    return result.replace("—", " (")


def normalize_punctuation(text: str) -> str:
    """Applique une normalisation typographique française légère."""

    if not text:
        return ""
    value = str(text)
    value = _replace_long_dashes(value)
    # Guillemets droits ou typographiques → guillemets français
    value = re.sub(r'"\s*(.+?)\s*"', r'« \1 »', value)
    value = re.sub(r"[“”]\s*(.+?)\s*[“”]", r"« \1 »", value)
    # Supprimer espaces multiples
    value = re.sub(r"\s+", " ", value)
    # Restaurer sauts de ligne
    value = value.replace(" \n", "\n").replace("\n ", "\n")
    # Espaces insécables avant ponctuation double
    for mark in _NON_BREAKING_BEFORE:
        value = re.sub(fr"\s*{re.escape(mark)}", f"\u00a0{mark}", value)
    value = value.replace("\u00a0 ", "\u00a0")
    return value.strip()


def trim_quotes(text: str, max_words: int = 10) -> str:
    """Tronque les citations trop longues à ``max_words`` mots."""

    if max_words <= 0:
        raise ValueError("max_words doit être > 0")
    if not text:
        return ""

    def _trim(segment: str) -> str:
        words = [word for word in segment.strip().split() if word]
        if len(words) <= max_words:
            return segment.strip()
        shortened = " ".join(words[:max_words]) + "…"
        return shortened

    def _replace_quotes(matches: Iterable[re.Match[str]]) -> str:
        updated = text
        for match in matches:
            inner = match.group(1)
            trimmed = _trim(inner)
            updated = updated.replace(match.group(0), f"« {trimmed} »")
        return updated

    french_pattern = re.finditer(r"«\s*(.+?)\s*»", text)
    updated = _replace_quotes(french_pattern)
    straight_pattern = re.finditer(r'"\s*(.+?)\s*"', updated)
    updated = _replace_quotes(straight_pattern)
    return updated


__all__ = ["normalize_punctuation", "trim_quotes"]
