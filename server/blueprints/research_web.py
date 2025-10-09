"""Blueprint exposing a simple web search API.

This blueprint defines a single endpoint used by the client to
perform generic web searches.  It delegates to the helper
``server.research.web_search`` which supports DuckDuckGo, SerpAPI
and Bing based on environment configuration.  The endpoint is
read‑only (GET) and always returns a JSON payload containing at
least the ``provider`` (the resolved search provider), a
``results`` list and an optional ``error`` string.
"""

from __future__ import annotations

import os
from flask import Blueprint, jsonify, request

from server.research.web_search import search as perform_search


bp = Blueprint("research_web_api", __name__, url_prefix="/api/research")


@bp.get("/web")
def web_search() -> tuple:
    """Handle HTTP GET requests to perform a web search.

    Expected query parameters:

    * ``q`` (or ``query``): the search terms (required).
    * ``lang``: optional ISO language code (defaults to ``fr``).
    * ``max``: optional maximum number of results (defaults to ``5``).

    The returned JSON always includes the resolved provider name in
    the ``provider`` field, a ``results`` list of dictionaries and
    ``ok`` set to ``True``.  In case of unexpected errors a
    best‑effort response is returned with ``results`` empty and
    ``ok`` set to ``False`` and an ``error`` string for debugging.
    """
    query = request.args.get("q") or request.args.get("query") or ""
    lang = request.args.get("lang", "fr").strip() or "fr"
    raw_max = request.args.get("max") or request.args.get("limit") or "5"
    try:
        max_results = max(1, int(raw_max))
    except (TypeError, ValueError):
        max_results = 5
    provider = (os.getenv("SEARCH_PROVIDER") or "ddg").strip().lower()
    try:
        results = perform_search(query, lang=lang, max_results=max_results)
        return jsonify({"ok": True, "provider": provider, "results": results})
    except Exception as exc:  # pragma: no cover - defensive fallback
        return (
            jsonify(
                {
                    "ok": False,
                    "provider": provider,
                    "results": [],
                    "error": str(exc),
                }
            ),
            200,
        )


__all__ = ["bp"]