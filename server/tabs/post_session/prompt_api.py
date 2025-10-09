"""Endpoint REST pour la composition du prompt post-séance."""

from __future__ import annotations

import logging
from typing import Any, Dict

from flask import jsonify, request

from server.services.prompt_composer import (
    DEFAULT_MAX_TOKENS,
    PromptComposer,
    PromptComposerError,
)

from . import bp

LOGGER = logging.getLogger("post_session.prompt_api")

_COMPOSER = PromptComposer()


def _error_response(code: str, message: str, status: int = 400):
    payload = {"success": False, "error": code, "message": message}
    return jsonify(payload), status


@bp.post("/prompt/compose")
def compose_prompt():
    """Compose un prompt prêt à coller selon les préférences transmises."""

    payload: Dict[str, Any] = request.get_json(silent=True) or {}

    slug = payload.get("slug")
    window = payload.get("window") if isinstance(payload.get("window"), dict) else None
    topics = payload.get("topics") if isinstance(payload.get("topics"), list) else None
    include = payload.get("include") if isinstance(payload.get("include"), dict) else None
    max_tokens = payload.get("max_tokens")
    strict = payload.get("attribution_strict", True)

    try:
        max_tokens_value = int(max_tokens) if max_tokens is not None else DEFAULT_MAX_TOKENS
    except (TypeError, ValueError):
        return _error_response("invalid_max_tokens", "Le paramètre max_tokens doit être un entier.")

    try:
        result = _COMPOSER.compose(
            slug=str(slug or "").strip(),
            window=window,
            topics=topics,
            include=include,
            max_tokens=max_tokens_value,
            strict_attribution=bool(strict),
        )
    except PromptComposerError as exc:
        message = str(exc) or "Impossible de composer le prompt."
        return _error_response(exc.code, message, 400)
    except Exception:  # pragma: no cover - garde
        LOGGER.exception("[post-session] prompt compose failed")
        return _error_response("unexpected_error", "Erreur lors de la composition du prompt.", 500)

    response = {"success": True, "data": result}
    return jsonify(response)

