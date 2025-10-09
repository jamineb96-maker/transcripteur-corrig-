"""Utilities to repair and load JSON payloads returned by the LLM."""
from __future__ import annotations

import json
import logging
import re
from typing import Dict

LOGGER = logging.getLogger(__name__)

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_PYTHON_LITERAL_RE = re.compile(r"(?<![\w\"])(True|False|None)(?![\w\"])")

_TRANSLATION_TABLE = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "’": "'",
        "‘": "'",
    }
)


def strip_code_fences(raw: str) -> str:
    """Remove Markdown code fences surrounding the payload if present."""

    if not raw:
        return ""
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def _normalise_quotes(text: str) -> str:
    return text.translate(_TRANSLATION_TABLE)


def _strip_trailing_commas(text: str) -> str:
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _replace_python_literals(text: str) -> str:
    def _convert(match: re.Match[str]) -> str:
        token = match.group(1)
        if token == "True":
            return "true"
        if token == "False":
            return "false"
        return "null"

    return _PYTHON_LITERAL_RE.sub(_convert, text)


def lenient_json_loads(raw: str) -> Dict[str, object]:
    """Load a JSON object after applying safe, incremental repairs."""

    text = strip_code_fences(raw)
    text = text.lstrip("\ufeff").strip()
    if not text:
        raise ValueError("empty_json")

    errors: list[str] = []

    def _attempt(candidate: str, label: str):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:  # pragma: no cover - dépend du contenu
            errors.append(f"{label}: {exc.msg} (line {exc.lineno} col {exc.colno})")
            return None
        if not isinstance(payload, dict):
            errors.append(f"{label}: root_is_not_object")
            return None
        if label != "original" and LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug("llm_json_repaired", extra={"step": label, "preview": candidate[:200]})
        return payload

    candidate = text
    parsed = _attempt(candidate, "original")
    if parsed is not None:
        return parsed

    for label, transformer in (
        ("normalize_quotes", _normalise_quotes),
        ("strip_trailing_commas", _strip_trailing_commas),
        ("python_literals", _replace_python_literals),
    ):
        candidate = transformer(candidate)
        parsed = _attempt(candidate, label)
        if parsed is not None:
            return parsed

    raise ValueError("; ".join(errors) if errors else "unparsable_json")


__all__ = ["strip_code_fences", "lenient_json_loads"]
