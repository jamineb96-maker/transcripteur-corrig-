"""Blueprint pour l'onglet Journal critique."""

from flask import Blueprint

bp = Blueprint('journal_critique', __name__)

from . import routes  # noqa: E402,F401
