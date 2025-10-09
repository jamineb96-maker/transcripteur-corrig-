"""Chargement des artefacts issus de la pipeline Post-séance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping

_BASE_DIR = Path(__file__).resolve().parents[3]
_DATA_FILE = _BASE_DIR / 'data' / 'post_session_artefacts.json'
_INSTANCE_DIR = _BASE_DIR / 'instance'


def _load_data() -> Dict[str, Mapping[str, object]]:
    if not _DATA_FILE.exists():
        return {}
    try:
        raw = json.loads(_DATA_FILE.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}
    data: Dict[str, Mapping[str, object]] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, Mapping):
                data[str(key)] = value
    elif isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, Mapping):
                continue
            key = str(entry.get('patient_id') or entry.get('id') or '')
            if key:
                data[key] = entry
    return data


def _read_latest_transcript(patient_id: str) -> str:
    folder = _INSTANCE_DIR / 'post_session' / patient_id
    if not folder.exists():
        return ''
    candidates = sorted(folder.glob('*.txt'), reverse=True)
    for candidate in candidates:
        try:
            text = candidate.read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if text:
            return text
    return ''


_KEYWORDS_MAP = {
    'douleur': 'somatique',
    'fatigue': 'somatique',
    'crispation': 'somatique',
    'brouillard': 'cognitif',
    'oublis': 'cognitif',
    'pression': 'boundaries',
    'limites': 'boundaries',
    'transport': 'materiel',
}


def _fallback_from_transcript(patient_id: str) -> Dict[str, object]:
    transcript = _read_latest_transcript(patient_id)
    if not transcript:
        return {
            'objectifs_extraits': [],
            'indices_somatiques': [],
            'indices_cognitifs': [],
            'contradiction_spans': [],
            'lenses_used': [],
            'reperes_candidates': [],
            'ai_requests': [],
            'evidence_sheet': [],
            'historique': [],
            'notes': 'fallback_empty',
        }
    text_lower = transcript.lower()
    somatiques = []
    cognitifs = []
    boundaries = []
    for keyword, label in _KEYWORDS_MAP.items():
        if keyword in text_lower:
            if label == 'somatique':
                somatiques.append(keyword)
            elif label == 'cognitif':
                cognitifs.append(keyword)
            elif label == 'boundaries':
                boundaries.append(keyword)
    objectifs = []
    if 'objectif' in text_lower:
        objectifs.append('clarifier objectifs court terme')
    if 'pause' in text_lower:
        objectifs.append('planifier des pauses')
    lenses = []
    if 'validisme' in text_lower or 'handicap' in text_lower:
        lenses.append('validisme')
    if 'trauma' in text_lower:
        lenses.append('trauma_complexe')
    reperes = []
    if 'repere' in text_lower or 'routine' in text_lower:
        reperes.append('routine simplifiée')
    ai_requests = []
    if 'peux-tu' in text_lower or 'pouvez-vous' in text_lower:
        ai_requests.append('demande_outil_budget_cognitif')
    return {
        'objectifs_extraits': objectifs,
        'indices_somatiques': somatiques,
        'indices_cognitifs': cognitifs,
        'contradiction_spans': boundaries,
        'lenses_used': lenses,
        'reperes_candidates': reperes,
        'ai_requests': ai_requests,
        'evidence_sheet': [],
        'historique': [transcript[:400]],
        'notes': 'fallback_transcript',
    }


def load_artefacts(patient_id: str) -> Dict[str, object]:
    patient_id = str(patient_id or '').strip()
    if not patient_id:
        return {}
    data = _load_data()
    artefacts = data.get(patient_id)
    if artefacts:
        return dict(artefacts)
    return _fallback_from_transcript(patient_id)
