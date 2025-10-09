"""Helpers et données pour la recherche post-séance."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Dict, List

from server.tabs.post_session.logic import (
    build_prompt,
    build_reperes_sections,
    parse_plan_text,
)

from .utils import clean_lines, ensure_text, sanitize_block

_RESOURCE_DIR = Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    return _RESOURCE_DIR / name


def prepare_prompt(*, transcript: str, plan_text: str, research: Dict[str, str]) -> str:
    """Compose le méga-prompt post-séance collé dans ChatGPT Web."""

    transcript_block = ensure_text(transcript)
    plan_text_value = ensure_text(plan_text)
    plan_overview = clean_lines(plan_text_value, max_lines=30)

    try:
        plan_struct = parse_plan_text(plan_text_value)
    except ValueError:
        plan_struct = {"overview": plan_overview, "steps": [], "keywords": []}

    research_payload: Dict[str, object] = dict(research or {})

    pharmaco_block = sanitize_block(
        research_payload.get("pharmacologie")
        or research_payload.get("pharmaco_sheet")
        or ""
    )
    biblio_block = sanitize_block(
        research_payload.get("bibliographie")
        or research_payload.get("evidence_sheet")
        or ""
    )

    existing_pharma = sanitize_block(research_payload.get("pharmaco_sheet") or "")
    research_payload["pharmaco_sheet"] = existing_pharma or pharmaco_block

    existing_evidence = sanitize_block(research_payload.get("evidence_sheet") or "")
    if existing_evidence:
        research_payload["evidence_sheet"] = existing_evidence
    else:
        combined = "\n\n".join(part for part in (biblio_block, pharmaco_block) if part)
        research_payload["evidence_sheet"] = combined

    points_mail: List[str] = []
    raw_points = research_payload.get("points_mail") or []
    if isinstance(raw_points, (list, tuple)):
        for item in raw_points:
            if isinstance(item, str):
                points_mail.append(item)
            elif isinstance(item, dict):
                title = item.get("title") or item.get("label") or item.get("slug")
                detail = item.get("detail") or item.get("body") or item.get("content")
                fragments = [str(value) for value in (title, detail) if value]
                if fragments:
                    points_mail.append(" — ".join(fragments))
    research_payload["points_mail"] = points_mail

    patient_value = ensure_text(
        research_payload.get("patient")
        or research_payload.get("patient_name")
        or research_payload.get("patient_label")
        or research_payload.get("prenom")
        or ""
    ).strip() or "Patient·e"

    use_tu = bool(
        research_payload.get("use_tu")
        or research_payload.get("useTu")
        or research_payload.get("tutoiement")
    )

    history_value = research_payload.get("history")
    if isinstance(history_value, list):
        history_payload = history_value
    else:
        history_payload = []

    raw_reperes = research_payload.get("reperes_sections")
    reperes_sections: List[Dict[str, str]] = []
    if isinstance(raw_reperes, list):
        for entry in raw_reperes:
            if not isinstance(entry, dict):
                continue
            title = ensure_text(entry.get("title") or entry.get("label") or "").strip()
            body = ensure_text(entry.get("body") or entry.get("content") or "").strip()
            if title and body:
                reperes_sections.append({"title": title, "body": body})

    objective_label = ensure_text(plan_struct.get("overview") or plan_overview or "").strip()
    objectives = [{"label": objective_label}] if objective_label else []
    first_step = ""
    if plan_struct.get("steps"):
        first_step = ensure_text(plan_struct["steps"][0].get("detail") or "").strip()
    contradictions = [{"excerpt": first_step}] if first_step else []

    if len(reperes_sections) < 3:
        try:
            reperes_sections = build_reperes_sections(
                research_payload,
                objectives,
                contradictions,
                target_sections=3,
            )
        except Exception:
            reperes_sections = []

    if len(reperes_sections) < 3:
        base_context = objective_label or "les situations travaillées ensemble"
        focus_context = first_step or base_context
        fallback_sections = [
            (
                "Relire les situations matérielles évoquées",
                (
                    f"Vous décrivez {base_context}. Ce repère reformule ce que vous soulignez "
                    "à propos des contraintes de logement, des rythmes de travail, des coûts de "
                    "santé et de la charge émotionnelle partagée. Il éclaire comment ces "
                    "déterminants matériels restreignent la disponibilité corporelle, l'accès "
                    "aux ressources et les marges de manœuvre quotidiennes. L'objectif est de "
                    "documenter chaque obstacle concret, de cartographier les appuis collectifs, "
                    "de vérifier l'impact financier de chaque option et de garder trace des "
                    "dispositifs institutionnels mobilisables. Cela interroge aussi la façon "
                    "dont les proches et les collègues redistribuent le care et comment les "
                    "droits existants peuvent être activés sans épuisement supplémentaire. Ce "
                    "suivi permet de consolider les décisions et d'ancrer les expérimentations "
                    "dans des alliances matérielles réelles."
                ),
            ),
            (
                "Documenter les appuis collectifs disponibles",
                (
                    f"Vous soulignez {focus_context}. Ce repère propose de tenir un journal "
                    "régulier des interactions avec les institutions, des démarches "
                    "administratives, des temps de déplacement et des dépenses associées. Il "
                    "invite à identifier qui peut soutenir, comment partager la charge des "
                    "appels, des suivis médicaux et des négociations avec l'employeur ou les "
                    "organismes sociaux. Documenter les réponses obtenues, les délais, les "
                    "refus et les réussites permet d'évaluer la soutenabilité matérielle et de "
                    "préparer des recours avec les collectifs ou syndicats disponibles. Cela "
                    "éclaire les marges de manœuvre réalistes, les arbitrages budgétaires et les "
                    "solidarités mobilisables sans culpabilisation. Le repère vise à transformer "
                    "ces constats en leviers concrets tout en rendant visible la valeur du "
                    "travail émotionnel déjà assumé."
                ),
            ),
            (
                "Observer les effets corporels et attentionnels",
                (
                    "Ce repère s'attache aux effets corporels et attentionnels que vous "
                    "décrivez pendant et après les situations exigeantes. Il propose de noter "
                    "les variations de respiration, de sommeil, de douleur et de concentration en "
                    "lien avec les contraintes matérielles afin de repérer ce qui déclenche "
                    "l'épuisement et ce qui ouvre des respirations. L'enjeu est de coordonner ces "
                    "observations avec les aménagements possibles du temps de travail, les aides "
                    "techniques accessibles et les relais relationnels déjà engagés. Prendre "
                    "appui sur des professionnel·les de confiance, des collectifs militants ou "
                    "des proches disponibles permet de négocier des pauses, de répartir les "
                    "démarches et de sécuriser les revenus sans sacrifier la santé. Le suivi "
                    "régulier documente les efforts fournis, questionne les normes productivistes "
                    "et légitime vos demandes d'ajustement."
                ),
            ),
        ]
        reperes_sections = [
            {"title": title, "body": textwrap.fill(body, 90)}
            for title, body in fallback_sections
        ]

    prompt_package = build_prompt(
        patient_name=patient_value,
        use_tu=use_tu,
        retained_section=sanitize_block(research_payload.get("retained_section") or ""),
        reperes_sections=reperes_sections,
        research=research_payload,
        history=history_payload,
        transcript=transcript_block,
        plan=plan_struct,
    )

    return prompt_package["prompt"]


__all__ = ["prepare_prompt", "resource_path"]
