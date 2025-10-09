"""Routes REST pour la gestion des factures."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, Dict

from flask import jsonify, request, send_file

from . import bp
from server.services.invoices import (
    InvoiceNotFoundError,
    InvoiceValidationError,
    create_invoice,
    generate_invoice_pdf,
    get_invoice,
    get_invoice_pdf_path,
    list_invoices,
    register_payment,
    summarise_invoices,
    validate_template,
)

LOGGER = logging.getLogger(__name__)


@bp.get('/api/invoices')
def get_invoices() -> Any:
    """Retourne la liste des factures, éventuellement filtrée par patient."""
    patient_id = request.args.get('patientId')
    invoices = list_invoices(patient_id)
    summary = summarise_invoices(invoices)
    return jsonify({'success': True, 'data': {'invoices': invoices, 'summary': summary}})


@bp.post('/api/invoices')
def create_invoice_endpoint() -> Any:
    """Crée une nouvelle facture et génère le PDF associé."""
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    try:
        invoice = create_invoice(payload)
    except InvoiceValidationError as exc:
        response = {'success': False, 'message': str(exc), 'errors': exc.errors}
        return jsonify(response), HTTPStatus.BAD_REQUEST
    except Exception as exc:  # pragma: no cover - protection supplémentaire
        LOGGER.exception("Erreur inattendue lors de la création de facture")
        return jsonify({'success': False, 'message': "Une erreur interne est survenue."}), HTTPStatus.INTERNAL_SERVER_ERROR
    return jsonify({'success': True, 'data': invoice}), HTTPStatus.CREATED


@bp.get('/api/invoices/<invoice_id>')
def get_invoice_endpoint(invoice_id: str) -> Any:
    """Retourne le détail d'une facture."""
    try:
        invoice = get_invoice(invoice_id)
    except InvoiceNotFoundError:
        return jsonify({'success': False, 'message': 'Facture introuvable.'}), HTTPStatus.NOT_FOUND
    return jsonify({'success': True, 'data': invoice})


@bp.post('/api/invoices/<invoice_id>/pay')
def pay_invoice_endpoint(invoice_id: str) -> Any:
    """Enregistre un paiement partiel ou total pour une facture."""
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    try:
        amount = payload.get('amount')
        if amount is None:
            LOGGER.info("Validation paiement échouée pour %s: montant manquant", invoice_id)
            raise InvoiceValidationError('Montant requis.', {'amount': 'Indiquez le montant du paiement.'})
        invoice = register_payment(invoice_id, amount)
    except InvoiceNotFoundError:
        return jsonify({'success': False, 'message': 'Facture introuvable.'}), HTTPStatus.NOT_FOUND
    except InvoiceValidationError as exc:
        return jsonify({'success': False, 'message': str(exc), 'errors': exc.errors}), HTTPStatus.BAD_REQUEST
    return jsonify({'success': True, 'data': invoice})


@bp.get('/invoices/<invoice_id>.pdf')
def download_invoice_pdf(invoice_id: str):
    """Retourne le PDF d'une facture, en le régénérant au besoin."""
    pdf_path = get_invoice_pdf_path(invoice_id)
    if not pdf_path.exists():
        try:
            invoice = get_invoice(invoice_id)
        except InvoiceNotFoundError:
            return jsonify({'success': False, 'message': 'Facture introuvable.'}), HTTPStatus.NOT_FOUND
        generate_invoice_pdf(invoice, persist=True)
    if not pdf_path.exists():
        return jsonify({'success': False, 'message': 'PDF non disponible.'}), HTTPStatus.NOT_FOUND
    return send_file(pdf_path, mimetype='application/pdf', as_attachment=False, download_name=f'{invoice_id}.pdf')


@bp.post('/api/invoices/validate-template')
def validate_template_endpoint() -> Any:
    """Vérifie que le gabarit de facture est exploitable."""
    result = validate_template()
    status = HTTPStatus.OK if result.get('valid') else HTTPStatus.BAD_REQUEST
    return jsonify({'success': result.get('valid', False), 'data': result}), status
