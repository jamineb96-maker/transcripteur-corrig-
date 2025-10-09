"""Service de gestion des factures."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from zipfile import ZipFile

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

LOGGER = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[2]
INSTANCE_DIR = ROOT_DIR / "instance"
INVOICE_DIR = INSTANCE_DIR / "invoices"
INDEX_PATH = INVOICE_DIR / "index.json"
COUNTER_PATH = INVOICE_DIR / "counter.json"
TEMPLATE_DIR = INSTANCE_DIR / "templates"
TEMPLATE_PATH = TEMPLATE_DIR / "invoice_template.docx"


class InvoiceError(Exception):
    """Base des erreurs liées au traitement des factures."""

    def __init__(self, message: str, errors: Optional[Dict[str, str]] = None) -> None:
        super().__init__(message)
        self.errors = errors or {}


class InvoiceNotFoundError(InvoiceError):
    """Erreur levée lorsqu'une facture est introuvable."""


class InvoiceValidationError(InvoiceError):
    """Erreur levée lors d'une validation métier invalide."""


def _raise_validation(message: str, errors: Optional[Dict[str, str]] = None) -> None:
    LOGGER.info("Validation de facture échouée: %s", message)
    if errors:
        LOGGER.info("Détails des erreurs: %s", errors)
    raise InvoiceValidationError(message, errors)


@dataclass
class InvoiceLine:
    description: str
    quantity: float
    unit_price: float
    vat_rate: float

    def total_ht(self) -> float:
        return round(self.quantity * self.unit_price, 2)

    def total_vat(self) -> float:
        return round(self.total_ht() * self.vat_rate, 2)

    def total_ttc(self) -> float:
        return round(self.total_ht() + self.total_vat(), 2)


def _ensure_directories() -> None:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    INVOICE_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError):
        return default


def _dump_json(path: Path, payload) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    temp_path.replace(path)


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    cleaned = re.sub(r"-+", "-", cleaned)
    return cleaned.strip("-").lower() or "invoice"


def _parse_date(value: str, field: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        _raise_validation("Date invalide.", {field: "Format de date attendu : AAAA-MM-JJ."})


def _coerce_float(value, field: str, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        _raise_validation("Valeur numérique requise.", {field: "La valeur doit être numérique."})
    if positive and number <= 0:
        _raise_validation("Valeur invalide.", {field: "La valeur doit être strictement positive."})
    return round(number, 2)


def _validate_lines(lines: Iterable[dict]) -> List[InvoiceLine]:
    validated: List[InvoiceLine] = []
    if not isinstance(lines, list) or not lines:
        _raise_validation("Lignes de facture manquantes.", {"lines": "Ajoutez au moins une ligne."})
    errors: Dict[str, str] = {}
    for index, raw in enumerate(lines):
        prefix = f"lines[{index}]"
        if not isinstance(raw, dict):
            errors[prefix] = "Format de ligne invalide."
            continue
        description = str(raw.get("description", "")).strip()
        if not description:
            errors[f"{prefix}.description"] = "La description est obligatoire."
        try:
            quantity = _coerce_float(raw.get("quantity", 0), f"{prefix}.quantity", positive=True)
        except InvoiceValidationError as exc:  # pragma: no cover - typed for clarity
            errors.update(exc.errors)
            continue
        try:
            unit_price = _coerce_float(raw.get("unitPrice", 0), f"{prefix}.unitPrice")
        except InvoiceValidationError as exc:
            errors.update(exc.errors)
            continue
        try:
            vat_rate = _coerce_float(raw.get("vatRate", 0), f"{prefix}.vatRate")
        except InvoiceValidationError as exc:
            errors.update(exc.errors)
            continue
        if vat_rate > 1:
            vat_rate = round(vat_rate / 100, 4)
        if description:
            validated.append(InvoiceLine(description, quantity, unit_price, vat_rate))
    if errors:
        _raise_validation("Certaines lignes sont invalides.", errors)
    return validated


def _load_invoices() -> List[dict]:
    data = _load_json(INDEX_PATH, default=[])
    if isinstance(data, list):
        return data
    return []


def _save_invoices(invoices: List[dict]) -> None:
    _ensure_directories()
    _dump_json(INDEX_PATH, invoices)


def _load_counters() -> Dict[str, int]:
    data = _load_json(COUNTER_PATH, default={})
    if isinstance(data, dict):
        normalised: Dict[str, int] = {}
        for key, value in data.items():
            try:
                normalised[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return normalised
    return {}


def _save_counters(counters: Dict[str, int]) -> None:
    _ensure_directories()
    _dump_json(COUNTER_PATH, counters)


def _generate_auto_identifiers(invoice_date: date) -> Tuple[str, str]:
    counters = _load_counters()
    year = str(invoice_date.year)
    next_value = counters.get(year, 0) + 1
    counters[year] = next_value
    _save_counters(counters)
    invoice_id = f"inv-{year}-{next_value:04d}"
    invoice_number = f"FAC-{year}-{next_value:04d}"
    return invoice_id, invoice_number


def _check_manual_collision(identifier: str, invoices: List[dict]) -> None:
    for entry in invoices:
        number = str(entry.get("number", ""))
        if entry.get("id") == identifier or _slugify(number) == identifier:
            LOGGER.warning("Collision d'identifiant de facture détectée: %s", identifier)
            raise InvoiceValidationError(
                "Identifiant déjà utilisé.",
                {"number": "Ce numéro de facture est déjà enregistré."},
            )


def _serialise_line(line: InvoiceLine) -> dict:
    return {
        "description": line.description,
        "quantity": line.quantity,
        "unitPrice": line.unit_price,
        "vatRate": line.vat_rate,
        "totalHT": line.total_ht(),
        "totalVAT": line.total_vat(),
        "totalTTC": line.total_ttc(),
    }


def _compute_totals(lines: List[InvoiceLine]) -> Tuple[float, float, float]:
    total_ht = round(sum(line.total_ht() for line in lines), 2)
    total_vat = round(sum(line.total_vat() for line in lines), 2)
    total_ttc = round(total_ht + total_vat, 2)
    return total_ht, total_vat, total_ttc


def list_invoices(patient_id: Optional[str] = None) -> List[dict]:
    invoices = _load_invoices()
    if patient_id:
        return [invoice for invoice in invoices if invoice.get("patientId") == patient_id]
    return invoices


def summarise_invoices(invoices: Iterable[dict]) -> Dict[str, float]:
    total = 0.0
    paid = 0.0
    due = 0.0
    for invoice in invoices:
        total += float(invoice.get("totalTTC", 0) or 0)
        paid += float(invoice.get("paid", 0) or 0)
        due += float(invoice.get("balance", 0) or 0)
    return {
        "total": round(total, 2),
        "paid": round(paid, 2),
        "due": round(due, 2),
    }


def get_invoice(invoice_id: str) -> dict:
    invoices = _load_invoices()
    for invoice in invoices:
        if invoice.get("id") == invoice_id:
            return invoice
    raise InvoiceNotFoundError("Facture introuvable.")


def create_invoice(payload: dict) -> dict:
    _ensure_directories()
    if not isinstance(payload, dict):
        _raise_validation("Payload invalide.")

    invoices = _load_invoices()

    patient_id = str(payload.get("patientId", "")).strip()
    if not patient_id:
        _raise_validation("Patient manquant.", {"patientId": "Sélectionnez un patient."})

    raw_date = payload.get("date") or date.today().isoformat()
    invoice_date = _parse_date(raw_date, "date")

    due_date_value = payload.get("dueDate")
    due_date = None
    if due_date_value:
        due_date = _parse_date(due_date_value, "dueDate")

    status = str(payload.get("status") or "draft")
    if status not in {"draft", "sent", "paid", "overdue"}:
        _raise_validation("Statut invalide.", {"status": "Statut inconnu."})

    lines = _validate_lines(payload.get("lines", []))
    total_ht, total_vat, total_ttc = _compute_totals(lines)

    paid_amount = _coerce_float(payload.get("paid", 0), "paid")
    if paid_amount < 0:
        _raise_validation("Montant payé invalide.", {"paid": "Le montant payé doit être positif."})
    if paid_amount > total_ttc:
        _raise_validation(
            "Montant payé supérieur au total.",
            {"paid": "Le montant payé ne peut pas dépasser le total TTC."},
        )

    manual_number = str(payload.get("number", "")).strip()
    mode = str(payload.get("mode") or ("manual" if manual_number else "auto"))
    if mode not in {"auto", "manual"}:
        _raise_validation("Mode invalide.", {"mode": "Utilisez 'auto' ou 'manual'."})

    if mode == "manual":
        if not manual_number:
            _raise_validation("Numéro requis en mode manuel.", {"number": "Indiquez un numéro de facture."})
        identifier = _slugify(manual_number)
        _check_manual_collision(identifier, invoices)
        invoice_id = identifier
        invoice_number = manual_number
    else:
        invoice_id, invoice_number = _generate_auto_identifiers(invoice_date)

    serialised_lines = [_serialise_line(line) for line in lines]
    balance = round(total_ttc - paid_amount, 2)

    invoice = {
        "id": invoice_id,
        "number": invoice_number,
        "patientId": patient_id,
        "date": invoice_date.isoformat(),
        "dueDate": due_date.isoformat() if due_date else None,
        "status": status,
        "lines": serialised_lines,
        "totalHT": total_ht,
        "totalVAT": total_vat,
        "totalTTC": total_ttc,
        "paid": paid_amount,
        "balance": balance,
        "notes": str(payload.get("notes") or "").strip() or None,
        "createdAt": datetime.utcnow().isoformat() + "Z",
        "updatedAt": datetime.utcnow().isoformat() + "Z",
    }

    invoices.append(invoice)
    _save_invoices(invoices)

    pdf_path = generate_invoice_pdf(invoice, persist=True)
    invoice["fileUrl"] = f"/invoices/{invoice_id}.pdf"
    if pdf_path is None:
        invoice["fileUrl"] = None
    else:
        invoice["fileUrl"] = f"/invoices/{invoice_id}.pdf"

    _save_invoices(invoices)

    return invoice


def register_payment(invoice_id: str, amount: float) -> dict:
    invoices = _load_invoices()
    for invoice in invoices:
        if invoice.get("id") == invoice_id:
            additional_paid = _coerce_float(amount, "amount", positive=True)
            current_paid = _coerce_float(invoice.get("paid", 0), "paid")
            total_ttc = _coerce_float(invoice.get("totalTTC", 0), "totalTTC")
            new_paid = round(current_paid + additional_paid, 2)
            if new_paid > total_ttc:
                _raise_validation(
                    "Montant payé supérieur au total.",
                    {"amount": "Le paiement dépasse le total restant."},
                )
            invoice["paid"] = new_paid
            invoice["balance"] = round(total_ttc - new_paid, 2)
            invoice["status"] = "paid" if invoice["balance"] <= 0 else invoice.get("status", "sent")
            invoice["updatedAt"] = datetime.utcnow().isoformat() + "Z"
            invoice.setdefault("fileUrl", f"/invoices/{invoice_id}.pdf")
            _save_invoices(invoices)
            generate_invoice_pdf(invoice, persist=True)
            return invoice
    raise InvoiceNotFoundError("Facture introuvable.")


def _build_template_context(invoice: dict) -> Dict[str, str]:
    def format_currency(value: float) -> str:
        return f"{value:,.2f}".replace(",", " ").replace(".", ",")

    lines = invoice.get("lines", [])
    lines_summary = []
    for line in lines:
        lines_summary.append(
            f"{line.get('description', '')} — {line.get('quantity', 0)} x {line.get('unitPrice', 0)} (TVA {line.get('vatRate', 0)})"
        )
    return {
        "invoice_number": str(invoice.get("number", "")),
        "invoice_date": str(invoice.get("date", "")),
        "invoice_due": str(invoice.get("dueDate", "")) if invoice.get("dueDate") else "",
        "patient_id": str(invoice.get("patientId", "")),
        "total_ht": format_currency(float(invoice.get("totalHT", 0))),
        "total_vat": format_currency(float(invoice.get("totalVAT", 0))),
        "total_ttc": format_currency(float(invoice.get("totalTTC", 0))),
        "paid_amount": format_currency(float(invoice.get("paid", 0))),
        "balance": format_currency(float(invoice.get("balance", 0))),
        "lines_summary": "; ".join(lines_summary),
        "notes": str(invoice.get("notes") or ""),
    }


def _merge_docx_template(invoice: dict) -> Optional[Path]:
    if not TEMPLATE_PATH.exists():
        return None
    context = _build_template_context(invoice)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        extracted_dir = tmp_dir_path / "doc"
        extracted_dir.mkdir(parents=True, exist_ok=True)
        try:
            with ZipFile(TEMPLATE_PATH) as template_zip:
                template_zip.extractall(extracted_dir)
        except (OSError, ValueError):
            return None
        document_path = extracted_dir / "word" / "document.xml"
        if not document_path.exists():
            return None
        xml_content = document_path.read_text(encoding="utf-8")
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            xml_content = xml_content.replace(placeholder, value)
        document_path.write_text(xml_content, encoding="utf-8")
        merged_path = tmp_dir_path / "merged.docx"
        with ZipFile(merged_path, "w") as merged_zip:
            for path in extracted_dir.rglob("*"):
                if path.is_dir():
                    continue
                arcname = path.relative_to(extracted_dir)
                merged_zip.write(path, arcname.as_posix())
        final_path = Path(tempfile.mkstemp(suffix=".docx")[1])
        shutil.copyfile(merged_path, final_path)
        return final_path


def _convert_doc_to_pdf(doc_path: Path, target_pdf: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--convert-to",
                "pdf",
                str(doc_path),
                "--outdir",
                str(target_pdf.parent),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
    except FileNotFoundError:
        LOGGER.info("LibreOffice non disponible, passage au fallback ReportLab.")
        return None
    except subprocess.SubprocessError as exc:
        LOGGER.warning("Conversion LibreOffice échouée: %s", exc)
        return None
    if result.returncode != 0:
        LOGGER.warning("LibreOffice a retourné un code %s", result.returncode)
        return None
    converted_path = target_pdf.parent / (doc_path.stem + ".pdf")
    if not converted_path.exists() or converted_path.stat().st_size <= 2048:
        LOGGER.warning("PDF généré invalide (%s).", converted_path)
        return None
    converted_path.replace(target_pdf)
    return target_pdf


def _fallback_pdf(invoice: dict, target_pdf: Path) -> Path:
    LOGGER.warning("Utilisation du fallback ReportLab pour la facture %s.", invoice.get("id"))
    c = canvas.Canvas(str(target_pdf), pagesize=A4)
    width, height = A4
    margin = 20 * mm
    y = height - margin
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, f"Facture {invoice.get('number', '')}")
    y -= 20
    c.setFont("Helvetica", 11)
    c.drawString(margin, y, f"Patient : {invoice.get('patientId', '')}")
    y -= 14
    c.drawString(margin, y, f"Date : {invoice.get('date', '')}")
    y -= 14
    c.drawString(margin, y, f"Total TTC : {invoice.get('totalTTC', 0)} €")
    y -= 14
    c.drawString(margin, y, f"Total payé : {invoice.get('paid', 0)} €")
    y -= 14
    c.drawString(margin, y, f"Solde restant : {invoice.get('balance', 0)} €")
    y -= 20
    c.setFont("Helvetica", 10)
    for line in invoice.get("lines", []):
        text = f"- {line.get('description', '')} (Qté {line.get('quantity', 0)} x {line.get('unitPrice', 0)} €)"
        c.drawString(margin, y, text)
        y -= 12
        if y <= margin:
            c.showPage()
            y = height - margin
            c.setFont("Helvetica", 10)
    c.showPage()
    c.save()
    return target_pdf


def generate_invoice_pdf(invoice: dict, persist: bool = True) -> Optional[Path]:
    _ensure_directories()
    if persist:
        target_dir = INVOICE_DIR
    else:
        target_dir = Path(tempfile.mkdtemp(prefix="invoice-preview-"))
    identifier = str(invoice.get("id") or _slugify(invoice.get("number", "")))
    pdf_target = (target_dir / identifier).with_suffix(".pdf")
    doc_path = _merge_docx_template(invoice)
    if doc_path:
        pdf = _convert_doc_to_pdf(doc_path, pdf_target)
        try:
            doc_path.unlink(missing_ok=True)
        except OSError:
            pass
        if pdf:
            return pdf
    return _fallback_pdf(invoice, pdf_target)


def get_invoice_pdf_path(invoice_id: str) -> Path:
    return INVOICE_DIR / f"{invoice_id}.pdf"


def validate_template() -> Dict[str, object]:
    _ensure_directories()
    if not TEMPLATE_PATH.exists():
        return {"valid": False, "message": "Aucun gabarit trouvé."}
    dummy_invoice = {
        "id": "validation",
        "number": "VAL-0000",
        "patientId": "demo",
        "date": date.today().isoformat(),
        "dueDate": None,
        "status": "draft",
        "lines": [
            {
                "description": "Vérification gabarit",
                "quantity": 1,
                "unitPrice": 0,
                "vatRate": 0,
            }
        ],
        "totalHT": 0,
        "totalVAT": 0,
        "totalTTC": 0,
        "paid": 0,
        "balance": 0,
    }
    pdf_path = generate_invoice_pdf(dummy_invoice, persist=False)
    if not pdf_path or not pdf_path.exists() or pdf_path.stat().st_size <= 0:
        return {"valid": False, "message": "Échec de génération du PDF."}
    try:
        pdf_path.unlink()
    except OSError:
        pass
    try:
        shutil.rmtree(pdf_path.parent)
    except OSError:
        pass
    return {"valid": True, "message": "Gabarit valide."}
