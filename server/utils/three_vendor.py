"""Helpers pour s'assurer que les assets Three.js critiques sont présents."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def ensure_draco_decoder(static_root: str | Path) -> Path | None:
    """Génère ``draco_decoder.wasm`` à partir de la sauvegarde base64 si nécessaire."""

    base = Path(static_root) / "vendor" / "three" / "examples" / "jsm" / "libs" / "draco"
    wasm_path = base / "draco_decoder.wasm"
    if wasm_path.exists():
        return wasm_path
    base64_path = base / "draco_decoder.wasm.base64"
    if not base64_path.exists():
        LOGGER.warning("draco_decoder.wasm manquant et aucun export base64 disponible")
        return None
    try:
        data = base64.b64decode(base64_path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - logging uniquement
        LOGGER.warning("Décodage base64 impossible pour draco_decoder.wasm: %s", exc)
        return None
    try:
        base.mkdir(parents=True, exist_ok=True)
        wasm_path.write_bytes(data)
    except OSError as exc:  # pragma: no cover - logging uniquement
        LOGGER.warning("Écriture impossible pour draco_decoder.wasm: %s", exc)
        return None
    return wasm_path
