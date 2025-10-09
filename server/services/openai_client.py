"""Gestion centralisée du client OpenAI.

Ce module expose des helpers pour initialiser le client OpenAI en tenant
compte d'un éventuel déploiement Azure et fournit des fonctions utilitaires
pour vérifier la disponibilité du service.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

try:  # pragma: no cover - dépendance optionnelle
    from openai import OpenAI
except Exception:  # pragma: no cover - absence de la dépendance
    OpenAI = None  # type: ignore[misc, assignment]


DEFAULT_TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini")
#
# NOTE : Par défaut, ce projet utilisait le modèle « gpt‑4o‑mini‑transcribe » pour la
# transcription audio. Ce modèle offre des performances intéressantes sur de
# petits enregistrements mais son API limite la durée d’analyse à quelques
# minutes (environ huit), ce qui entraînait des transcriptions tronquées des
# séances longues. De nombreux utilisateurs ont constaté que la
# transcription s’arrêtait prématurément alors que l’intégralité du fichier
# devait être traitée. Pour contourner ce problème sans complexifier le
# pipeline, le modèle par défaut est désormais « whisper-1 ». Whisper est
# particulièrement adapté à la transcription longue et accepte des fichiers
# significativement plus volumineux (jusqu’à 25 Mo sur l’API OpenAI). Si vous
# souhaitez revenir au comportement précédent, définissez explicitement
# l’environnement OPENAI_ASR_MODEL.

DEFAULT_ASR_MODEL = os.getenv("OPENAI_ASR_MODEL", "whisper-1")
FALLBACK_ASR_MODEL = "gpt-4o-mini-transcribe"


LOGGER = logging.getLogger("assist.services.openai")


def _build_openai_client() -> Optional["OpenAI"]:  # pragma: no cover - dépend du réseau
    if OpenAI is None:
        LOGGER.debug("Bibliothèque openai non disponible, client désactivé")
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        api_type = (os.getenv("OPENAI_API_TYPE") or "").strip().lower()
        if api_type == "azure":
            base_url = os.environ["OPENAI_API_BASE"]
            return OpenAI(api_key=api_key, base_url=base_url)
        return OpenAI(api_key=api_key)
    except KeyError:
        LOGGER.warning(
            "OPENAI_API_BASE manquante alors que OPENAI_API_TYPE=azure est défini", extra={"api_type": "azure"}
        )
    except Exception as exc:
        LOGGER.warning("Impossible d'initialiser le client OpenAI: %s", exc, exc_info=True)
    return None


@lru_cache(maxsize=1)
def get_openai_client() -> Optional["OpenAI"]:
    """Retourne une instance partagée du client OpenAI ou `None` si indisponible."""

    return _build_openai_client()


def refresh_openai_client() -> Optional["OpenAI"]:
    """Réinitialise le cache et tente de reconstruire un client OpenAI."""

    try:
        get_openai_client.cache_clear()  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover - compatibilité anciennes versions
        pass
    return get_openai_client()


def is_openai_configured() -> bool:
    """Indique si une clé OpenAI est présente dans l'environnement."""

    return bool(os.getenv("OPENAI_API_KEY"))


def check_openai_health() -> bool:
    """Effectue un ping léger de l'API OpenAI pour vérifier sa disponibilité."""

    client = get_openai_client()
    if client is None:
        return False

    try:  # pragma: no cover - dépendance externe
        client.models.list()
        return True
    except Exception as exc:
        status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if status in {400, 404}:  # La requête a atteint l'API mais la ressource n'existe pas
            LOGGER.debug("Ping OpenAI reçu avec statut %s (considéré comme disponible)", status)
            return True
        LOGGER.debug("Ping OpenAI échoué: %s", exc, exc_info=True)
        return False


__all__ = [
    "DEFAULT_ASR_MODEL",
    "DEFAULT_TEXT_MODEL",
    "FALLBACK_ASR_MODEL",
    "check_openai_health",
    "get_openai_client",
    "is_openai_configured",
    "refresh_openai_client",
]

