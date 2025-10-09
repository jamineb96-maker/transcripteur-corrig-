"""Utilities to generate deterministic identifiers for the library."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Union

BUFFER_SIZE = 1024 * 1024


def _hash_bytes(data: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(data)
    return digest.hexdigest()


def hash_file(path: Union[str, Path]) -> str:
    """Return the SHA256 hex digest of the given file."""
    digest = hashlib.sha256()
    with open(Path(path), "rb") as handle:
        while True:
            chunk = handle.read(BUFFER_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def generate_doc_id(title: str, authors: str, year: int, *, pdf_hash: str) -> str:
    """Create a deterministic doc_id from metadata and the PDF hash."""
    base = f"{title}|{authors}|{year}|{pdf_hash}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()[:24]


def generate_doc_id_from_file(title: str, authors: str, year: int, path: Union[str, Path]) -> str:
    """Convenience helper that reads a file and computes its deterministic doc_id."""
    return generate_doc_id(title, authors, year, pdf_hash=hash_file(path))


__all__ = [
    "generate_doc_id",
    "generate_doc_id_from_file",
    "hash_file",
]
