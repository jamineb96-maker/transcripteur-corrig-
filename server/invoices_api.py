"""Blueprint Flask pour la facturation autonome."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional

from flask import Blueprint, Response, jsonify, request, send_file

from .assets_bootstrap import AssetPaths, ensure_assets, refresh_logo_cache
from .invoice_template import build_invoice_docx
from .pdf_pipeline import fallback_ready, soffice_available, to_pdf

try:  # pragma: no cover - dépendance optionnelle
    import pypdfium2 as pdfium  # type: ignore
except Exception:  # pragma: no cover - fallback basique
    pdfium = None

LOGGER = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
INSTANCE_DIR = ROOT_DIR / "instance"
ASSETS_DIR = INSTANCE_DIR / "assets"
INVOICES_DIR = INSTANCE_DIR / "invoices"
INDEX_PATH = INVOICES_DIR / "index.json"
COUNTER_PATH = INVOICES_DIR / "counter.json"

DEFAULT_ISSUER = {
    "name": "Benjamin Tramoni",
    "address": "Adresse professionnelle",
    "email": "benjamin.tramoni@gmail.com",
    "phone": "",
    "siret": "",
    "ape": "",
}

bp = Blueprint("invoices_api", __name__)


class InvoiceError(Exception):
    """Base pour les erreurs métier de facturation."""

    status_code = 400

    def __init__(self, message: str, errors: Optional[Dict[str, str]] = None) -> None:
        super().__init__(message)
        self.errors = errors or {}


class InvoiceNotFound(InvoiceError):
    status_code = 404


class InvoiceConflict(InvoiceError):
    status_code = 409


def _load_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _slugify(value: str) -> str:
    keep = [c if c.isalnum() else "-" for c in value.strip()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    slug = slug.strip("-")
    return slug.lower() or "facture"


def _parse_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise InvoiceError("Date invalide.", {"date": "Format attendu AAAA-MM-JJ."})


def _coerce_amount(value, field: str, *, positive: bool = True) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InvoiceError("Valeur numérique requise.", {field: "Valeur numérique attendue."})
    if positive and number <= 0:
        raise InvoiceError("Valeur positive attendue.", {field: "La valeur doit être strictement positive."})
    return round(number, 2)


def _validate_lines(lines: List[dict]) -> List[dict]:
    if not isinstance(lines, list) or not lines:
        raise InvoiceError("Lignes de facture manquantes.", {"lines": "Ajoutez au moins une ligne."})
    validated: List[dict] = []
    errors: Dict[str, str] = {}
    for index, raw in enumerate(lines):
        if not isinstance(raw, dict):
            errors[f"lines[{index}]"] = "Format de ligne invalide."
            continue
        label = str(raw.get("label", "")).strip()
        if not label:
            errors[f"lines[{index}].label"] = "Libellé requis."
        try:
            qty = _coerce_amount(raw.get("qty", 0), f"lines[{index}].qty")
        except InvoiceError as exc:
            errors.update(exc.errors)
            continue
        try:
            unit = _coerce_amount(raw.get("unit_price", 0), f"lines[{index}].unit_price", positive=False)
        except InvoiceError as exc:
            errors.update(exc.errors)
            continue
        try:
            vat_rate = _coerce_amount(raw.get("vat_rate", 0), f"lines[{index}].vat_rate", positive=False)
        except InvoiceError as exc:
            errors.update(exc.errors)
            continue
        if vat_rate > 1:
            vat_rate = round(vat_rate / 100, 4)
        validated.append(
            {
                "label": label,
                "qty": qty,
                "unit_price": unit,
                "vat_rate": vat_rate,
            }
        )
    if errors:
        raise InvoiceError("Certaines lignes sont invalides.", errors)
    return validated


def _default_assets() -> AssetPaths:
    return ensure_assets()


def _prepare_invoice(payload: Dict, *, persist: bool) -> Dict:
    if not isinstance(payload, dict):
        raise InvoiceError("Corps de requête invalide.")
    invoice_date = _parse_date(payload.get("date"))
    patient = payload.get("patient") or {}
    name = str(patient.get("name", "")).strip()
    address = str(patient.get("address", "")).strip()
    if not name:
        raise InvoiceError("Nom du patient requis.", {"patient.name": "Champ obligatoire."})
    if not address:
        raise InvoiceError("Adresse du patient requise.", {"patient.address": "Champ obligatoire."})
    lines = _validate_lines(payload.get("lines") or [])

    issuer = DEFAULT_ISSUER.copy()
    issuer.update({k: v for k, v in (payload.get("issuer") or {}).items() if v})

    totals = {"total_ht": 0.0, "total_vat": 0.0, "total": 0.0}
    for line in lines:
        total_ht = round(line["qty"] * line["unit_price"], 2)
        total_vat = round(total_ht * line["vat_rate"], 2)
        line["total"] = round(total_ht + total_vat, 2)
        totals["total_ht"] = round(totals["total_ht"] + total_ht, 2)
        totals["total_vat"] = round(totals["total_vat"] + total_vat, 2)
        totals["total"] = round(totals["total"] + line["total"], 2)

    number_mode = str(payload.get("number_mode", "auto")).lower()
    if number_mode not in {"auto", "manual"}:
        raise InvoiceError("Mode de numérotation invalide.", {"number_mode": "auto ou manual"})

    index = _load_json(INDEX_PATH, default=[])
    counters = _load_json(COUNTER_PATH, default={})

    if persist and number_mode == "auto":
        year = str(invoice_date.year)
        next_value = int(counters.get(year, 0)) + 1
        counters[year] = next_value
        invoice_id = f"F{year}-{next_value:05d}"
        invoice_number = invoice_id
    elif persist and number_mode == "manual":
        number = str(payload.get("number", "")).strip()
        if not number:
            raise InvoiceError("Numéro manuel requis.", {"number": "Indiquez un numéro."})
        invoice_id = _slugify(number)
        invoice_number = number
    else:
        invoice_number = str(payload.get("number", "")).strip() or f"PREVIEW-{invoice_date.year}"
        invoice_id = _slugify(invoice_number)

    if persist:
        for entry in index:
            if entry.get("id") == invoice_id or entry.get("number") == invoice_number:
                raise InvoiceConflict("Identifiant déjà utilisé.")

    invoice = {
        "id": invoice_id,
        "number": invoice_number,
        "date": invoice_date.strftime("%Y-%m-%d"),
        "patient": {"name": name, "address": address},
        "lines": lines,
        "totals": totals,
        "notes": str(payload.get("notes", "")),
        "issuer": issuer,
        "payments": [],
        "paid": False,
        "balance": totals["total"],
        "generated_on": datetime.now().strftime("%d/%m/%Y"),
    }

    if persist and number_mode == "auto":
        _write_json(COUNTER_PATH, counters)

    return invoice


def _save_invoice(invoice: Dict, pdf_path: Path, sha256: str) -> Dict:
    detail_path = INVOICES_DIR / f"{invoice['id']}.json"
    invoice_record = invoice.copy()
    invoice_record.update({
        "pdf": pdf_path.name,
        "sha256": sha256,
    })
    _write_json(detail_path, invoice_record)

    index = _load_json(INDEX_PATH, default=[])
    index = [entry for entry in index if entry.get("id") != invoice["id"]]
    index.append(
        {
            "id": invoice["id"],
            "number": invoice["number"],
            "date": invoice["date"],
            "patient_name": invoice["patient"]["name"],
            "total_ttc": invoice["totals"]["total"],
            "paid": invoice["paid"],
            "file_url": f"/invoices/{invoice['id']}.pdf",
            "sha256": sha256,
        }
    )
    index.sort(key=lambda item: (item.get("date", ""), item.get("id", "")), reverse=True)
    _write_json(INDEX_PATH, index)
    LOGGER.info("invoice.indexed %s", invoice["id"])
    return invoice_record


def _load_invoice(invoice_id: str) -> Dict:
    detail_path = INVOICES_DIR / f"{invoice_id}.json"
    if not detail_path.exists():
        raise InvoiceNotFound("Facture introuvable.")
    with detail_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _serialize_invoice(invoice: Dict) -> Dict:
    data = invoice.copy()
    data["file_url"] = f"/invoices/{invoice['id']}.pdf"
    data.pop("pdf", None)
    return data


@bp.route("/api/assets/upload", methods=["POST"])
def upload_asset() -> Response:
    kind = request.args.get("kind")
    if kind not in {"logo", "signature"}:
        return jsonify({"success": False, "message": "Type d'actif invalide."}), 400
    file = request.files.get("file")
    if file is None:
        return jsonify({"success": False, "message": "Fichier manquant."}), 400
    filename = "logo.svg" if kind == "logo" else "signature.png"
    target = ASSETS_DIR / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    file.save(target)
    if kind == "logo":
        refresh_logo_cache()
    return jsonify({"success": True, "data": {"path": f"/billing-assets/{filename}"}})


@bp.get("/billing-assets/<path:filename>")
def serve_asset(filename: str):
    path = (ASSETS_DIR / filename).resolve()
    if not path.exists() or not str(path).startswith(str(ASSETS_DIR.resolve())):
        return jsonify({"success": False, "message": "Actif introuvable."}), 404
    return send_file(path)


@bp.post("/api/invoices")
def create_invoice():
    payload = request.get_json(silent=True) or {}
    try:
        invoice = _prepare_invoice(payload, persist=True)
    except InvoiceError as exc:
        return (
            jsonify({"success": False, "message": str(exc), "errors": exc.errors}),
            getattr(exc, "status_code", 400),
        )
    assets = _default_assets()
    docx_path = build_invoice_docx(invoice, assets)
    try:
        pdf_path = to_pdf(docx_path, invoice, assets, output_dir=INVOICES_DIR, output_name=f"{invoice['id']}.pdf")
    finally:
        if docx_path.exists():
            docx_path.unlink()
    sha256 = _compute_sha256(pdf_path)
    invoice_record = _save_invoice(invoice, pdf_path, sha256)
    return jsonify({"success": True, "data": _serialize_invoice(invoice_record)}), 201


@bp.get("/api/invoices")
def list_invoices():
    index = _load_json(INDEX_PATH, default=[])
    patient_query = (request.args.get("patient") or "").strip().lower()
    paid_param = request.args.get("paid")
    from_date = request.args.get("from")
    to_date = request.args.get("to")

    def matches(entry):
        if patient_query and patient_query not in entry.get("patient_name", "").lower():
            return False
        if paid_param in {"true", "false"}:
            paid_flag = entry.get("paid", False)
            if (paid_param == "true" and not paid_flag) or (paid_param == "false" and paid_flag):
                return False
        if from_date and entry.get("date") < from_date:
            return False
        if to_date and entry.get("date") > to_date:
            return False
        return True

    filtered = [entry for entry in index if matches(entry)]
    return jsonify({"success": True, "data": {"invoices": filtered}})


@bp.get("/api/invoices/<invoice_id>")
def get_invoice(invoice_id: str):
    try:
        invoice = _load_invoice(invoice_id)
    except InvoiceError as exc:
        return jsonify({"success": False, "message": str(exc)}), exc.status_code
    return jsonify({"success": True, "data": _serialize_invoice(invoice)})


@bp.post("/api/invoices/<invoice_id>/pay")
def register_payment(invoice_id: str):
    try:
        invoice = _load_invoice(invoice_id)
    except InvoiceError as exc:
        return jsonify({"success": False, "message": str(exc)}), exc.status_code
    payload = request.get_json(silent=True) or {}
    amount = _coerce_amount(payload.get("amount"), "amount")
    payment_date = str(payload.get("date", datetime.now().strftime("%Y-%m-%d")))
    method = str(payload.get("method", ""))
    invoice.setdefault("payments", []).append({"amount": amount, "date": payment_date, "method": method})
    paid_total = round(sum(item.get("amount", 0) for item in invoice["payments"]), 2)
    balance = round(invoice["totals"]["total"] - paid_total, 2)
    invoice["paid"] = balance <= 0.01
    invoice["balance"] = balance
    pdf_path = INVOICES_DIR / f"{invoice['id']}.pdf"
    sha = _compute_sha256(pdf_path) if pdf_path.exists() else ""
    saved = _save_invoice(invoice, pdf_path, sha)
    return jsonify({"success": True, "data": _serialize_invoice(saved)})


@bp.get("/invoices/<invoice_id>.pdf")
def download_invoice(invoice_id: str):
    pdf_path = INVOICES_DIR / f"{invoice_id}.pdf"
    if not pdf_path.exists():
        try:
            invoice = _load_invoice(invoice_id)
        except InvoiceError as exc:
            return jsonify({"success": False, "message": str(exc)}), exc.status_code
        assets = _default_assets()
        docx_path = build_invoice_docx(invoice, assets)
        try:
            to_pdf(docx_path, invoice, assets, output_dir=INVOICES_DIR, output_name=f"{invoice['id']}.pdf")
        finally:
            if docx_path.exists():
                docx_path.unlink()
    if not pdf_path.exists():
        return jsonify({"success": False, "message": "PDF indisponible."}), 404
    return send_file(pdf_path, mimetype="application/pdf", as_attachment=False, download_name=f"{invoice_id}.pdf")


@bp.post("/api/invoices/preview")
def preview_invoice():
    if pdfium is None:
        return jsonify({"success": False, "message": "Prévisualisation indisponible."}), 503
    payload = request.get_json(silent=True) or {}
    try:
        invoice = _prepare_invoice(payload, persist=False)
    except InvoiceError as exc:
        return jsonify({"success": False, "message": str(exc), "errors": exc.errors}), getattr(exc, "status_code", 400)
    assets = _default_assets()
    with TemporaryDirectory() as tmp_dir:
        docx_path = build_invoice_docx(invoice, assets)
        pdf_path = to_pdf(docx_path, invoice, assets, output_dir=Path(tmp_dir), output_name="preview.pdf")
        page = pdfium.PdfDocument(str(pdf_path))[0]
        bitmap = page.render(scale=2).to_pil()
        buffer = BytesIO()
        bitmap.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode()
        if docx_path.exists():
            docx_path.unlink()
    return jsonify({"success": True, "data": {"preview": f"data:image/png;base64,{encoded}", "message": "L’aperçu est rasterisé; le PDF final conserve le logo vectoriel."}})


@bp.get("/api/invoices/diagnostics")
def diagnostics():
    assets = _default_assets()
    return jsonify(
        {
            "success": True,
            "data": {
                "template_ready": assets.logo_raster.exists() and assets.signature.exists(),
                "logo_svg_exists": assets.logo_svg.exists(),
                "signature_png_exists": assets.signature.exists(),
                "logo_raster_exists": assets.logo_raster.exists(),
                "soffice_found": soffice_available(),
                "fallback_ready": fallback_ready(),
            },
        }
    )


__all__ = ["bp"]
