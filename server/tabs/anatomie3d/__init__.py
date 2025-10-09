"""Initialisation du Blueprint pour l'onglet Anatomie 3D."""

from flask import Blueprint

bp = Blueprint("anatomie3d", __name__, url_prefix="/anatomy3d")

from . import routes  # noqa: E402,F401
