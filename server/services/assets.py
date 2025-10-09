"""Utilities for computing and exposing the static asset version.

The agenda front-end relies on cache busting for dynamically imported
modules.  This helper centralises the logic that determines the asset
version so both the server templates and the client-side router can stay
in sync.  The logic favours an explicit environment variable when
present, falls back to a hash of the Post‑séance bundle and finally to a
timestamp so that the value always changes between deployments.
"""

from __future__ import annotations

import hashlib
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CLIENT_ROOT = _PROJECT_ROOT / "client"

_POST_SESSION_FILES: Sequence[Path] = (
    Path("app.js"),
    Path("tabs") / "post_session" / "index.js",
    Path("tabs") / "post_session" / "view.html",
    Path("tabs") / "post_session" / "style.css",
)


def _hash_paths(base: Path, paths: Iterable[Path]) -> str | None:
    """Return a short SHA1 hash for the concatenated contents of *paths*."""

    hasher = hashlib.sha1()
    found_any = False
    for relative in paths:
        candidate = base / relative
        try:
            data = candidate.read_bytes()
        except FileNotFoundError:
            continue
        hasher.update(data)
        found_any = True
    if not found_any:
        return None
    return hasher.hexdigest()[:12]


@lru_cache(maxsize=1)
def get_asset_version(static_dir: str | Path | None = None) -> str:
    """Return the asset version used for cache busting.

    Priority order:
    1. Explicit ``ASSET_VERSION`` environment variable.
    2. Hash of ``client/app.js`` when available.
    3. Timestamp based fallback.
    """

    env_version = os.getenv("ASSET_VERSION")
    if env_version:
        return env_version

    base_dir = Path(static_dir) if static_dir else _CLIENT_ROOT
    hashed = _hash_paths(base_dir, _POST_SESSION_FILES)
    if hashed:
        return hashed

    return time.strftime("%Y%m%d%H%M%S")


def detect_tab_duplicates(static_dir: str | Path) -> list[str]:
    """Detect duplicated tab directories under ``client/static``.

    Returns a sorted list of tab folder names present both in
    ``client/tabs/<name>`` and ``client/static/tabs/<name>``.
    """

    base = Path(static_dir)
    canonical_root = base / "tabs"
    duplicate_root = base / "static" / "tabs"
    if not canonical_root.exists() or not duplicate_root.exists():
        return []
    duplicates: list[str] = []
    for entry in canonical_root.iterdir():
        if not entry.is_dir():
            continue
        if (duplicate_root / entry.name).is_dir():
            duplicates.append(entry.name)
    return sorted(duplicates)


__all__ = ["get_asset_version", "detect_tab_duplicates"]

