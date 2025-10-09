"""Blueprint registrations for the Flask application."""
from __future__ import annotations

import logging
from typing import Iterable, List

from flask import Blueprint

from server.tabs.agenda import api_bp as agenda_api, public_bp as agenda_public

from .budget import bp as budget_bp
from .documents_aide import bp as documents_aide_bp
from .invoices_svg import bp as invoices_svg_bp
from .journal_critique import bp as journal_critique_bp
from .library import bp as library_bp, library_ingest_bp, search_bp as library_search_bp
from .library_api import bp as library_api_v2_bp
from .patients import bp as patients_bp
from .patients_api import bp as patients_api_v2_bp
from .post_session import bp as post_session_legacy_bp
from .post_v2_api import bp as post_v2_api_bp
from .research_api import bp as research_api_bp
from .research_web import bp as research_web_bp
from .pre_session import bp as pre_session_bp
# [pipeline-v3 begin]
from .pipeline_v3 import bp as pipeline_v3_bp
# [pipeline-v3 end]
from server.tabs.anatomie3d import bp as anatomy3d_bp
from server.tabs.clinical_api import bp as clinical_api_bp
from server.tabs.post_session import bp as post_session_bp


LOGGER = logging.getLogger("assist.server")
LOGGER.info("pre_session blueprint chargé")


def get_blueprints() -> List[Blueprint]:
    """Return the list of blueprints to register on the Flask app."""

    return [
        patients_bp,
        patients_api_v2_bp,
        clinical_api_bp,
        pre_session_bp,
        # [pipeline-v3 begin]
        pipeline_v3_bp,
        # [pipeline-v3 end]
        post_session_legacy_bp,
        post_session_bp,
        post_v2_api_bp,
        research_api_bp,
        research_web_bp,
        budget_bp,
        journal_critique_bp,
        documents_aide_bp,
        anatomy3d_bp,
        library_bp,
        library_api_v2_bp,
        library_search_bp,
        library_ingest_bp,
        invoices_svg_bp,
        agenda_public,
        agenda_api,
    ]


__all__: Iterable[str] = ["get_blueprints"]
