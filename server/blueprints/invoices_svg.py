"""SVG-based invoices API blueprint."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Tuple

from flask import Blueprint, Response, current_app, jsonify, request

from ..services.invoices_renderer import (
    DEFAULT_DURATION,
    format_eur,
    next_invoice_number,
    render_and_save,
    service_title_from_amount,
)

LOGGER = logging.getLogger("assist.invoices")

bp = Blueprint("invoices_svg", __name__, url_prefix="/api/invoices")


REGISTRY_FILENAME = "factures.json"
COMPANY_FILENAME = "company.json"


def _instance_path() -> Path:
    return Path(current_app.instance_path)


def _registry_path() -> Path:
    return _instance_path() / REGISTRY_FILENAME


def _company_path() -> Path:
    return _instance_path() / COMPANY_FILENAME


def _archives_dir() -> Path:
    return _instance_path() / "archives"


def _load_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
        LOGGER.warning("[invoices] unable to read %s (%s)", path, exc)
        return default


def _save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _load_registry() -> Dict[str, object]:
    data = _load_json(_registry_path(), {"invoices": [], "counters": {}})
    if not isinstance(data, dict):
        data = {"invoices": [], "counters": {}}
    data.setdefault("invoices", [])
    data.setdefault("counters", {})
    return data


def _save_registry(registry: Dict[str, object]) -> None:
    _save_json(_registry_path(), registry)


def _load_company() -> Dict[str, object]:
    company_path = _company_path()
    created = not company_path.exists()
    company = _load_json(
        company_path,
        {
            "name": "Nom Cabinet",
            "subtitle": "Psychopraticien",
            "siret": "",
            "address": "",
            "email": "",
            "phone": "",
            "city": "",
            "iban": "",
            "bic": "",
            "vat_note": "TVA non applicable, art. 293 B du CGI",
            "legal_footer": "",
            "accent_color": "#2B6CB0",
        },
    )
    if not isinstance(company, dict):
        company = {}
    if created:
        _save_json(company_path, company)
    return company


def _validate_patient_id(patient_id: str) -> str:
    if not patient_id:
        raise ValueError("patient_id manquant")
    if any(ch in patient_id for ch in {"..", "/", "\\"}):
        raise ValueError("patient_id invalide")
    return patient_id


def _get_patient_invoice_dir(patient_id: str) -> Path:
    return _archives_dir() / patient_id / "factures"


def _find_invoice(registry: Dict[str, object], number: str) -> Tuple[int, Dict[str, object]] | Tuple[int, None]:
    invoices = registry.get("invoices", [])
    if not isinstance(invoices, list):
        return (-1, None)
    for idx, invoice in enumerate(invoices):
        if isinstance(invoice, dict) and invoice.get("number") == number:
            return idx, invoice
    return -1, None


def _current_iso_timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _prepare_lines(payload_lines: List[Dict[str, object]], default_date: str) -> List[Dict[str, object]]:
    lines: List[Dict[str, object]] = []
    for raw in payload_lines:
        if not isinstance(raw, dict):
            continue
        line_date = str(raw.get("date") or default_date)
        duration = str(raw.get("duree") or raw.get("duration") or DEFAULT_DURATION)
        try:
            unit_price = float(raw.get("pu") if raw.get("pu") is not None else raw.get("unit_price", 0.0))
        except (TypeError, ValueError):
            unit_price = 0.0
        try:
            qty = float(raw.get("qty") if raw.get("qty") is not None else raw.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 1.0
        desc = service_title_from_amount(unit_price)
        lines.append(
            {
                "date": line_date,
                "desc": desc,
                "duree": duration,
                "pu": round(unit_price, 2),
                "qty": round(qty, 3),
            }
        )
    return lines


def _compute_amount(lines: List[Dict[str, object]]) -> float:
    total = 0.0
    for line in lines:
        total += float(line.get("pu", 0.0)) * float(line.get("qty", 1.0))
    return round(total, 2)


def _sort_invoices(invoices: List[Dict[str, object]]) -> List[Dict[str, object]]:
    def _sort_key(item: Dict[str, object]):
        date_value = item.get("date") or "0000-00-00"
        try:
            key_date = date.fromisoformat(str(date_value))
        except ValueError:
            key_date = date.min
        number = str(item.get("number") or "")
        return (-key_date.toordinal(), number)

    return sorted(invoices, key=_sort_key)


@bp.get("")
def list_invoices() -> Response:
    registry = _load_registry()
    invoices = [invoice for invoice in registry.get("invoices", []) if isinstance(invoice, dict)]

    patient_filter = (request.args.get("patient") or "").strip()
    query = (request.args.get("q") or "").strip().lower()
    year_filter = (request.args.get("year") or "").strip()

    filtered: List[Dict[str, object]] = []
    for invoice in invoices:
        if patient_filter and invoice.get("patient_id") != patient_filter:
            continue
        if year_filter:
            if not str(invoice.get("number", "")).startswith(f"{year_filter}-"):
                try:
                    if date.fromisoformat(str(invoice.get("date"))).year != int(year_filter):
                        continue
                except (ValueError, TypeError):
                    continue
        if query:
            haystack = " ".join(
                [
                    str(invoice.get("number", "")),
                    str(invoice.get("patient", "")),
                    str(invoice.get("patient_id", "")),
                ]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(invoice)

    sorted_invoices = _sort_invoices(filtered)
    return jsonify({"invoices": sorted_invoices, "count": len(sorted_invoices)})


@bp.post("")
def create_invoice() -> Response:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "payload invalide"}), 400

    try:
        patient_id = _validate_patient_id(str(payload.get("patient_id", "")).strip())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    patient_name = str(payload.get("patient_name") or patient_id.replace("-", " ").title())
    address = str(payload.get("address") or "")
    paid_via = str(payload.get("paid_via") or "")
    replace_existing = payload.get("replace", True)

    date_iso = str(payload.get("date") or date.today().isoformat())
    try:
        date.fromisoformat(date_iso)
    except ValueError:
        return jsonify({"error": "date invalide"}), 400

    lines_payload = payload.get("lines")
    lines: List[Dict[str, object]]
    if isinstance(lines_payload, list) and lines_payload:
        lines = _prepare_lines(lines_payload, date_iso)
    else:
        amount = payload.get("amount")
        if amount is None:
            return jsonify({"error": "amount requis"}), 400
        try:
            unit_price = float(amount)
        except (TypeError, ValueError):
            return jsonify({"error": "amount invalide"}), 400
        lines = [
            {
                "date": date_iso,
                "desc": service_title_from_amount(unit_price),
                "duree": DEFAULT_DURATION,
                "pu": unit_price,
                "qty": 1.0,
            }
        ]

    registry = _load_registry()
    registry_invoices = registry.get("invoices")
    if not isinstance(registry_invoices, list):
        registry_invoices = []
        registry["invoices"] = registry_invoices

    number = str(payload.get("number") or "").strip()
    new_number_generated = False
    if not number:
        number = next_invoice_number(registry)
        new_number_generated = True

    existing_index, existing_invoice = _find_invoice(registry, number)
    if existing_invoice and not replace_existing:
        return jsonify({"error": "facture existe déjà", "number": number}), 409

    invoice_dir = _get_patient_invoice_dir(patient_id)
    invoice_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = invoice_dir / f"Facture {number}.pdf"
    svg_path = invoice_dir / f"Facture {number}.svg"

    company = _load_company()

    context = {
        "company": company,
        "invoice": {"number": number, "date": date_iso, "amount": _compute_amount(lines)},
        "patient_name": patient_name,
        "patient_address": address,
        "paid_via": paid_via,
        "lines": [
            {
                "date": line["date"],
                "desc": line["desc"],
                "duration": line["duree"],
                "unit_price": line["pu"],
                "quantity": line["qty"],
            }
            for line in lines
        ],
        "paths": {"pdf": str(pdf_path), "svg": str(svg_path)},
    }

    try:
        render_result = render_and_save(context)
    except Exception as exc:  # pragma: no cover - defensive logging
        LOGGER.exception("[invoices] render failed for %s", number)
        if new_number_generated:
            year = number.split("-", 1)[0]
            counters = registry.get("counters")
            if isinstance(counters, dict) and year in counters:
                try:
                    counters[year] = max(int(counters.get(year, 1)) - 1, 0)
                except (TypeError, ValueError):
                    counters[year] = 0
        _save_registry(registry)
        return jsonify({"error": "generation impossible"}), 500
    total_amount = _compute_amount(lines)
    now_iso = _current_iso_timestamp()

    invoice_record = {
        "number": number,
        "date": date_iso,
        "patient": patient_name,
        "patient_id": patient_id,
        "amount": total_amount,
        "currency": "EUR",
        "desc": lines[0].get("desc", service_title_from_amount(total_amount)),
        "address": address,
        "paid_via": paid_via,
        "sent": bool(existing_invoice.get("sent")) if existing_invoice else False,
        "paid": bool(existing_invoice.get("paid")) if existing_invoice else False,
        "paths": {"svg": str(svg_path), "pdf": str(pdf_path)},
        "created_at": existing_invoice.get("created_at") if existing_invoice else now_iso,
        "updated_at": now_iso,
        "lines": lines,
    }

    if existing_invoice:
        registry_invoices[existing_index] = invoice_record
    else:
        registry_invoices.append(invoice_record)

    _save_registry(registry)

    LOGGER.info(
        "[invoices] render %s → files=%s total=%s",
        number,
        render_result.get("paths"),
        format_eur(total_amount),
    )

    sorted_invoices = _sort_invoices([invoice for invoice in registry_invoices if isinstance(invoice, dict)])
    status_code = 200 if existing_invoice and not new_number_generated else 201
    return jsonify({"invoice": invoice_record, "invoices": sorted_invoices, "number": number}), status_code


@bp.delete("/<string:number>")
def delete_invoice(number: str) -> Response:
    number = number.strip()
    registry = _load_registry()
    invoices = registry.get("invoices")
    if not isinstance(invoices, list):
        invoices = []
        registry["invoices"] = invoices

    remaining: List[Dict[str, object]] = []
    removed_paths: List[Tuple[str, str]] = []
    for invoice in invoices:
        if not isinstance(invoice, dict):
            continue
        if invoice.get("number") == number:
            paths = invoice.get("paths") or {}
            svg_path = Path(str(paths.get("svg"))) if paths.get("svg") else None
            pdf_path = Path(str(paths.get("pdf"))) if paths.get("pdf") else None
            for path in (svg_path, pdf_path):
                if path and path.exists():
                    try:
                        path.unlink()
                        removed_paths.append((path.suffix, str(path)))
                    except OSError:
                        LOGGER.warning("[invoices] unable to delete %s", path)
        else:
            remaining.append(invoice)

    registry["invoices"] = remaining
    _save_registry(registry)

    LOGGER.info("[invoices] delete %s removed_files=%s", number, removed_paths)

    return jsonify({"ok": True, "invoices": _sort_invoices([inv for inv in remaining if isinstance(inv, dict)])})


@bp.post("/mark")
def mark_invoice() -> Response:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"error": "payload invalide"}), 400

    number = str(payload.get("number") or "").strip()
    if not number:
        return jsonify({"error": "number requis"}), 400

    registry = _load_registry()
    index, invoice = _find_invoice(registry, number)
    if invoice is None:
        return jsonify({"error": "facture introuvable", "number": number}), 404

    sent = invoice.get("sent") if payload.get("sent") is None else bool(payload.get("sent"))
    paid = invoice.get("paid") if payload.get("paid") is None else bool(payload.get("paid"))

    invoice["sent"] = bool(sent)
    invoice["paid"] = bool(paid)
    invoice["updated_at"] = _current_iso_timestamp()
    registry["invoices"][index] = invoice
    _save_registry(registry)

    invoices = registry.get("invoices", [])
    sorted_invoices = _sort_invoices([inv for inv in invoices if isinstance(inv, dict)])

    return jsonify({"ok": True, "invoice": invoice, "invoices": sorted_invoices})


@bp.get("/diagnostics")
def diagnostics() -> Response:
    registry = _load_registry()
    company = _load_company()
    archives_dir = _archives_dir()
    archives_count = 0
    if archives_dir.exists():
        try:
            archives_count = sum(1 for entry in archives_dir.iterdir() if entry.is_dir())
        except OSError:
            archives_count = 0

    diagnostics_payload = {
        "svg_engine": "ok",
        "cairosvg": True,
        "company_ready": bool(company.get("name")),
        "archives_count": archives_count,
        "invoices_total": len(registry.get("invoices", [])) if isinstance(registry.get("invoices"), list) else 0,
    }
    return jsonify(diagnostics_payload)


__all__ = ["bp"]
