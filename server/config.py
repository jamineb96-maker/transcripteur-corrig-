"""Chargement simple de la configuration à partir des variables d'environnement."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from .services.env import env


load_dotenv()


def getenv(key: str, default=None):
    """Expose un accès direct aux variables d'environnement."""

    return os.getenv(key, default)


def get_config() -> dict:
    """Retourne un dictionnaire de configuration basé sur les variables d'environnement."""

    return {
        'APP_PORT': env('APP_PORT', 1421),
        'FLASK_ENV': env('FLASK_ENV', 'development'),
        'SECRET_KEY': env('SECRET_KEY', 'dev-secret'),
        'GOOGLE_CLIENT_ID': env('GOOGLE_CLIENT_ID', ''),
        'GOOGLE_CLIENT_SECRET': env('GOOGLE_CLIENT_SECRET', ''),
        'GOOGLE_REDIRECT_URI': env('GOOGLE_REDIRECT_URI', ''),
        'POST_V2': env('POST_V2', 'false'),
        'RESEARCH_V2': env('RESEARCH_V2', 'false'),
        'USE_FAISS': env('USE_FAISS', 'false'),
        'ALLOW_FAKE_EMBEDS': env('ALLOW_FAKE_EMBEDS', 'false'),
        'RAG_WEB_PROVIDER': env('RAG_WEB_PROVIDER', 'none'),
        'RAG_WEB_ALLOWLIST': env('RAG_WEB_ALLOWLIST', 'server/research/allowlist.txt'),
        'RAG_WEB_MAX_RESULTS': env('RAG_WEB_MAX_RESULTS', 6),
        'RAG_WEB_RECENCY_DAYS': env('RAG_WEB_RECENCY_DAYS', 1095),
        'PROMPT_MAX_TOKENS_ESTIMATE': env('PROMPT_MAX_TOKENS_ESTIMATE', 180000),
    }


__all__ = ['get_config', 'getenv']