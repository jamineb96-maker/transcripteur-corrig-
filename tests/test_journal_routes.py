import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from server import create_app


@pytest.fixture()
def client():
    app = create_app()
    app.config.update({'TESTING': True})
    with app.test_client() as client:
        yield client


def test_prompts_endpoint_returns_metadata(client):
    response = client.get('/api/journal-critique/prompts')
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    prompts = data['prompts']
    assert isinstance(prompts, list)
    assert len(prompts) >= 7
    sample = prompts[0]
    assert 'id' in sample and 'family' in sample and 'title' in sample


def test_coverage_with_sample_prompts(client):
    prompts_resp = client.get('/api/journal-critique/prompts')
    prompts = prompts_resp.get_json()['prompts']
    selected_ids = [prompt['id'] for prompt in prompts[:2]]
    response = client.post(
        '/api/journal-critique/coverage',
        json={'selected_prompts': selected_ids, 'artefacts': {'indices_somatiques': ['signal']}}
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    coverage = data['coverage']
    assert 'scores' in coverage
    assert 'alerts' in coverage


def test_suggestions_endpoint(client):
    payload = {
        'artefacts': {
            'indices_somatiques': ['douleur'],
            'lenses_used': [{'slug': 'validisme'}],
            'contradiction_spans': [{'excerpt': 'moment'}],
        },
        'budget_profile': 'moyen',
    }
    response = client.post('/api/journal-critique/suggestions', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert isinstance(data['suggestions'], list)
