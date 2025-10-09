"""Génération des pré-sélections à partir des artefacts Post-séance."""

from __future__ import annotations

from typing import Dict, Iterable, List

from .library import Tool

_OBJECTIVE_MAP = {
    'energie': {'energie', 'budget_cognitif'},
    'pause': {'somatique', 'auto_soin'},
    'limite': {'boundaries'},
    'signal': {'cognitif'},
    'douleur': {'somatique'},
}

_LENS_TAGS = {
    'validisme': {'lens:validisme'},
    'trauma_complexe': {'lens:trauma'},
    'patriarcat': {'lens:patriarcat'},
    'neurodiversité': {'lens:neurodiversite'},
    'matérialisme': {'contextualisation'},
}


def _modules_for_tags(tools: Iterable[Tool], tags: Iterable[str]) -> List[Tool]:
    tags = {tag.lower() for tag in tags}
    result = []
    for tool in tools:
        tool_tags = {tag.lower() for tag in tool.tags}
        if tool_tags & tags:
            result.append(tool)
    return result


def _explain(tag: str, artefact_source: str) -> str:
    return f"Détection {artefact_source} → besoin '{tag}'."


def suggest_modules_from_postsession(artefacts: Dict[str, object], tools: Iterable[Tool]) -> List[Dict[str, object]]:
    """Renvoie une liste priorisée de modules suggérés avec justification."""

    suggestions: List[Dict[str, object]] = []
    seen = set()
    tools = list(tools)

    def add(tool: Tool, priority: float, why: str) -> None:
        if tool.id in seen:
            return
        seen.add(tool.id)
        suggestions.append({'id': tool.id, 'title': tool.title, 'priority': priority, 'why': why})

    objectifs = artefacts.get('objectifs_extraits') or []
    for objectif in objectifs:
        if not isinstance(objectif, str):
            continue
        lower = objectif.lower()
        for key, tags in _OBJECTIVE_MAP.items():
            if key in lower:
                for tool in _modules_for_tags(tools, tags):
                    add(tool, 0.9, _explain(key, 'objectifs'))

    ai_requests = artefacts.get('ai_requests') or []
    for request in ai_requests:
        if not isinstance(request, str):
            continue
        lower = request.lower()
        if 'budget' in lower or 'cognitif' in lower:
            for tool in _modules_for_tags(tools, {'budget_cognitif'}):
                add(tool, 0.85, "Demande explicite d'outils budget cognitif")
        if 'limite' in lower or 'boundary' in lower:
            for tool in _modules_for_tags(tools, {'boundaries'}):
                add(tool, 0.82, "Demande de ressources limites")

    indices_somatiques = artefacts.get('indices_somatiques') or []
    if indices_somatiques:
        for tool in _modules_for_tags(tools, {'somatique', 'auto_soin'}):
            add(tool, 0.8, 'Présence d’indices somatiques récurrents')
    indices_cognitifs = artefacts.get('indices_cognitifs') or []
    if indices_cognitifs:
        for tool in _modules_for_tags(tools, {'cognitif', 'budget_cognitif'}):
            add(tool, 0.78, 'Signaux de surcharge cognitive détectés')

    contradiction_spans = artefacts.get('contradiction_spans') or []
    if contradiction_spans:
        for tool in _modules_for_tags(tools, {'boundaries', 'communication'}):
            add(tool, 0.7, 'Contradictions dans le respect des limites')

    lenses = artefacts.get('lenses_used') or []
    for lens in lenses:
        if not isinstance(lens, str):
            continue
        key = lens.lower()
        tags = _LENS_TAGS.get(key)
        if tags:
            for tool in _modules_for_tags(tools, tags):
                add(tool, 0.68, f"Lens critique active : {lens}")
        elif key == 'validisme':
            for tool in _modules_for_tags(tools, {'lens:validisme', 'contextualisation'}):
                add(tool, 0.68, "Lens validisme détectée")

    reperes = artefacts.get('reperes_candidates') or []
    for rep in reperes:
        if not isinstance(rep, str):
            continue
        lower = rep.lower()
        if any(word in lower for word in ('pause', 'micro-pause')):
            for tool in _modules_for_tags(tools, {'somatique'}):
                add(tool, 0.72, "Repère candidat → pauses somatiques")
        if 'signal' in lower:
            for tool in _modules_for_tags(tools, {'cognitif'}):
                add(tool, 0.7, "Repère candidat → signaux cognitifs")

    suggestions.sort(key=lambda item: item['priority'], reverse=True)
    return suggestions
