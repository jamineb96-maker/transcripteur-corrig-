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


def test_unregister_sw_script_served(client):
    response = client.get('/static/unregister-sw.js')
    assert response.status_code == 200
    assert 'javascript' in response.content_type
    payload = response.get_data(as_text=True)
    assert 'unregister-sw' in payload


def test_index_references_unregister_sw(client):
    response = client.get('/')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/static/unregister-sw.js" in html
