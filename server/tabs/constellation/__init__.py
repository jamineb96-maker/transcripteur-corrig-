"""Initialisation du Blueprint pour l'onglet Constellation."""

from flask import Blueprint

bp = Blueprint('constellation', __name__)

from . import routes  # noqa: E402,F401