"""Helpers to adapt French language agreements in templates."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Grammar:
    """Simple helper container for French agreements.

    Parameters
    ----------
    profile:
        Dictionary containing the keys ``gender`` (``"m"``, ``"f"`` or ``"n"``),
        ``pronoun`` (``"il"``, ``"elle"`` or ``"iel"``) and ``tv`` (``"tu"`` or
        ``"vous"``).
    """

    profile: dict[str, Any]

    def __post_init__(self) -> None:
        self.gender = (self.profile or {}).get("gender", "f")
        if self.gender not in {"m", "f", "n"}:
            self.gender = "f"
        self.pronoun = (self.profile or {}).get("pronoun", "elle")
        if self.pronoun not in {"il", "elle", "iel"}:
            self.pronoun = "elle"
        self.tv = (self.profile or {}).get("tv", "tu")
        if self.tv not in {"tu", "vous"}:
            self.tv = "tu"
        self.plural = bool((self.profile or {}).get("plural", False))

    # ----- Tutoiement / vouvoiement helpers ---------------------------------
    def t(self, tutoiement: str, vouvoiement: str) -> str:
        return tutoiement if self.tv == "tu" else vouvoiement

    def T(self, tutoiement: str, vouvoiement: str) -> str:  # noqa: N802 (capital letter)
        return self.t(tutoiement, vouvoiement)

    def te(self, tutoiement: str, vouvoiement: str) -> str:
        return self.t(tutoiement, vouvoiement)

    def ton(self, tutoiement: str, vouvoiement: str) -> str:
        return self.t(tutoiement, vouvoiement)

    # ----- Accord adjectives / verbs -----------------------------------------
    def acc(self, masc: str, fem: str, neutral: str | None = None) -> str:
        if self.gender == "m":
            return masc
        if self.gender == "f":
            return fem
        return neutral if neutral is not None else fem

    def pron(self, il: str, elle: str, iel: str) -> str:
        mapping = {"il": il, "elle": elle, "iel": iel}
        return mapping.get(self.pronoun, iel)

    def etre(self) -> str:
        if self.tv == "tu":
            return "es"
        if self.tv == "vous":
            return "êtes"
        return "est"

    def avoir(self) -> str:
        if self.tv == "tu":
            return "as"
        if self.tv == "vous":
            return "avez"
        return "a"

    def suff_e(self) -> str:
        return "e" if self.gender in {"f", "n"} else ""

    def plur(self, singulier: str, pluriel: str) -> str:
        return pluriel if self.plural else singulier


__all__ = ["Grammar"]
