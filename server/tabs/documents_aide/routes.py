"""Routes Flask pour le module Documents d'aide."""

from __future__ import annotations

import base64
import datetime as dt
import re
import unicodedata
from typing import Dict, List

from flask import jsonify, request, send_from_directory

from server.services.patients import list_patients

from . import bp
from .coverage import assess_library_coverage
from .library import Tool, get_tool, iter_tools_from_ids, list_metadata, list_tools, read_tool_content
from .personalize import apply_personalization, build_context
from .pdf import ModuleRender, build_pdf, build_preview
from .postsession import load_artefacts
from .recommendations import build_recommendations
from .storage import append_history, document_output_path, load_history
from .suggestions import suggest_modules_from_postsession
from .validators import validate_selection


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value or '').encode('ascii', 'ignore').decode('ascii')
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", '-', normalized).strip('-')
    return normalized or 'document'


def _resolve_patient(patient_payload: Dict[str, object]) -> Dict[str, object]:
    patient_id = str(patient_payload.get('id') or '').strip()
    name = str(patient_payload.get('name') or patient_payload.get('displayName') or '').strip()
    if not patient_id and patient_payload.get('patient_id'):
        patient_id = str(patient_payload['patient_id']).strip()
    if not name and patient_id:
        match = next((p for p in list_patients() if p['id'] == patient_id), None)
        if match:
            name = match.get('displayName') or match.get('name') or patient_id
    if not patient_id:
        raise ValueError('missing_patient_id')
    if not name:
        name = patient_id
    payload = dict(patient_payload)
    payload['id'] = patient_id
    payload['name'] = name
    return payload


def _render_modules(module_ids: List[str], patient: Dict[str, object], langage: str, gender: str) -> List[ModuleRender]:
    context = build_context(patient, langage, gender)
    rendered: List[ModuleRender] = []
    for tool in iter_tools_from_ids(module_ids):
        raw = read_tool_content(tool)
        personalized = apply_personalization(raw, context)
        summary = '\n'.join(line.strip() for line in personalized.splitlines() if line.strip())[:220]
        rendered.append(ModuleRender(id=tool.id, title=tool.title, content=personalized, summary=summary))
    return rendered


def _selected_tools(module_ids: List[str]) -> List[Tool]:
    tools = []
    for module_id in module_ids:
        tool = get_tool(module_id)
        if tool:
            tools.append(tool)
    return tools


@bp.get('/modules')
def list_modules():
    """Expose la bibliothèque disponible."""

    return jsonify({'success': True, 'modules': list_metadata()})


@bp.get('/context')
def context():
    """Retourne le contexte pour un patient donné (modules + suggestions)."""

    patient_id = request.args.get('patient') or ''
    patient_id = patient_id.strip()
    artefacts = load_artefacts(patient_id) if patient_id else {}
    suggestions = suggest_modules_from_postsession(artefacts, list_tools()) if patient_id else []
    coverage = assess_library_coverage(artefacts, [], list_tools()) if patient_id else {'score': 100, 'status': 'ok', 'needs': [], 'missing_modules': []}
    return jsonify(
        {
            'success': True,
            'modules': list_metadata(),
            'artefacts': artefacts,
            'suggestions': suggestions,
            'coverage': coverage,
        }
    )


@bp.get('')
def history():
    """Retourne l'historique des documents générés pour un patient."""

    patient_id = request.args.get('patient')
    if not patient_id:
        return jsonify({'success': True, 'history': []})
    records = load_history(patient_id)
    for record in records:
        filename = record.get('filename')
        if filename:
            record['file_url'] = f"/api/documents-aide/download/{patient_id}/{filename}"
    return jsonify({'success': True, 'history': records})


@bp.post('/assess')
def assess():
    payload = request.get_json(silent=True) or {}
    patient_data = payload.get('patient') or {}
    modules = payload.get('modules') or []
    langage = payload.get('langage') or 'vous'
    gender = patient_data.get('gender') or payload.get('gender') or 'neutral'
    try:
        patient = _resolve_patient(patient_data)
    except ValueError:
        return jsonify({'success': False, 'error': 'missing_patient_id'}), 400
    artefacts = load_artefacts(patient['id'])
    coverage = assess_library_coverage(artefacts, modules, list_tools())
    validators = validate_selection(_selected_tools(modules), artefacts, patient_data.get('contraindications') or [])
    recommendations = build_recommendations(coverage.get('missing_modules', []), artefacts)
    return jsonify(
        {
            'success': True,
            'coverage': coverage,
            'validators': validators,
            'recommendations': recommendations,
        }
    )


@bp.post('/preview')
def preview():
    payload = request.get_json(silent=True) or {}
    patient_data = payload.get('patient') or {}
    modules = payload.get('modules') or []
    langage = payload.get('langage') or 'vous'
    gender = patient_data.get('gender') or payload.get('gender') or 'neutral'
    try:
        patient = _resolve_patient(patient_data)
    except ValueError:
        return jsonify({'success': False, 'error': 'missing_patient_id'}), 400
    rendered = _render_modules(modules, patient, langage, gender)
    preview_bytes = build_preview(rendered, patient['name'])
    encoded = base64.b64encode(preview_bytes).decode('ascii')
    return jsonify({'success': True, 'preview': encoded})


@bp.post('')
def generate():
    payload = request.get_json(silent=True) or {}
    patient_data = payload.get('patient') or {}
    modules = payload.get('modules') or []
    langage = payload.get('langage') or 'vous'
    gender = patient_data.get('gender') or payload.get('gender') or 'neutral'
    notes = payload.get('notes_praticien') or ''
    if not isinstance(modules, list):
        return jsonify({'success': False, 'error': 'invalid_modules'}), 400
    try:
        patient = _resolve_patient(patient_data)
    except ValueError:
        return jsonify({'success': False, 'error': 'missing_patient_id'}), 400

    artefacts = load_artefacts(patient['id'])
    coverage = assess_library_coverage(artefacts, modules, list_tools())
    selected_tools = _selected_tools(modules)
    validators = validate_selection(selected_tools, artefacts, patient_data.get('contraindications') or [])
    if validators['errors']:
        return (
            jsonify({'success': False, 'error': 'validation_failed', 'details': validators}),
            422,
        )

    rendered_modules = _render_modules(modules, patient, langage, gender)
    pdf_bytes = build_pdf(rendered_modules, patient['name'], langage, notes, patient_data.get('cabinet') or 'Cabinet')

    today = dt.datetime.now().strftime('%Y%m%d_%H%M')
    slug = _slugify(patient['name'])
    filename = f"{today}_{slug}.pdf"
    output_path = document_output_path(patient['id'], filename)
    output_path.write_bytes(pdf_bytes)

    entry = {
        'generated_at': dt.datetime.now().isoformat(),
        'filename': filename,
        'modules': modules,
        'coverage': coverage,
        'notes': notes,
        'artefacts': artefacts,
    }
    append_history(patient['id'], entry)

    return jsonify(
        {
            'success': True,
            'file_url': f"/api/documents-aide/download/{patient['id']}/{filename}",
            'coverage': coverage,
            'validators': validators,
        }
    )


@bp.get('/download/<patient_id>/<path:filename>')
def download(patient_id: str, filename: str):
    """Permet de télécharger un PDF généré."""

    path = document_output_path(patient_id, filename)
    if not path.exists():
        return jsonify({'success': False, 'error': 'file_not_found'}), 404
    return send_from_directory(path.parent, path.name, as_attachment=True)


@bp.get('/coverage-report')
def coverage_report():
    patient_id = request.args.get('patient')
    if not patient_id:
        return jsonify({'success': False, 'error': 'missing_patient'}), 400
    history = load_history(patient_id)
    if not history:
        return jsonify({'success': True, 'report': {'entries': []}})
    latest = history[-1]
    report = {
        'patient_id': patient_id,
        'generated_at': latest.get('generated_at'),
        'modules': latest.get('modules', []),
        'coverage': latest.get('coverage', {}),
        'artefacts': latest.get('artefacts', {}),
    }
    return jsonify({'success': True, 'report': report})


@bp.get('/recommendations')
def recommendations():
    patient_id = request.args.get('patient')
    artefacts = load_artefacts(patient_id) if patient_id else {}
    coverage = assess_library_coverage(artefacts, [], list_tools())
    recommendations_payload = build_recommendations(coverage.get('missing_modules', []), artefacts)
    return jsonify({'success': True, 'recommendations': recommendations_payload})
