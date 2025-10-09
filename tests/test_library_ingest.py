"""Tests unitaires pour le module d'ingestion de la bibliothèque."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(Path(__file__).resolve().parents[1]))

pytest.importorskip("pdfminer.high_level")

from modules.library_ingest import compute_doc_hash, extract_text, segment_pages

try:  # pragma: no cover - dépendance optionnelle
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except ModuleNotFoundError:  # pragma: no cover - tests skip si indisponible
    canvas = None  # type: ignore


@pytest.mark.skipif(canvas is None, reason="reportlab manquant")
def test_extract_text_marks_textual_pages_without_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.drawString(100, 700, "Page 1: Bonjour Bibliothèque")
    c.showPage()
    c.drawString(100, 700, "Page 2: Deuxième page")
    c.save()

    pages = extract_text(pdf_path)
    assert len(pages) == 2
    assert pages[0]["page"] == 1
    assert "Bonjour Bibliothèque" in pages[0]["text"]
    assert pages[0]["has_ocr"] is False


def test_compute_doc_hash_stable() -> None:
    payload = b"bonjour"
    hash_a = compute_doc_hash(payload)
    hash_b = compute_doc_hash(payload)
    assert hash_a == hash_b
    assert hash_a.startswith("sha256:")


def test_segment_pages_covers_pages_without_overlap() -> None:
    pages = [
        {"page": 1, "text": "mot " * 300},
        {"page": 2, "text": "mot " * 400},
        {"page": 3, "text": "mot " * 350},
    ]
    segments = segment_pages(pages, target_tokens=500)
    assert segments, "Des segments doivent être produits"
    covered = []
    for seg in segments:
        start, end = seg["pages"]
        assert start <= end
        covered.extend(range(start, end + 1))
    assert sorted(set(covered)) == [1, 2, 3]
    # Vérifie l'absence de chevauchement via l'unicité des pages couvertes
    assert len(covered) == len(set(covered))

