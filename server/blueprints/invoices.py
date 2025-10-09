"""Simplified invoices blueprint for diagnostics and listings."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List

from flask import Blueprint, current_app, jsonify, request

LOGGER = logging.getLogger(__name__)

bp = Blueprint("invoices", __name__, url_prefix="/api")


def _instance_dir() -> Path:
    return Path(current_app.instance_path)


def _assets_dir() -> Path:
    return _instance_dir() / "assets"


def _invoices_index_path() -> Path:
    return _instance_dir() / "invoices" / "index.json"


def _load_invoices() -> List[Dict[str, object]]:
    path = _invoices_index_path()
    if not path.exists():
        LOGGER.info("Facturation : index inexistant, utilisation d'une liste vide")
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
    except (json.JSONDecodeError, OSError) as exc:
        LOGGER.warning("Facturation : lecture impossible de %s (%s)", path, exc)
    return []


@bp.get("/invoices/diagnostics")
def invoices_diagnostics():
    assets_dir = _assets_dir()
    logo_svg = assets_dir / "logo.svg"
    signature_png = assets_dir / "signature.png"
    template_dir = Path(current_app.root_path).parent / "server" / "templates"
    template_ready = (template_dir / "invoice_template.docx").exists()
    soffice_found = shutil.which("soffice") is not None
    diagnostics = {
        "template_ready": bool(template_ready),
        "logo": logo_svg.exists(),
        "signature": signature_png.exists(),
        "logo_svg_exists": logo_svg.exists(),
        "signature_png_exists": signature_png.exists(),
        "soffice_found": bool(soffice_found),
        "fallback_ready": True,
    }
    LOGGER.info("Facturation : diagnostics %s", diagnostics)
    return jsonify({"ok": True, "data": diagnostics})


@bp.get("/invoices")
def list_invoices():
    patient_filter = (request.args.get("patient") or "").strip()
    invoices = _load_invoices()
    if patient_filter:
        invoices = [invoice for invoice in invoices if invoice.get("patientId") == patient_filter]
    LOGGER.info(
        "Facturation : %d facture(s) retournée(s) (filtre patient=%s)",
        len(invoices),
        patient_filter or "*",
    )
    return jsonify({"ok": True, "invoices": invoices, "count": len(invoices), "patient": patient_filter or None})


__all__ = ["bp"]
