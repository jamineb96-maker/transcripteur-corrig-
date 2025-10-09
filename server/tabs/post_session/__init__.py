"""Initialisation du Blueprint pour l'onglet Post‑séance."""

from flask import Blueprint

# Nom unique pour le blueprint
bp = Blueprint('post_session', __name__, url_prefix='/api/post')

# Import des routes afin d'enregistrer les endpoints sur le blueprint
from . import prompt_api  # noqa: E402,F401
from . import routes  # noqa: E402,F401

