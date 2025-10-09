from pathlib import Path

import pytest

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from server import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config.update({'TESTING': True})
    with app.test_client() as client:
        yield client


def _cleanup_patient_docs(patient_id: str):
    base_dir = Path(__file__).resolve().parents[1]
    docs_dir = base_dir / 'instance' / 'documents' / patient_id
    if docs_dir.exists():
        for path in docs_dir.glob('*'):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass


def test_modules_listing(client):
    response = client.get('/api/documents-aide/modules')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    ids = {module['id'] for module in payload['modules']}
    assert 'spoon_theory' in ids


def test_context_and_assess(client):
    response = client.get('/api/documents-aide/context?patient=p1')
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert any(s['id'] == 'spoon_theory' for s in data['suggestions'])

    assess_payload = {
        'patient': {'id': 'p1', 'name': 'Caroline', 'gender': 'feminine'},
        'modules': ['spoon_theory', 'somatic_breaks'],
        'langage': 'vous',
        'gender': 'feminine',
    }
    assess_response = client.post('/api/documents-aide/assess', json=assess_payload)
    assert assess_response.status_code == 200
    assess_data = assess_response.get_json()
    assert assess_data['success'] is True
    assert assess_data['coverage']['score'] <= 100
    alignment = assess_data['coverage']['level_alignment']
    assert alignment['expected'] == 'base'
    assert alignment['status'] in {'aligned', 'partial', 'mismatch', 'missing', 'neutral'}
    assert alignment['message']
    assert any(rec['id'] == 'micro_sensory_breaks' for rec in assess_data['recommendations'])


def test_generate_document_success(client):
    _cleanup_patient_docs('p1')
    payload = {
        'patient': {'id': 'p1', 'name': 'Caroline', 'gender': 'feminine'},
        'modules': ['spoon_theory', 'somatic_breaks'],
        'langage': 'vous',
        'gender': 'feminine',
        'notes_praticien': 'Notes de test',
        'priorites': ['energie', 'somatique'],
    }
    response = client.post('/api/documents-aide', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    file_url = data['file_url']
    assert file_url.startswith('/api/documents-aide/download/')
    filename = file_url.rsplit('/', 1)[-1]
    base_dir = Path(__file__).resolve().parents[1]
    pdf_path = base_dir / 'instance' / 'documents' / 'p1' / filename
    assert pdf_path.exists()
    _cleanup_patient_docs('p1')


def test_generate_rejects_editorial_terms(client):
    base_dir = Path(__file__).resolve().parents[1]
    module_path = base_dir / 'library' / 'modules' / 'spoon_theory.md'
    original_content = module_path.read_text(encoding='utf-8')
    try:
        module_path.write_text(original_content + '\n\nComplexe d\'Œdipe cité pour test.', encoding='utf-8')
        payload = {
            'patient': {'id': 'p1', 'name': 'Caroline', 'gender': 'feminine'},
            'modules': ['spoon_theory'],
            'langage': 'vous',
            'gender': 'feminine',
        }
        response = client.post('/api/documents-aide', json=payload)
        assert response.status_code == 422
        data = response.get_json()
        assert data['success'] is False
        assert data['error'] == 'validation_failed'
    finally:
        module_path.write_text(original_content, encoding='utf-8')
        _cleanup_patient_docs('p1')


def test_level_alignment_penalizes_score(client):
    payload = {
        'patient': {'id': 'p1', 'name': 'Caroline', 'gender': 'feminine'},
        'modules': ['boundaries'],
        'langage': 'vous',
        'gender': 'feminine',
    }
    response = client.post('/api/documents-aide/assess', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    coverage = data['coverage']
    alignment = coverage['level_alignment']
    assert alignment['expected'] == 'base'
    assert alignment['status'] == 'mismatch'
    assert 'attendu' in alignment['message']
    assert coverage['score'] < 80
