# [pipeline-v3 begin]
"""Construction du plan pré-séance v3 (anti-TCC, critique, narrative, située)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def build_pre_session_plan(
    raw_context: Dict[str, str],
    previous_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble un plan préparatoire minimaliste et strict."""

    def _one_line(s: str) -> str:
        return " ".join((s or "").split()).strip()

    orientation = (
        _one_line(raw_context.get("orientation", ""))
        or "Clarifier la demande et cadrer la séance dans une perspective matérialiste, féministe et evidence based."
    )
    objectif = (
        _one_line(raw_context.get("objectif_prioritaire", ""))
        or "Formuler un objectif opératoire partagé pour la séance."
    )
    cadre = (
        _one_line(raw_context.get("cadre_de_travail", ""))
        or "Cadre matérialiste, féministe, evidence based, critique et situé; sans échelles chiffrées ni coaching individualisant."
    )
    situation = (
        _one_line(raw_context.get("situation_actuelle", ""))
        or _one_line(raw_context.get("etat_depuis_derniere", ""))
        or "Éléments transmis avant séance enregistrés."
    )
    tensions = _one_line(raw_context.get("tensions_principales", "")) or _one_line(raw_context.get("etat_depuis_derniere", "")) or "Tensions partagées à clarifier ensemble."
    axes = _one_line(raw_context.get("axes_de_travail", "")) or _one_line(raw_context.get("notes_therapeutiques", "")) or "Repérer collectivement les appuis et protections disponibles."
    cloture = (
        _one_line(raw_context.get("cloture_attendue", ""))
        or "Sortir avec une clarification partagée et un pas de continuité réaliste."
    )

    diff = {"orientation_modifiee": False, "elements_ajoutes": [], "elements_retires": []}
    if previous_plan:
        diff["orientation_modifiee"] = _one_line(previous_plan.get("orientation", "")) != orientation

    return {
        "orientation": orientation,
        "objectif_prioritaire": objectif,
        "cadre_de_travail": cadre,
        "synthese": {
            "situation_actuelle": situation,
            "tensions_principales": tensions,
            "axes_de_travail": axes,
        },
        "cloture_attendue": cloture,
        "diff_avec_plan_precedent": diff,
    }
# [pipeline-v3 end]
