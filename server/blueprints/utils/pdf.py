"""Utilities to render printable PDFs from HTML content."""
from __future__ import annotations

import io
import logging
from pathlib import Path

from cairosvg import svg2pdf
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

LOGGER = logging.getLogger(__name__)

_DEFAULT_FONT_REGISTERED = False


def _register_default_font() -> None:
    global _DEFAULT_FONT_REGISTERED
    if _DEFAULT_FONT_REGISTERED:
        return
    try:
        pdfmetrics.registerFont(TTFont("Inter", "assets/fonts/Inter-Regular.ttf"))
        _DEFAULT_FONT_REGISTERED = True
    except Exception:  # pragma: no cover - optional font
        LOGGER.debug("Inter font unavailable, falling back to Helvetica")
        _DEFAULT_FONT_REGISTERED = True


def _wrap_html_in_svg(html: str) -> bytes:
    # CairoSVG converts SVG documents, we wrap the HTML using foreignObject.
    svg_template = f"""
    <svg xmlns='http://www.w3.org/2000/svg' width='595px' height='842px'>
        <foreignObject width='100%' height='100%'>
            <body xmlns='http://www.w3.org/1999/xhtml'>
                {html}
            </body>
        </foreignObject>
    </svg>
    """
    return svg_template.encode("utf-8")


def _fallback_reportlab(html: str, output_path: Path) -> None:
    _register_default_font()
    buffer = io.BytesIO()
    pdf_canvas = canvas.Canvas(buffer, pagesize=A4)
    pdf_canvas.setFont("Inter" if "Inter" in pdfmetrics.getRegisteredFontNames() else "Helvetica", 11)
    width, height = A4
    top = height - 40
    for raw_line in html.splitlines():
        line = raw_line.strip()
        if not line:
            top -= 14
            continue
        while line:
            chunk = line[:110]
            line = line[110:]
            pdf_canvas.drawString(40, top, chunk)
            top -= 14
            if top < 40:
                pdf_canvas.showPage()
                top = height - 40
    pdf_canvas.save()
    output_path.write_bytes(buffer.getvalue())


def html_to_pdf(html: str, output_path: Path) -> Path:
    """Render the provided HTML into a PDF file.

    Parameters
    ----------
    html:
        HTML document as string.
    output_path:
        Destination path.
    """

    try:
        svg2pdf(bytestring=_wrap_html_in_svg(html), write_to=str(output_path))
        return output_path
    except Exception as exc:  # pragma: no cover - CairoSVG fallback
        LOGGER.warning("CairoSVG rendering failed, fallback to ReportLab: %s", exc)
        _fallback_reportlab(html, output_path)
        return output_path


__all__ = ["html_to_pdf"]
