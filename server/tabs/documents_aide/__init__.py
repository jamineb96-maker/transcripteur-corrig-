"""Blueprint pour l'onglet Documents d'aide."""

from flask import Blueprint

bp = Blueprint('documents_aide', __name__, url_prefix='/api/documents-aide')

from . import routes  # noqa: E402,F401
