"""Initialisation du Blueprint pour l'onglet Pré‑séance."""

from flask import Blueprint

# Création du blueprint.  Le nom 'pre_session' sert d'identifiant unique.
bp = Blueprint('pre_session', __name__)

# Import des routes pour enregistrer les gestionnaires sur le blueprint.
from . import routes  # noqa: E402,F401