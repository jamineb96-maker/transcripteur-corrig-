"""Génération de requêtes multi-angles sans PII."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

from .faceting import Facet


PII_PATTERN = re.compile(r"(\b\d{2,}\b|@|\b(?:mr|mme|monsieur|madame)\b)", re.IGNORECASE)


@dataclass
class QueryContext:
    """Informations additionnelles pour la génération des requêtes."""

    location: str = "France"
    language: str = "français"
    sensitivity: str = "standard"


def _sanitize(text: str) -> str:
    text = text or ""
    text = PII_PATTERN.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def generate_queries(facet: Facet, context: QueryContext, extra_terms: Sequence[str] | None = None) -> Dict[str, List[str]]:
    """Construit un ensemble de requêtes multi-angles pour une facette."""

    base_terms = [facet.label, facet.focus, context.location]
    if extra_terms:
        base_terms.extend(extra_terms)
    terms = " ".join(_sanitize(term) for term in base_terms if term)
    terms = terms.strip()
    if not terms:
        terms = facet.label

    clinical = f"{context.language} {facet.label} recommandations {context.location}"
    determinants = f"{context.language} {facet.label} accès droits {context.location}"
    local = f"{context.language} ressources {context.location} {facet.label}"

    bundle = {
        "clinical": [clinical],
        "determinants": [determinants],
        "local": [local],
    }

    # Ajout d'une requête additionnelle enrichie si des termes complémentaires sont fournis.
    if terms and terms != facet.label:
        bundle["clinical"].append(f"{terms} evidence")
        bundle["determinants"].append(f"{terms} protection sociale")
        bundle["local"].append(f"{terms} services {context.location}")

    return bundle


__all__ = ["QueryContext", "generate_queries"]
