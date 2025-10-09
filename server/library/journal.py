"""Utilitaires de journalisation JSONL pour la bibliothèque clinique v2."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

LOGGER = logging.getLogger(__name__)


def _store_path() -> str:
    base = os.path.join(os.path.dirname(__file__), "store")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "journal.log")


def log_event(event: str, payload: Dict[str, Any]) -> None:
    """Écrit un événement JSON horodaté dans le journal dédié."""

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
    }
    record.update(payload)
    line = json.dumps(record, ensure_ascii=False)
    path = _store_path()
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        LOGGER.warning("journal_write_failed", extra={"error": str(exc), "event": event})
