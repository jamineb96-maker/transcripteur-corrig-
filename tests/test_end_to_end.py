import json
from pathlib import Path

import pytest

from server.__init__ import create_app


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    # Use temporary directories for uploads and archives
    tmpdir = tmp_path_factory.mktemp('api')
    upload_dir = tmpdir / 'uploads'
    archive_dir = tmpdir / 'archives'
    app = create_app(upload_dir=str(upload_dir), archive_dir=str(archive_dir))
    app.testing = True
    return app.test_client()


def test_post_session_json(client):
    transcript = "Je rencontre des difficultés au travail et nous avons discuté des ressources disponibles."
    payload = {"transcript": transcript, "prenom": "Bob", "register": "vous"}
    res = client.post('/post_session', data=json.dumps(payload), content_type='application/json')
    assert res.status_code == 200
    data = res.get_json()
    assert data['plan']
    assert data['analysis']
    assert data['mail']
    assert data['artifacts']
    # Les artefacts retournés doivent avoir des chemins valides
    for key, rel_path in data['artifacts'].items():
        assert isinstance(rel_path, str) and len(rel_path) > 0
        assert rel_path.count('/') >= 1  # contient au moins un séparateur indiquant sous‑dossier