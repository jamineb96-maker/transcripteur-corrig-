"""Routes pour l'onglet Pré‑séance.

Ce module définit les endpoints JSON exposés pour le tab Pre‑séance.  Un
point de test `/ping` renvoie un simple message et un point `/generate`
permet de générer un bref texte à partir des contextes soumis par le
client.
"""

from flask import request, jsonify
from . import bp
from .logic import generate_brief


@bp.get('/ping')
def ping():
    """Test rapide du fonctionnement du blueprint."""
    return jsonify({'success': True, 'data': 'pre-pong'})


@bp.post('/generate')
def generate():
    """Génère un bref texte à partir des contextes envoyés par le client.

    Le client doit envoyer un JSON avec une clé ``prompt`` (objet) ou, par
    rétrocompatibilité, ``contexts`` (liste de chaînes) et une clé
    optionnelle ``params`` (objet).  La réponse contient un objet ``data``
    avec la clé ``brief``.
    """
    payload = request.get_json(silent=True) or {}
    prompt = payload.get('prompt')
    if prompt is None and 'contexts' in payload:
        prompt = payload.get('contexts', [])
    params = payload.get('params', {})
    brief = generate_brief(prompt, params)
    return jsonify({'success': True, 'data': {'brief': brief}})
