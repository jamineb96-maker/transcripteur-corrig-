"""Initialisation des blueprints pour l'onglet Agenda."""

from flask import Blueprint

# Blueprint exposant les routes publiques sous /agenda
public_bp = Blueprint('agenda_public', __name__, url_prefix="/agenda")

# Blueprint exposant les routes d'API sous /api/agenda
api_bp = Blueprint('agenda_api', __name__, url_prefix="/api/agenda")

from . import routes  # noqa: E402,F401
