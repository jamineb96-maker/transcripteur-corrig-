"""Load and expose the Za style profile for the post-session mega prompt."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

PROFILE_PATH = Path(__file__).with_name("style_profile.yaml")


@lru_cache(maxsize=1)
def _load_profile() -> Dict[str, Any]:
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(f"Missing style profile at {PROFILE_PATH}")
    with open(PROFILE_PATH, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):  # pragma: no cover - defensive
        raise ValueError("Invalid style profile payload")
    return data


def style_blocks() -> str:
    """Return a serialized style profile block for the mega prompt."""

    profile = _load_profile()
    return json.dumps(profile, ensure_ascii=False, indent=2)


__all__ = ["style_blocks"]
