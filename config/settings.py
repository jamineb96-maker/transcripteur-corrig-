"""Default application settings for local development."""
from __future__ import annotations

import os
from typing import List

# Network configuration
PORT: int = int(os.environ.get("PORT", "1421") or 1421)
HOST: str = os.environ.get("HOST", "127.0.0.1")

# Optional API base override for the frontend (relative by default)
API_BASE_RELATIVE: str = os.environ.get("API_BASE_RELATIVE", "")

# Allowed origins for CORS when serving the API locally
DEFAULT_ALLOWED_ORIGINS: List[str] = [
    "http://127.0.0.1:1421",
    "http://localhost:1421",
]

EXTRA_ALLOWED_ORIGINS = [origin.strip() for origin in os.environ.get("CORS_EXTRA_ORIGINS", "").split(",") if origin.strip()]
ALLOWED_ORIGINS: List[str] = DEFAULT_ALLOWED_ORIGINS + [origin for origin in EXTRA_ALLOWED_ORIGINS if origin not in DEFAULT_ALLOWED_ORIGINS]

# Debug flag mirrors Flask's convention ("1" enables debug mode)
FLASK_DEBUG_FLAG: str = os.environ.get("FLASK_DEBUG", "0")

# Recherche clinique (par défaut uniquement l'index local)
RESEARCH_WEB_ENABLED: bool = os.environ.get("RESEARCH_WEB_ENABLED", "0").strip().lower() not in {
    "",
    "0",
    "false",
    "no",
    "off",
}

# Garde-fous PII agressifs activés par défaut
PII_STRICT: bool = os.environ.get("PII_STRICT", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# Permet de réactiver les anciennes « pistes » si besoin
LEGACY_PITCHES: bool = os.environ.get("LEGACY_PITCHES", "0").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}

# [pipeline-v3 begin]
LIBRARY_DIR: str = os.environ.get("LIBRARY_DIR", "./library")
# [pipeline-v3 end]
