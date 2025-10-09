import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.services.invoicing import (
    InvoiceNumberCollisionError,
    InvoicingService,
)


@pytest.fixture()
def invoicing_service(tmp_path):
    return InvoicingService(tmp_path)


def test_invoice_totals_status_and_manual_collision(tmp_path):
    service = InvoicingService(tmp_path)

    lines = [
        {"description": "Consultation", "quantity": 2, "unit_price": 50, "vat_rate": 0.2},
        {"description": "Déplacement", "quantity": 1, "unit_price": 30, "vat_rate": 0.1},
        {"description": "Supplément", "quantity": 3, "unit_price": 15.5, "vat_rate": 0.055},
    ]

    invoice = service.create_invoice(
        patient_id="patient-001",
        lines=lines,
        invoice_date=date(2025, 3, 15),
    )

    totals = invoice["totals"]
    assert totals["ht"] == pytest.approx(176.50, abs=0.01)
    assert totals["tva"] == pytest.approx(25.56, abs=0.01)
    assert totals["ttc"] == pytest.approx(202.06, abs=0.01)

    # Chaque ligne doit inclure les montants calculés
    assert invoice["lines"][0]["amounts"]["ht"] == pytest.approx(100.0, abs=0.01)
    assert invoice["lines"][0]["amounts"]["ttc"] == pytest.approx(120.0, abs=0.01)

    # Stockage et persistance du statut payé
    service.mark_paid(invoice["number"])
    persisted = InvoicingService(tmp_path).get_invoice(invoice["number"])
    assert persisted["status"] == "paid"

    manual_invoice = service.create_invoice(
        patient_id="patient-002",
        lines=lines,
        invoice_date=date(2025, 4, 1),
        manual_number="FAC-2025-0001",
    )
    assert manual_invoice["number"] == "FAC-2025-0001"

    with pytest.raises(InvoiceNumberCollisionError):
        service.create_invoice(
            patient_id="patient-003",
            lines=lines,
            invoice_date=date(2025, 4, 20),
            manual_number="FAC-2025-0001",
        )


def test_pdf_generation_pipeline_success_and_fallback(tmp_path):
    output_dir = tmp_path / "pdfs"

    created_paths = {}

    def libreoffice_converter(invoice, target):
        path = Path(target)
        path.write_bytes(b"%PDF-1.4\n" + b"0" * 3000)
        created_paths["libreoffice"] = path
        return path

    fallback_called = {"value": False}

    def reportlab_generator(invoice, target):
        fallback_called["value"] = True
        path = Path(target)
        path.write_bytes(b"%PDF-1.4\n" + b"1" * 4096)
        return path

    service = InvoicingService(
        tmp_path,
        libreoffice_converter=libreoffice_converter,
        reportlab_generator=reportlab_generator,
    )

    invoice = service.create_invoice(
        patient_id="patient-pdf",
        lines=[{"description": "Séance", "quantity": 1, "unit_price": 60, "vat_rate": 0.2}],
    )

    pdf_path = service.generate_pdf(invoice["number"], output_dir)
    assert pdf_path.exists()
    assert pdf_path in created_paths.values()
    assert fallback_called["value"] is False

    # Échec LibreOffice -> repli ReportLab et taille minimale > 2 Ko
    def failing_libreoffice(_invoice, _target):
        raise RuntimeError("conversion error")

    fallback_calls = {"count": 0}

    def fallback(invoice, target):
        fallback_calls["count"] += 1
        path = Path(target)
        path.write_bytes(b"%PDF-1.4\n" + b"2" * 3000)
        return path

    failing_service = InvoicingService(
        tmp_path,
        libreoffice_converter=failing_libreoffice,
        reportlab_generator=fallback,
    )

    failing_invoice = failing_service.create_invoice(
        patient_id="patient-pdf-2",
        lines=[{"description": "Séance", "quantity": 1, "unit_price": 70, "vat_rate": 0.2}],
    )

    fallback_pdf = failing_service.generate_pdf(failing_invoice["number"], output_dir)
    assert fallback_calls["count"] == 1
    assert fallback_pdf.stat().st_size > 2048


def test_auto_counter_across_years(tmp_path):
    service = InvoicingService(tmp_path)

    invoice_2024 = service.create_invoice(
        patient_id="patient-2024",
        lines=[{"description": "Séance", "quantity": 1, "unit_price": 50, "vat_rate": 0.2}],
        invoice_date=date(2024, 12, 15),
    )
    invoice_2025 = service.create_invoice(
        patient_id="patient-2025",
        lines=[{"description": "Séance", "quantity": 1, "unit_price": 65, "vat_rate": 0.2}],
        invoice_date=date(2025, 1, 5),
    )

    assert invoice_2024["number"].startswith("2024-")
    assert invoice_2025["number"].startswith("2025-")
    assert invoice_2024["number"] != invoice_2025["number"]

    # Rechargement du service pour vérifier la persistance du compteur
    reloaded = InvoicingService(tmp_path)
    another_2024 = reloaded.create_invoice(
        patient_id="patient-2024-bis",
        lines=[{"description": "Séance", "quantity": 1, "unit_price": 55, "vat_rate": 0.2}],
        invoice_date=date(2024, 5, 20),
    )

    assert another_2024["number"].startswith("2024-")
    assert another_2024["number"] != invoice_2024["number"]

    with open(tmp_path / "counter.json", "r", encoding="utf-8") as handle:
        counter_data = json.load(handle)
    assert counter_data["2024"] >= 2
    assert counter_data["2025"] >= 1
