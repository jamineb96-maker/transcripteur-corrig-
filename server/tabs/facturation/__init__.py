"""Initialisation du Blueprint pour l'onglet Facturation."""

from flask import Blueprint

bp = Blueprint('facturation', __name__)

from . import routes  # noqa: E402,F401