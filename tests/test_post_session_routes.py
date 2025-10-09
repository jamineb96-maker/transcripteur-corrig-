import hashlib
import io
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from server import create_app
from server.services import patients_repo

patients_repo.ARCHIVES_ROOT = Path(os.getcwd()) / 'tests_instance_archives'
patients_repo.ARCHIVES_ROOT.mkdir(parents=True, exist_ok=True)

from server.tabs.post_session import logic
from server.blueprints import post_session


@pytest.fixture()
def client():
    app = create_app()
    app.config.update({'TESTING': True})
    with app.test_client() as client:
        yield client


def _count_words(text: str) -> int:
    return len([w for w in re.findall(r"\w+", text)])


def test_process_success(client):
    audio_content = (
        "Consultation de suivi sur le sommeil.\n"
        "Le patient décrit une amélioration mais encore des réveils.\n"
        "Planifier un suivi des routines d'hygiène du sommeil et proposer des exercices de respiration."
    ).encode('utf-8')
    data = {
        'audio': (io.BytesIO(audio_content), 'session.txt'),
        'searchLimit': '2',
    }
    response = client.post('/api/post/process', data=data, content_type='multipart/form-data')
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    data = payload['data']

    assert 'transcript' in data and 'plan' in data and 'prompt' in data and 'mail' in data
    assert data['plan']['steps']
    assert isinstance(data['references'], list)
    assert len(data['references']) <= 2
    for ref in data['references']:
        assert 'title' in ref

    # Le mail final doit respecter la structure à deux parties
    mail = data['mail']
    assert "Ce que vous avez exprimé et ce que j'en ai compris" in mail
    assert "Pistes de lecture et repères" in mail
    assert "Bien à vous," in mail
    assert "Benjamin." in mail
    first_part, second_part = mail.split("Pistes de lecture et repères", 1)
    assert 500 <= _count_words(first_part) <= 900
    assert 250 <= _count_words(second_part) <= 500
    assert '# CONTEXTE' in data['prompt']

    # Les repères doivent rester valides
    lenses = data['research']['lenses_used']
    assert lenses


def test_process_missing_audio(client):
    response = client.post('/api/post/process', data={}, content_type='multipart/form-data')
    assert response.status_code == 400
    payload = response.get_json()
    assert payload['success'] is False
    assert payload['error'] == 'missing_audio'


def test_process_invalid_search_limit(client):
    audio_content = b"Discussion post-seance sur la douleur chronique."
    data = {
        'audio': (io.BytesIO(audio_content), 'session.txt'),
        'searchLimit': 'not-a-number',
    }
    response = client.post('/api/post/process', data=data, content_type='multipart/form-data')
    assert response.status_code == 400
    payload = response.get_json()
    assert payload['error'] == 'invalid_search_limit'


def test_process_unsupported_format(client):
    audio_content = b"not really an audio file"
    data = {
        'audio': (io.BytesIO(audio_content), 'session.flac'),
    }
    response = client.post('/api/post/process', data=data, content_type='multipart/form-data')
    assert response.status_code == 415
    payload = response.get_json()
    assert payload['error'] == 'unsupported_audio_format'


def test_validate_reperes_section_guardrails():
    sections = [
        {'title': 'Titre 1', 'body': 'mot ' * 130},
        {'title': 'Titre 2', 'body': 'mot ' * 130},
        {'title': 'Titre 3', 'body': 'mot ' * 130},
    ]
    logic.validate_reperes_section(sections)
    sections[0]['body'] = 'trop court'
    with pytest.raises(ValueError):
        logic.validate_reperes_section(sections)


def test_transcribe_endpoint(client):
    audio_content = b"Premiere consultation de suivi sur la gestion du stress."
    response = client.post(
        '/api/post/transcribe',
        data={'audio': (io.BytesIO(audio_content), 'session.txt')},
        content_type='multipart/form-data',
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    data = payload['data']
    assert data['transcript']
    assert isinstance(data['segments'], list)
    assert data['text_len'] == len(data['text'])
    assert data['text_sha256'] == hashlib.sha256(data['text'].encode('utf-8')).hexdigest()
    assert isinstance(data['transcript_url'], str)


def test_transcribe_accepts_binary_body(client):
    audio_content = (
        "Séance Opera envoyée en flux binaire pour valider le fallback serveur."
    ).encode('utf-8')
    response = client.post(
        '/api/post/transcribe?patient=opera-demo',
        data=audio_content,
        headers={
            'Content-Type': 'application/octet-stream',
            'X-File-Name': 'opera_demo.mp3',
        },
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload.get('ok') is True or payload.get('success') is True
    data = payload['data'] if isinstance(payload.get('data'), dict) else payload
    transcript = data.get('text') or data.get('transcript') or ''
    assert transcript.strip()
    if 'text_len' in data and 'text' in data:
        assert data['text_len'] == len(data['text'])
        assert data['text_sha256'] == hashlib.sha256(data['text'].encode('utf-8')).hexdigest()


def test_plan_research_and_prompt_endpoints(client):
    transcript_text = (
        "Séance d'accompagnement axée sur la fatigue chronique et l'organisation du quotidien."
        " La patiente souhaite clarifier les priorités et identifier les appuis concrets."
    )

    plan_resp = client.post('/api/post/plan', json={'transcript': transcript_text})
    assert plan_resp.status_code == 200
    plan_payload = plan_resp.get_json()['data']
    assert plan_payload['plan']
    assert plan_payload['context']

    research_resp = client.post(
        '/api/post/research',
        json={
            'transcript': transcript_text,
            'planContext': plan_payload['context'],
            'searchLimit': 2,
        },
    )
    assert research_resp.status_code == 200
    research_payload = research_resp.get_json()['data']
    assert isinstance(research_payload['results'], list)
    assert research_payload['context']

    prompt_resp = client.post(
        '/api/post/prompt',
        json={
            'transcript': transcript_text,
            'planContext': plan_payload['context'],
            'researchContext': research_payload['context'],
            'patientName': 'Alex',
            'useTu': True,
        },
    )
    assert prompt_resp.status_code == 200
    prompt_payload = prompt_resp.get_json()['data']
    assert "Ce que vous avez exprimé et ce que j'en ai compris" in prompt_payload['mail']
    assert prompt_payload['prompt']
    assert prompt_payload['planContext']
    assert prompt_payload['researchContext']


def test_mail_persists_artifacts_in_notes_post(monkeypatch, tmp_path, client):
    archive_root = tmp_path / 'archives' / 'jean-dupont'
    monkeypatch.setattr(post_session, 'resolve_patient_archive', lambda slug: archive_root)

    payload = {
        'transcript': 'Transcript de la séance',
        'plan': 'Plan de suivi détaillé',
        'historique': 'Historique complémentaire',
        'patient': 'jean-dupont',
        'base_name': 'Suivi Mai',
        'date': '20240131',
    }

    response = client.post('/api/post-session/mail', json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert data['ok'] is True

    notes_post_dir = archive_root / 'notes' / 'post'
    assert notes_post_dir.exists()

    expected_base = 'suivi-mai'
    transcript_path = notes_post_dir / f'{expected_base}_transcript.txt'
    plan_path = notes_post_dir / f'{expected_base}_plan.txt'
    mail_path = notes_post_dir / f'{expected_base}_mail.txt'

    assert transcript_path.read_text(encoding='utf-8') == 'Transcript de la séance'
    assert plan_path.read_text(encoding='utf-8') == 'Plan de suivi détaillé'
    mail_content = mail_path.read_text(encoding='utf-8')
    assert 'Ce que j’' in mail_content or 'Ce que j\u2019' in mail_content
