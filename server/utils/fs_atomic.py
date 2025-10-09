"""Outils d'écriture atomique pour la bibliothèque."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Callable

from .docid import ensure_dir

Writer = Callable[[Path], None]


def _prepare_tmp_path(target: Path) -> Path:
    """Retourne un chemin temporaire dans ``tmp`` pour une écriture atomique."""

    final_path = Path(target)
    parent = ensure_dir(final_path.parent)
    tmp_dir = ensure_dir(parent / "tmp")
    tmp_name = f"{final_path.name}.{uuid.uuid4().hex}.tmp"
    return tmp_dir / tmp_name


def atomic_write(path: Path | str, writer: Writer) -> Path:
    """Écrit un fichier de manière atomique en utilisant ``os.replace``."""

    final_path = Path(path)
    tmp_path = _prepare_tmp_path(final_path)
    writer(tmp_path)
    os.replace(tmp_path, final_path)
    return final_path


def atomic_write_text(path: Path | str, data: str, *, encoding: str = "utf-8") -> Path:
    """Écrit du texte de manière atomique."""

    def _writer(tmp_path: Path) -> None:
        tmp_path.write_text(data, encoding=encoding)

    return atomic_write(path, _writer)


def atomic_write_bytes(path: Path | str, data: bytes) -> Path:
    """Écrit des octets de manière atomique."""

    def _writer(tmp_path: Path) -> None:
        tmp_path.write_bytes(data)

    return atomic_write(path, _writer)
