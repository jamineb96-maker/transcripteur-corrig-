"""Initialisation du blueprint Budget cognitif."""

from flask import Blueprint

bp = Blueprint('budget', __name__)

from . import routes  # noqa: E402,F401
