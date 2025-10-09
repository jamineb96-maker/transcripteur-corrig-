"""Routines d'initialisation pour garantir un démarrage déterministe."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Dict


LOGGER = logging.getLogger(__name__)

_DEMO_SIGNATURE = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/P6Nv1gAAAABJRU5ErkJggg=="
)
_DEMO_LOGO = """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 40\"><rect width=\"120\" height=\"40\" fill=\"#2d3748\"/><text x=\"60\" y=\"24\" text-anchor=\"middle\" font-size=\"18\" fill=\"#f7fafc\">Assistant</text></svg>"""


def ensure_instance_bootstrap(base_dir: Path) -> Dict[str, object]:
    """Crée les fichiers minimums dans ``instance/`` et renvoie un rapport."""

    instance_dir = base_dir / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)

    patients_path = instance_dir / "patients.json"
    readme_path = instance_dir / "README_INSTANCE.txt"
    marker_path = instance_dir / "first_run.marker"
    documents_dir = instance_dir / "documents"
    records_dir = instance_dir / "records"
    invoices_dir = instance_dir / "invoices"
    assets_dir = instance_dir / "assets"
    library_dir = instance_dir / "library"
    journal_dir = library_dir / "journal_prompts"
    modules_dir = library_dir / "modules"

    demo_patients = [
        {"id": "nelle", "displayName": "Nelle"},
        {"id": "zoe", "displayName": "Zoé"},
        {"id": "charline", "displayName": "Charline"},
    ]

    info: Dict[str, object] = {"demo_mode": False}

    if not patients_path.exists():
        patients_path.write_text(
            json.dumps(demo_patients, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        LOGGER.info("patients.json créé avec le jeu de démonstration")
        info["demo_mode"] = True

    if not readme_path.exists():
        readme_path.write_text(
            (
                "Ce dossier contient les données persistantes de l'application.\n"
                "- patients.json : liste des patients au format JSON.\n"
                "- patients.sqlite3 : base SQLite facultative (table `patients`).\n"
                "- first_run.marker : fichier marqueur de premier lancement.\n"
                "\n"
                "Vous pouvez remplacer patients.json par vos propres données en\n"
                "respectant le schéma [{\"id\":\"...\",\"displayName\":\"...\"}].\n"
            ),
            encoding="utf-8",
        )

    documents_dir.mkdir(parents=True, exist_ok=True)
    records_dir.mkdir(parents=True, exist_ok=True)
    invoices_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    library_dir.mkdir(parents=True, exist_ok=True)
    journal_dir.mkdir(parents=True, exist_ok=True)
    modules_dir.mkdir(parents=True, exist_ok=True)

    invoices_index = invoices_dir / "index.json"
    if not invoices_index.exists():
        invoices_index.write_text("[]\n", encoding="utf-8")

    logo_path = assets_dir / "logo.svg"
    if not logo_path.exists():
        logo_path.write_text(_DEMO_LOGO, encoding="utf-8")
        info["demo_mode"] = True

    signature_path = assets_dir / "signature.png"
    if not signature_path.exists():
        signature_path.write_bytes(_DEMO_SIGNATURE)
        info["demo_mode"] = True

    prompts_index = library_dir / "journal_prompts_index.json"
    if not prompts_index.exists():
        prompts_index.write_text(
            json.dumps(
                [
                    {
                        "id": "externalisation-probleme",
                        "title": "Externalisation du problème",
                        "family": "externalisation",
                        "familyLabel": "Externalisation",
                        "tags": ["externalisation", "positionnement"],
                        "reading_level": "accessible",
                        "budget_profile": "léger",
                    },
                    {
                        "id": "cartographie-somato",
                        "title": "Cartographie somato-cognitive",
                        "family": "somatique",
                        "familyLabel": "Somatique",
                        "tags": ["somatique", "auto-observation"],
                        "reading_level": "accessible",
                        "budget_profile": "léger",
                    },
                    {
                        "id": "remembering-alliances",
                        "title": "Re-membering des alliances",
                        "family": "alliances",
                        "familyLabel": "Alliances",
                        "tags": ["relationnel", "alliances"],
                        "reading_level": "accessible",
                        "budget_profile": "moyen",
                    },
                    {
                        "id": "resultats-uniques",
                        "title": "Résultats uniques",
                        "family": "resultats_uniques",
                        "familyLabel": "Résultats uniques",
                        "tags": ["narratif"],
                        "reading_level": "intermédiaire",
                        "budget_profile": "moyen",
                    },
                    {
                        "id": "lettre-au-probleme",
                        "title": "Lettre au problème",
                        "family": "politique",
                        "familyLabel": "Positionnement politique",
                        "tags": ["politique", "valeurs"],
                        "reading_level": "intermédiaire",
                        "budget_profile": "moyen",
                    },
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        info["demo_mode"] = True

    demo_prompt = journal_dir / "externalisation_cartographie_presence.md"
    if not demo_prompt.exists():
        demo_prompt.write_text(
            (
                "# Externalisation : cartographier la présence\n\n"
                "- Décrire la présence du problème en termes sensoriels.\n"
                "- Identifier les espaces où sa voix est la plus forte.\n"
                "- Noter les allié·e·s qui contrebalancent son discours.\n"
            ),
            encoding="utf-8",
        )

    demo_module = modules_dir / "somatic_breaks.md"
    if not demo_module.exists():
        demo_module.write_text(
            (
                "# Pauses somatiques\n\n"
                "1. Micro-étirement des épaules.\n"
                "2. Respiration carrée 4-4-4-4.\n"
                "3. Vérifier les appuis au sol.\n"
            ),
            encoding="utf-8",
        )

    if not marker_path.exists():
        marker_path.write_text("bootstrap-ok", encoding="utf-8")

    return info


__all__ = ["ensure_instance_bootstrap"]

