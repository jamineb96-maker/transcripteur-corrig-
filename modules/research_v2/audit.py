"""Audit trail pour la recherche pré-session v2."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

LOGGER_NAME = "presession.research"
LOG_DIR = Path("logs/research")
LOG_FILE = LOG_DIR / "sessions.log"


def configure_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_json(logger: logging.Logger, payload: Dict[str, Any]) -> None:
    logger.info(json.dumps(payload, ensure_ascii=False))


__all__ = ["configure_logger", "log_json", "LOGGER_NAME"]
