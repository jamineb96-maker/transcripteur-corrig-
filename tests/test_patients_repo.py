import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

pytest.importorskip('flask')

from server.services import patients_repo
from server.util.slug import slugify


@pytest.fixture()
def repo_env(tmp_path, monkeypatch):
    archives = tmp_path / 'archives'
    archives.mkdir(parents=True, exist_ok=True)
    patients_json = tmp_path / 'patients.json'
    monkeypatch.setattr(patients_repo, 'ARCHIVES_ROOT', archives)
    monkeypatch.setattr(patients_repo, 'PATIENTS_JSON_PATH', patients_json)
    monkeypatch.setattr(
        patients_repo,
        '_state',
        patients_repo.PatientsState(entries=[], source='archives', refreshed_at=0.0),
    )
    return archives, patients_json


def test_slugify_expected():
    assert slugify('Caroline Été') == 'caroline-ete'
    assert slugify('  Jean-Luc  ') == 'jean-luc'
    assert slugify('') == 'patient'


def test_scan_archives_merges_profiles(repo_env):
    archives, patients_json = repo_env

    caroline = archives / 'Caroline'
    caroline.mkdir()
    (caroline / 'profile.json').write_text(
        json.dumps(
            {
                'id': 'caroline',
                'display_name': 'Caroline Demo',
                'email': 'caroline@example.com',
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    charline = archives / 'Charline'
    charline.mkdir()

    nelle = archives / 'Nelle'
    nelle.mkdir()

    patients_json.write_text(
        json.dumps(
            [
                {
                    'id': 'charline',
                    'display_name': 'Charline Merge',
                    'email': 'charline@example.net',
                }
            ],
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    patients_repo.refresh()
    entries = patients_repo.list_patients()
    slugs = {entry['slug']: entry for entry in entries}

    assert set(slugs.keys()) >= {'caroline', 'charline', 'nelle'}
    assert slugs['caroline']['display_name'] == 'Caroline Demo'
    assert slugs['caroline']['email'] == 'caroline@example.com'
    assert slugs['charline']['display_name'] == 'Charline Merge'
    assert slugs['charline']['email'] == 'charline@example.net'
    assert slugs['nelle']['display_name'] == 'Nelle'
    assert patients_repo.get_state().source == 'archives'


def test_legacy_display_name_does_not_override_profile(repo_env):
    archives, patients_json = repo_env

    alex = archives / 'Alex'
    alex.mkdir()
    (alex / 'profile.json').write_text(
        json.dumps(
            {
                'id': 'alex',
                'display_name': 'Archive Preferred',
                'email': 'alex@example.com',
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    patients_json.write_text(
        json.dumps(
            [
                {
                    'id': 'alex',
                    'display_name': 'Legacy Override',
                    'phone': '123-456-7890',
                }
            ],
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    patients_repo.refresh()
    entries = patients_repo.list_patients()
    alex_entry = next(entry for entry in entries if entry['slug'] == 'alex')

    assert alex_entry['display_name'] == 'Archive Preferred'
    assert alex_entry['displayName'] == 'Archive Preferred'
    assert alex_entry['phone'] == '123-456-7890'


def test_api_patients_reports_archives_source(tmp_path, monkeypatch):
    from server import create_app

    archives = tmp_path / 'archives'
    archives.mkdir(parents=True, exist_ok=True)
    (archives / 'Caroline').mkdir()

    monkeypatch.setattr(patients_repo, 'ARCHIVES_ROOT', archives)
    monkeypatch.setattr(patients_repo, 'PATIENTS_JSON_PATH', tmp_path / 'patients.json')
    monkeypatch.setattr(
        patients_repo,
        '_state',
        patients_repo.PatientsState(entries=[], source='archives', refreshed_at=0.0),
    )

    app = create_app()
    app.config.update({'TESTING': True})

    with app.test_client() as client:
        response = client.get('/api/patients')
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['source'] == 'archives'
        assert isinstance(payload['patients'], list)
