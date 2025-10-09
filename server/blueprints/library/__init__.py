"""Library blueprints package exposing historical routes and new helpers."""

from __future__ import annotations

from . import routes as _routes
from . import search_api as _search

bp = _routes.bp
library_ingest_bp = _routes.library_ingest_bp
search_bp = _search.bp

# Re-export public symbols from the submodules while avoiding blueprint shadowing.
for _name in getattr(_routes, "__all__", []):
    if _name in {"bp", "library_ingest_bp"}:
        continue
    globals()[_name] = getattr(_routes, _name)

for _name in getattr(_search, "__all__", []):
    if _name in {"bp", "search_bp"}:  # "bp" is already re-exported via ``search_bp`` above.
        continue
    globals()[_name] = getattr(_search, _name)

__all__ = [
    "bp",
    "library_ingest_bp",
    "search_bp",
    *[
        _name
        for _name in getattr(_routes, "__all__", [])
        if _name not in {"bp", "library_ingest_bp"}
    ],
    *[
        _name
        for _name in getattr(_search, "__all__", [])
        if _name not in {"bp", "search_bp"}
    ],
]
