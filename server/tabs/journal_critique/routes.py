"""Routes pour l'onglet Journal critique."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from flask import jsonify, request, send_from_directory

from . import bp
from .logic import (
    assess_prompt_coverage,
    generate_document,
    generate_preview,
    get_recommendations,
    list_history,
    list_prompts,
    suggest_prompts_from_postsession,
)


@bp.get('/prompts')
def api_prompts():
    filters = {key: request.args.get(key) for key in request.args}
    prompts = list_prompts(filters)
    return jsonify({'success': True, 'prompts': prompts})


@bp.post('/suggestions')
def api_suggestions():
    payload: Dict[str, Any] = request.get_json(force=True) or {}
    artefacts = payload.get('artefacts') or {}
    budget = payload.get('budget_profile', 'moyen')
    suggestions = suggest_prompts_from_postsession(artefacts, budget=budget)
    return jsonify({'success': True, 'suggestions': suggestions})


@bp.post('/coverage')
def api_coverage():
    payload: Dict[str, Any] = request.get_json(force=True) or {}
    artefacts = payload.get('artefacts') or {}
    selected = payload.get('selected_prompts') or []
    coverage = assess_prompt_coverage(artefacts, selected)
    return jsonify({'success': True, 'coverage': coverage})


@bp.post('/preview')
def api_preview():
    payload = request.get_json(force=True) or {}
    try:
        result = generate_preview(payload)
    except ValueError as exc:
        message = {
            'no_prompts': "Aucun prompt sélectionné.",
            'missing_externalisation': "Ajoutez au moins une invite d'externalisation.",
            'missing_resultats_uniques': "Ajoutez un prompt sur les résultats uniques.",
            'missing_low_budget_variant': "Choisissez des prompts avec variantes énergie basse.",
            'pdf_too_small': "Le PDF généré est vide ou trop léger.",
            'prompt_banned_language': "Un prompt contient un terme proscrit.",
            'reportlab_missing': "Le module reportlab est requis pour générer le PDF.",
        }.get(str(exc), 'Prévisualisation impossible pour cette sélection.')
        return (
            jsonify({'success': False, 'error': str(exc), 'message': message}),
            400,
        )
    return jsonify({'success': True, 'preview': result})


@bp.post('/generate')
def api_generate():
    payload = request.get_json(force=True) or {}
    try:
        result = generate_document(payload)
    except ValueError as exc:
        message = {
            'no_prompts': "Aucun prompt sélectionné.",
            'missing_externalisation': "Ajoutez au moins une invite d'externalisation.",
            'missing_resultats_uniques': "Ajoutez un prompt sur les résultats uniques.",
            'missing_low_budget_variant': "Choisissez des prompts avec variantes énergie basse.",
            'pdf_too_small': "Le PDF généré est vide ou trop léger.",
            'docx_too_small': "Le document DOCX est vide ou trop léger.",
            'prompt_banned_language': "Un prompt contient un terme proscrit.",
            'unknown_prompt': "Un prompt sélectionné est introuvable dans la bibliothèque.",
            'missing_prompt_file': "Le fichier Markdown d'un prompt est manquant.",
            'reportlab_missing': "Le module reportlab est requis pour générer le PDF.",
            'docx_missing': "Le module python-docx est requis pour générer le DOCX.",
        }.get(str(exc), 'Génération impossible pour cette sélection.')
        return (
            jsonify({'success': False, 'error': str(exc), 'message': message}),
            400,
        )
    return jsonify({'success': True, 'data': result})


@bp.get('/history')
def api_history():
    patient_id = request.args.get('patient')
    history = list_history(patient_id)
    return jsonify({'success': True, 'history': history})


@bp.get('/exports/<path:filename>')
def api_exports(filename: str):
    base = Path('instance/archives')
    file_path = base / filename
    try:
        file_path.resolve().relative_to(base.resolve())
    except ValueError:
        return (
            jsonify({'success': False, 'error': 'forbidden'}),
            403,
        )
    if not file_path.exists():
        return (
            jsonify({'success': False, 'error': 'file_not_found'}),
            404,
        )
    return send_from_directory(base, filename, as_attachment=True)


@bp.get('/recommendations')
def api_recommendations():
    domain = request.args.get('domain', '').lower()
    data = get_recommendations(domain)
    return jsonify({'success': True, 'recommendations': data})
