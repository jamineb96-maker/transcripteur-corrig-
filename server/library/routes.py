"""Routes de l'API pour la librairie.

Ce module définit un blueprint Flask qui expose des endpoints pour
interroger la librairie : état, recherche et récupération d'un item.
La logique d'indexation est déléguée au module `indexer`.
"""

from flask import Blueprint, request, jsonify
from . import indexer


# Création du blueprint
bp = Blueprint('library', __name__)


@bp.get('/status')
def library_status():
    """Renvoie des informations sur l'index de la librairie."""
    return jsonify({'success': True, 'data': indexer.status()})


@bp.get('/search')
def library_search():
    """Recherche des documents dans la librairie.

    Paramètres :
    * q : chaîne de recherche obligatoire
    * tags : liste de tags séparés par des virgules (optionnel)
    * limit : nombre maximum de résultats (optionnel, défaut : 10)
    """
    query = request.args.get('q', '')
    tags_param = request.args.get('tags')
    tags = []
    if tags_param:
        tags = [t.strip() for t in tags_param.split(',') if t.strip()]
    try:
        limit = int(request.args.get('limit', '10'))
    except Exception:
        limit = 10
    results = indexer.search(query, tags=tags, limit=limit)
    return jsonify({'success': True, 'data': results})


@bp.get('/item')
def library_item():
    """Renvoie un document complet par son identifiant.

    Paramètre :
    * id : chemin relatif du document dans `server/library/store`
    """
    doc_id = request.args.get('id')
    if not doc_id:
        return jsonify({'success': False, 'error': 'missing_id', 'message': 'Paramètre id manquant'}), 400
    item = indexer.get_item(doc_id)
    if not item:
        return jsonify({'success': False, 'error': 'not_found', 'message': 'Document introuvable'}), 404
    return jsonify({'success': True, 'data': item})