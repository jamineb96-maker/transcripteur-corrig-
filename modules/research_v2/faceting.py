"""Extraction des facettes de recherche pour la pré-session v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass
class Facet:
    """Représente une facette de recherche contextualisée."""

    name: str
    label: str
    focus: str
    expected_topics: List[str]
    required: bool = True
    progress_target: int = 10


DEFAULT_FACETS: List[Facet] = [
    Facet(
        name="douleur_dysautonomie",
        label="Douleurs et dysautonomie",
        focus="Lien entre douleurs chroniques, dysautonomie et endométriose",
        expected_topics=["douleur", "dysautonomie", "endométriose"],
    ),
    Facet(
        name="migraine_endometriose",
        label="Migraines et endométriose",
        focus="Articulation migraines hormonales, endométriose et traitements",
        expected_topics=["migraine", "endométriose"],
    ),
    Facet(
        name="tdah_charge_allostatique",
        label="TDAH et charge allostatique",
        focus="Gestion du TDAH, surcharge mentale et administrative",
        expected_topics=["TDAH", "charge", "allostatique"],
    ),
    Facet(
        name="medicaments_effets",
        label="Médicaments et effets",
        focus="Traitements en cours, interactions, effets secondaires",
        expected_topics=["médicament", "traitement", "effets"],
    ),
    Facet(
        name="achats_compulsifs_dettes",
        label="Achats compulsifs et dettes",
        focus="Impact financier et accès aux protections sociales",
        expected_topics=["achats", "dettes", "financier"],
    ),
    Facet(
        name="communication_couple",
        label="Communication de couple",
        focus="Coordination dans le couple face aux soins",
        expected_topics=["couple", "communication"],
    ),
    Facet(
        name="droits_orientation_locale",
        label="Droits et orientation locale",
        focus="Accès aux droits en France et ressources locales",
        expected_topics=["droits", "orientation", "France"],
    ),
]


def extract_facets(raw_context: Dict[str, str]) -> List[Facet]:
    """Retourne les facettes pertinentes à partir du contexte fourni."""

    text_blob = " ".join((value or "") for value in raw_context.values()).lower()
    facets: List[Facet] = []
    for facet in DEFAULT_FACETS:
        # Si une facette est présente dans le contexte, on la marque comme prioritaire.
        found = any(keyword.lower() in text_blob for keyword in facet.expected_topics)
        facets.append(
            Facet(
                name=facet.name,
                label=facet.label,
                focus=facet.focus,
                expected_topics=facet.expected_topics,
                required=found or facet.required,
                progress_target=facet.progress_target,
            )
        )
    return facets


__all__ = ["Facet", "extract_facets", "DEFAULT_FACETS"]
