"""Routes de base pour l'onglet Constellation."""

from flask import jsonify
from . import bp


@bp.get('/ping')
def ping():
    """Endpoint de test renvoyant un message simple."""
    return jsonify({'success': True, 'data': 'constellation-pong'})