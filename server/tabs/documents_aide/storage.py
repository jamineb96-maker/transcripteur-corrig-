"""Gestion de l'historique des documents d'aide générés."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from server.services.paths import ensure_patient_subdir
from server.util import slugify


def _patient_dir(patient_id: str) -> Path:
    slug = slugify(patient_id or "")
    return ensure_patient_subdir(slug, "documents_aide")


def _history_path(patient_id: str) -> Path:
    return _patient_dir(patient_id) / 'history.json'


def load_history(patient_id: str) -> List[Dict[str, object]]:
    path = _history_path(patient_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    return []


def append_history(patient_id: str, entry: Dict[str, object]) -> None:
    history = load_history(patient_id)
    history.append(entry)
    # Conserve les 20 derniers
    history = history[-20:]
    path = _history_path(patient_id)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


def document_output_path(patient_id: str, filename: str) -> Path:
    safe_name = filename.replace('..', '_')
    return _patient_dir(patient_id) / safe_name
