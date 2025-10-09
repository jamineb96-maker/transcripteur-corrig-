"""Conversion DOCX → PDF robuste avec repli ReportLab."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

from reportlab.lib import colors  # type: ignore
from reportlab.lib.pagesizes import A4  # type: ignore
from reportlab.lib.styles import ParagraphStyle  # type: ignore
from reportlab.lib.units import mm  # type: ignore
from reportlab.lib.utils import ImageReader  # type: ignore
from reportlab.pdfgen import canvas  # type: ignore
from reportlab.platypus import Paragraph, Table, TableStyle  # type: ignore
from reportlab.graphics import renderPDF  # type: ignore

try:  # pragma: no cover - dépendances optionnelles
    from svglib.svglib import svg2rlg  # type: ignore
except Exception:  # pragma: no cover
    svg2rlg = None  # type: ignore

from .assets_bootstrap import AssetPaths

LOGGER = logging.getLogger(__name__)

MIN_PDF_SIZE = 5 * 1024


def soffice_available() -> bool:
    """Retourne True si LibreOffice est détecté."""

    return shutil.which("soffice") is not None


def fallback_ready() -> bool:
    """Indique si les dépendances ReportLab/svglib sont disponibles."""

    try:  # pragma: no cover - dépendances optionnelles
        import reportlab  # noqa: F401
        import svglib  # noqa: F401
        return True
    except Exception:  # pragma: no cover - diagnostic uniquement
        return False


def _format_currency(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _draw_header(pdf: canvas.Canvas, invoice: Dict, assets: AssetPaths, *, left_margin: float, right_margin: float,
                 top_margin: float, width: float, height: float) -> float:
    y = height - top_margin
    logo_width = 34 * mm
    logo_height = 0.0
    try:
        if svg2rlg is None:
            raise RuntimeError("svglib non disponible")
        drawing = svg2rlg(str(assets.logo_svg))
        if drawing.minWidth():
            scale = logo_width / float(drawing.minWidth())
        else:
            scale = 1.0
        drawing.scale(scale, scale)
        logo_height = drawing.height
        renderPDF.draw(drawing, pdf, width - right_margin - logo_width, y - logo_height)
    except Exception as exc:  # pragma: no cover - dépend des libs
        LOGGER.warning("Logo vectoriel indisponible pour le fallback: %s", exc)
    issuer = invoice.get("issuer", {})
    lines = []
    for key in ("name", "address", "email", "phone", "siret", "ape"):
        value = str(issuer.get(key, "")).strip()
        if value:
            lines.append(value)
    pdf.setFont("Helvetica", 9)
    text_y = y - logo_height - 4
    for line in lines:
        pdf.drawRightString(width - right_margin, text_y, line)
        text_y -= 12
    return text_y - 10


def _draw_paragraph_table(pdf: canvas.Canvas, left: Paragraph, right: Paragraph, *, x: float, y: float, width: float) -> float:
    table = Table([[left, right]], colWidths=[width * 0.5, width * 0.5])
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBEFORE", (0, 0), (-1, -1), 0, colors.white),
                ("LINEAFTER", (0, 0), (-1, -1), 0, colors.white),
                ("LINEABOVE", (0, 0), (-1, -1), 0, colors.white),
                ("LINEBELOW", (0, 0), (-1, -1), 0, colors.white),
            ]
        )
    )
    w, h = table.wrapOn(pdf, width, y)
    table.drawOn(pdf, x, y - h)
    return y - h


def _draw_lines_table(pdf: canvas.Canvas, invoice: Dict, styles: Dict[str, ParagraphStyle], *, x: float, y: float,
                      width: float) -> float:
    line_items = list(invoice.get("lines", []) or [])
    if not line_items:
        line_items = [
            {"label": "Séance psychopraticien 60 min", "qty": 1, "unit_price": 0.0, "total": 0.0},
        ]
    data = [["Prestation", "Qté", "PU", "Total"]]
    for entry in line_items:
        qty = float(entry.get("qty", 0))
        qty_str = f"{qty:.2f}".rstrip("0").rstrip(".")
        data.append(
            [
                Paragraph(str(entry.get("label", "")), styles["body"]),
                qty_str.replace(".", ","),
                _format_currency(float(entry.get("unit_price", 0))),
                _format_currency(float(entry.get("total", qty * float(entry.get("unit_price", 0))))),
            ]
        )
    col_widths = [width * 0.55, width * 0.15, width * 0.15, width * 0.15]
    table = Table(data, colWidths=col_widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F0F0")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111111")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("LINEABOVE", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                ("LINEBEFORE", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                ("LINEAFTER", (0, 0), (-1, -1), 0.5, colors.HexColor("#999999")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    w, h = table.wrapOn(pdf, width, y)
    table.drawOn(pdf, x, y - h)
    return y - h


def _draw_totals(pdf: canvas.Canvas, totals: Dict, styles: Dict[str, ParagraphStyle], *, x: float, y: float,
                 width: float) -> float:
    amount = _format_currency(float(totals.get("total", totals.get("total_ttc", 0.0))))
    table = Table([[Paragraph("Total dû", styles["totals"]), Paragraph(amount, styles["totals_right"])]]
    )
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LINEABOVE", (0, 0), (-1, -1), 0, colors.white),
                ("LINEBELOW", (0, 0), (-1, -1), 0, colors.white),
                ("LINEBEFORE", (0, 0), (-1, -1), 0, colors.white),
                ("LINEAFTER", (0, 0), (-1, -1), 0, colors.white),
            ]
        )
    )
    w, h = table.wrapOn(pdf, width, y)
    table.drawOn(pdf, x + width - w, y - h)
    return y - h


def _draw_legal(pdf: canvas.Canvas, styles: Dict[str, ParagraphStyle], *, x: float, y: float, width: float) -> float:
    paragraphs = [
        "Cette facture peut être transmise à votre mutuelle…",
        f"Document généré le {Path('.')}",
    ]
    for text in paragraphs:
        para = Paragraph(text, styles["legal"])
        w, h = para.wrapOn(pdf, width, y)
        para.drawOn(pdf, x, y - h)
        y -= h + 2
    return y


def _draw_signature(pdf: canvas.Canvas, assets: AssetPaths, styles: Dict[str, ParagraphStyle], *, x: float, y: float,
                    width: float, right_margin: float) -> None:
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(x + width, y, "Pour acquit,")
    y -= 14
    try:
        signature = ImageReader(str(assets.signature))
        sig_width = 28 * mm
        ratio = signature.getSize()[1] / signature.getSize()[0]
        sig_height = sig_width * ratio
        pdf.drawImage(
            signature,
            x + width - sig_width,
            y - sig_height,
            width=sig_width,
            height=sig_height,
            mask="auto",
        )
        y -= sig_height + 6
    except Exception as exc:  # pragma: no cover - dépend d'actifs
        LOGGER.warning("Signature indisponible pour fallback: %s", exc)
    pdf.drawRightString(x + width, y, "Benjamin Tramoni")


def _reportlab_pdf(invoice: Dict, assets: AssetPaths, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(pdf_path), pagesize=A4)
    width, height = A4
    left_margin = 20 * mm
    right_margin = 20 * mm
    top_margin = 18 * mm
    bottom_margin = 18 * mm
    usable_width = width - left_margin - right_margin

    styles = {
        "body": ParagraphStyle("InvoiceBody", fontName="Helvetica", fontSize=10, leading=13),
        "small_right": ParagraphStyle(
            "InvoiceSmallRight",
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#555555"),
            alignment=2,
        ),
        "small_left": ParagraphStyle(
            "InvoiceSmallLeft",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
        ),
        "totals": ParagraphStyle("InvoiceTotals", fontName="Helvetica-Bold", fontSize=12, leading=14),
        "totals_right": ParagraphStyle(
            "InvoiceTotalsRight",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=14,
            alignment=2,
        ),
        "legal": ParagraphStyle(
            "InvoiceLegal",
            fontName="Helvetica",
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#555555"),
        ),
    }

    current_y = _draw_header(
        pdf,
        invoice,
        assets,
        left_margin=left_margin,
        right_margin=right_margin,
        top_margin=top_margin,
        width=width,
        height=height,
    )

    pdf.setFont("Helvetica-Bold", 16)
    pdf.setFillColor(colors.HexColor("#111111"))
    pdf.drawString(left_margin, current_y, "FACTURE")
    current_y -= 20

    patient = invoice.get("patient", {})
    patient_lines = ["<b>Facturé à</b>"]
    name = str(patient.get("name", "")).strip()
    address = str(patient.get("address", "")).strip()
    if name:
        patient_lines.append(name)
    if address:
        patient_lines.extend(address.splitlines())
    left_paragraph = Paragraph("<br/>".join(patient_lines), styles["small_left"])

    right_lines = [
        f"Facture n° {invoice.get('number', invoice.get('id', ''))}",
        f"Date {invoice.get('date', '')}",
        "TVA non applicable, art. 293 B du CGI",
    ]
    right_paragraph = Paragraph("<br/>".join(right_lines), styles["small_right"])
    current_y = _draw_paragraph_table(
        pdf,
        left_paragraph,
        right_paragraph,
        x=left_margin,
        y=current_y - 8,
        width=usable_width,
    )
    current_y -= 16

    current_y = _draw_lines_table(pdf, invoice, styles, x=left_margin, y=current_y, width=usable_width)
    current_y -= 20

    current_y = _draw_totals(pdf, invoice.get("totals", {}), styles, x=left_margin, y=current_y, width=usable_width)
    current_y -= 30

    legal_lines = [
        "Cette facture peut être transmise à votre mutuelle…",
        f"Document généré le {invoice.get('generated_on', '')}",
    ]
    for text in legal_lines:
        para = Paragraph(text, styles["legal"])
        w, h = para.wrapOn(pdf, usable_width, current_y)
        para.drawOn(pdf, left_margin, current_y - h)
        current_y -= h + 4

    _draw_signature(pdf, assets, styles, x=left_margin, y=current_y - 10, width=usable_width, right_margin=right_margin)

    pdf.showPage()
    pdf.save()
    LOGGER.info("pdf.fallback ok pour %s", invoice.get("id", "temp"))


def to_pdf(docx_path: Path, invoice: Optional[Dict] = None, assets: Optional[AssetPaths] = None,
           *, output_dir: Optional[Path] = None, output_name: Optional[str] = None) -> Path:
    """Convertit un DOCX en PDF en essayant LibreOffice puis ReportLab."""

    docx_path = Path(docx_path)
    if output_dir is None:
        output_dir = docx_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    if output_name is None:
        output_name = docx_path.with_suffix(".pdf").name
    pdf_path = output_dir / output_name

    if soffice_available():  # pragma: no branch - simple condition
        try:
            subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(docx_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if pdf_path.exists() and pdf_path.stat().st_size >= MIN_PDF_SIZE:
                LOGGER.info("pdf.soffice ok pour %s", docx_path.name)
                return pdf_path
            LOGGER.warning("PDF généré par LibreOffice invalide (%s)", pdf_path)
        except Exception as exc:  # pragma: no cover - dépend de l'environnement
            LOGGER.warning("Conversion LibreOffice impossible: %s", exc)
    if pdf_path.exists():
        pdf_path.unlink()
    if invoice is None or assets is None:
        raise ValueError("Fallback PDF requires invoice data and assets")
    _reportlab_pdf(invoice, assets, pdf_path)
    if pdf_path.stat().st_size < MIN_PDF_SIZE:
        raise RuntimeError("PDF fallback trop léger, génération invalide")
    return pdf_path


__all__ = ["to_pdf", "soffice_available", "fallback_ready"]
