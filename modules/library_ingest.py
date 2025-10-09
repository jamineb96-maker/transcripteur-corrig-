"""Outils d'ingestion des documents PDF pour l'onglet Bibliothèque."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import re
from dataclasses import dataclass
from typing import Iterable, Iterator, List, Sequence

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

from server.library.store.manifest import (
    ensure_manifest,
    resolve_extraction_dir,
    update_manifest,
)
from server.utils.docid import ensure_dir, parse_doc_id
from server.utils.fs_atomic import atomic_write

LOGGER = logging.getLogger(__name__)

try:  # pragma: no cover - dépendances optionnelles
    import pypdfium2 as pdfium
except ModuleNotFoundError:  # pragma: no cover - fallback
    pdfium = None  # type: ignore

try:  # pragma: no cover - dépendances optionnelles
    import pytesseract
except ModuleNotFoundError:  # pragma: no cover - fallback
    pytesseract = None  # type: ignore

try:  # pragma: no cover - dépendances optionnelles
    from PIL import Image
except ModuleNotFoundError:  # pragma: no cover - fallback
    Image = None  # type: ignore


TOKEN_SPLITTER = re.compile(r"\s+")


@dataclass(slots=True)
class PageExtraction:
    """Représentation typée d'une page extraite."""

    page: int
    text: str
    has_ocr: bool

    def to_dict(self) -> dict:
        return {"page": self.page, "text": self.text, "has_ocr": self.has_ocr}


class InvalidDocumentId(ValueError):
    """Erreur métier déclenchée lorsque le doc_id est invalide."""


def compute_doc_hash(file_bytes: bytes) -> str:
    """Calcule un identifiant stable basé sur SHA256."""

    if not isinstance(file_bytes, (bytes, bytearray)):
        raise TypeError("file_bytes must be bytes-like")
    digest = hashlib.sha256(bytes(file_bytes)).hexdigest()
    return f"sha256:{digest}"


def _iter_text_chunks(layout) -> Iterator[str]:
    for element in layout:
        if isinstance(element, LTTextContainer):
            yield element.get_text()


def _clean_text(text: str) -> str:
    cleaned = text.replace("\x0c", "\n")
    cleaned = cleaned.replace("\r", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _perform_ocr(pdf_path: Path, page_index: int) -> str:
    if not (pdfium and pytesseract and Image):  # pragma: no cover - dépendances optionnelles
        return ""
    try:
        document = pdfium.PdfDocument(str(pdf_path))
    except Exception as exc:  # pragma: no cover - dépendances optionnelles
        LOGGER.warning("OCR fallback indisponible : %s", exc)
        return ""
    try:
        page = document.get_page(page_index)
        bitmap = page.render(scale=2)
        pil_image = bitmap.to_pil() if hasattr(bitmap, "to_pil") else None
        if pil_image is None and hasattr(bitmap, "to_pil_image"):
            pil_image = bitmap.to_pil_image()
        if pil_image is None:
            return ""
        text = pytesseract.image_to_string(pil_image)  # type: ignore[arg-type]
        return _clean_text(text)
    except Exception as exc:  # pragma: no cover - dépendances optionnelles
        LOGGER.warning("OCR échoué pour page %s : %s", page_index + 1, exc)
        return ""
    finally:
        try:
            document.close()
        except AttributeError:  # pragma: no cover - compatibilité
            pass


def extract_text(pdf_path: Path | str) -> List[dict]:
    """Extrait le texte page par page avec fallback OCR si nécessaire."""

    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF introuvable : {pdf_path}")

    pages: List[PageExtraction] = []
    for page_index, layout in enumerate(extract_pages(str(path)), start=1):
        text_chunks = list(_iter_text_chunks(layout))
        text = _clean_text("".join(text_chunks))
        has_ocr = False
        if not text:
            ocr_text = _perform_ocr(path, page_index - 1)
            if ocr_text:
                text = ocr_text
                has_ocr = True
        pages.append(PageExtraction(page=page_index, text=text, has_ocr=has_ocr))
    return [page.to_dict() for page in pages]


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(TOKEN_SPLITTER.split(text.strip()))


def segment_pages(pages: Iterable[dict], target_tokens: int = 1000) -> List[dict]:
    """Assemble des segments de 800 à 1200 tokens à partir des pages extraites."""

    target_tokens = max(200, int(target_tokens or 1000))
    pages_list = [page for page in pages if isinstance(page, dict)]
    segments: List[dict] = []
    buffer_text: List[str] = []
    buffer_pages: List[int] = []
    token_count = 0

    def flush_segment(index: int) -> None:
        nonlocal buffer_text, buffer_pages, token_count
        if not buffer_text:
            return
        text = "\n\n".join(buffer_text).strip()
        if not text:
            buffer_text = []
            buffer_pages = []
            token_count = 0
            return
        segments.append(
            {
                "segment_id": f"seg_{index:03d}",
                "pages": [buffer_pages[0], buffer_pages[-1]],
                "text": text,
                "token_estimate": _estimate_tokens(text),
            }
        )
        buffer_text = []
        buffer_pages = []
        token_count = 0

    segment_index = 0
    for page in pages_list:
        page_number = int(page.get("page", 0) or 0)
        text = str(page.get("text", ""))
        if not page_number or not text.strip():
            continue
        page_tokens = _estimate_tokens(text)
        if not buffer_text:
            buffer_pages = [page_number]
        else:
            buffer_pages.append(page_number)
        buffer_text.append(text.strip())
        token_count += page_tokens
        if token_count >= target_tokens and page_tokens > 0:
            flush_segment(segment_index)
            segment_index += 1
    flush_segment(segment_index)

    return segments


def persist_extraction(
    doc_id: str,
    pages: Sequence[dict],
    segments: Sequence[dict],
    *,
    extracted_root: Path | None = None,
    shard: bool = True,
    source_filename: str | None = None,
    file_size_bytes: int | None = None,
    tags: Sequence[str] | None = None,
    options: dict | None = None,
    feature_v2: bool = True,
) -> Path:
    """Enregistre l'extraction sur disque via le schéma de mapping v2."""

    if not doc_id or not isinstance(doc_id, str):
        raise InvalidDocumentId("doc_id manquant ou invalide")

    try:
        parse_doc_id(doc_id)
    except ValueError as exc:  # pragma: no cover - validation explicite
        raise InvalidDocumentId(str(exc)) from exc

    pages_list = list(pages)
    segments_list = list(segments)

    root = Path(extracted_root) if extracted_root else Path("library") / "extracted"
    ensure_dir(root)
    target_dir = resolve_extraction_dir(root, doc_id, shard=shard, feature_v2=feature_v2)

    pages_dir = ensure_dir(target_dir / "pages")
    segments_path = target_dir / "segments.jsonl"
    pages_path = pages_dir / "pages.jsonl"

    def _write_jsonl(path: Path, items: Iterable[dict]) -> None:
        payload = list(items)

        def _writer(tmp_path: Path) -> None:
            with tmp_path.open("w", encoding="utf-8") as handle:
                for item in payload:
                    handle.write(json.dumps(item, ensure_ascii=False))
                    handle.write("\n")

        atomic_write(path, _writer)

    _write_jsonl(pages_path, pages_list)
    _write_jsonl(segments_path, segments_list)

    ensure_manifest(
        doc_id,
        target_dir,
        source_filename=source_filename,
        file_size_bytes=file_size_bytes,
    )
    manifest_updates = {
        "tags": list(tags or []),
        "options": options or {},
        "pages": len(pages_list),
        "segments": len(segments_list),
    }
    update_manifest(target_dir, manifest_updates)
    LOGGER.debug(
        "persist_extraction",
        extra={
            "doc_id": doc_id,
            "fs_path": str(target_dir),
            "pages": len(pages_list),
            "segments": len(segments_list),
        },
    )
    return target_dir


__all__ = [
    "compute_doc_hash",
    "extract_text",
    "segment_pages",
    "persist_extraction",
    "InvalidDocumentId",
]
