"""SVG invoice rendering helpers."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import InvalidOperation, ROUND_HALF_UP, Decimal
import html
from pathlib import Path
from typing import Dict, List, Sequence

import cairosvg

from .assets_svg import generate_logo_svg, generate_signature_svg

SOLIDARITY_THRESHOLD = Decimal("60")
DEFAULT_DESC = "Consultation psy"
DEFAULT_DURATION = "50 min"


@dataclass
class InvoiceLine:
    date: str
    desc: str
    duration: str
    unit_price: Decimal
    quantity: Decimal

    @property
    def total(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, "Noto Sans", "Liberation Sans", sans-serif'
COL_WIDTHS = [22.0, 90.0, 18.0, 22.0, 28.0]
HEADER_HEIGHT = 8.0
MIN_LINE_HEIGHT = 7.0


def _esc(value: object) -> str:
    return html.escape(str(value) if value is not None else "")


def service_title_from_amount(amount: object) -> str:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return DEFAULT_DESC
    return "Consultation tarif solidaire" if value < SOLIDARITY_THRESHOLD else DEFAULT_DESC


def format_eur(amount: float | Decimal) -> str:
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer_part, fractional_part = f"{value:.2f}".split(".")
    integer_part_with_sep = " ".join(
        [integer_part[max(i - 3, 0) : i] for i in range(len(integer_part), 0, -3)][::-1]
    )
    formatted = f"{integer_part_with_sep},{fractional_part}"
    return formatted.replace(" ", "\u202F") + "\u202F€"


def fmt_date_iso_to_fr(iso: str) -> str:
    date_obj = dt.date.fromisoformat(iso)
    return date_obj.strftime("%d/%m/%Y")


def next_invoice_number(registry: Dict[str, object]) -> str:
    today = dt.date.today()
    year = str(today.year)
    counters = registry.setdefault("counters", {})  # type: ignore[assignment]
    if not isinstance(counters, dict):
        counters = {}
        registry["counters"] = counters
    current = int(counters.get(year, 0))
    current += 1
    counters[year] = current
    return f"{year}-{current:03d}"


def _wrap_text(text: str, width_mm: float, max_lines: int = 2) -> List[str]:
    if not text:
        return [""]
    approx_chars = max(int(width_mm / 2.2), 8)
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) <= approx_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if len(lines) < max_lines and current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    if words and len(lines) == max_lines and sum(len(line) for line in lines) < len(" ".join(words)):
        lines[-1] = lines[-1][: max(0, approx_chars - 1)] + "…"
    if not lines:
        lines = [text[:approx_chars]]
    return lines


def _line_height(desc_lines: Sequence[str]) -> float:
    lines = max(len(desc_lines), 1)
    return max(MIN_LINE_HEIGHT, 6.0 * lines)


def _build_table_rows(lines: Sequence[InvoiceLine], start_y: float) -> Dict[str, object]:
    rows = []
    y = start_y + HEADER_HEIGHT
    total_height = HEADER_HEIGHT
    for line in lines:
        desc_lines = _wrap_text(line.desc, COL_WIDTHS[1])
        height = _line_height(desc_lines)
        row_info = {
            "y": y,
            "height": height,
            "desc_lines": desc_lines,
            "line": line,
        }
        rows.append(row_info)
        y += height
        total_height += height
    return {"rows": rows, "total_height": total_height}


def render_invoice_svg(context: Dict[str, object]) -> str:
    company = context.get("company", {})
    invoice = context.get("invoice", {})
    lines_context = context.get("lines", [])
    lines: List[InvoiceLine] = []
    for payload in lines_context:
        unit_price = Decimal(str(payload.get("unit_price", payload.get("pu", "0"))))
        qty = Decimal(str(payload.get("quantity", payload.get("qty", "1"))))
        desc_value = payload.get("desc")
        if desc_value is None or not str(desc_value).strip():
            desc_value = service_title_from_amount(payload.get("unit_price", payload.get("pu", unit_price)))
        line = InvoiceLine(
            date=str(payload.get("date", invoice.get("date"))),
            desc=str(desc_value),
            duration=str(payload.get("duration", payload.get("duree", DEFAULT_DURATION))),
            unit_price=unit_price,
            quantity=qty,
        )
        lines.append(line)
    if not lines:
        amount = Decimal(str(invoice.get("amount", "0")))
        lines.append(
            InvoiceLine(
                date=str(invoice.get("date")),
                desc=service_title_from_amount(amount),
                duration=DEFAULT_DURATION,
                unit_price=amount,
                quantity=Decimal("1"),
            )
        )

    subtotal = sum((line.total for line in lines), Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    invoice_date_iso = str(invoice.get("date", dt.date.today().isoformat()))
    invoice_date_fr = invoice.get("date_fr") or fmt_date_iso_to_fr(invoice_date_iso)
    today_fr = context.get("today_fr") or fmt_date_iso_to_fr(dt.date.today().isoformat())

    table = _build_table_rows(lines, start_y=85.0)
    table_height = table["total_height"]
    totals_y = 85.0 + table_height + 6.0

    patient_address = context.get("patient_address", "")
    address_lines = [line.strip() for line in str(patient_address).splitlines() if line.strip()]
    if not address_lines:
        address_lines = []

    logo_svg = generate_logo_svg(str(company.get("name", "")), str(company.get("subtitle", "")), str(company.get("accent_color", "")))
    signature_svg = generate_signature_svg(str(company.get("name", "")))

    company_name = _esc(company.get("name", ""))
    company_subtitle = _esc(company.get("subtitle", ""))
    address_lines_company = [line for line in str(company.get("address", "")).splitlines() if line]
    company_email = _esc(company.get("email", ""))
    company_phone = _esc(company.get("phone", ""))
    header_block = f"""
  <g transform="translate(15,18)">
    <g transform="scale(1)">{logo_svg}</g>
  </g>
  <g transform="translate(38,20)" fill="#111">
    <text font-family='{FONT_STACK}' font-size="10" font-weight="600">{company_name}</text>
    <text y="7" font-family='{FONT_STACK}' font-size="9">{company_subtitle}</text>
"""
    address_y = 14
    for idx, line in enumerate(address_lines_company):
        header_block += f"    <text y=\"{address_y + idx * 5}\" font-family='{FONT_STACK}' font-size=\"8.5\" fill=\"#444\">{_esc(line)}</text>\n"
    contact_line = " — ".join(filter(None, [company_email, company_phone]))
    if contact_line:
        footer_offset = address_y + len(address_lines_company) * 5 + 5
        header_block += f"    <text y=\"{footer_offset}\" font-family='{FONT_STACK}' font-size=\"8.5\" fill=\"#444\">{contact_line}</text>\n"
    header_block += "  </g>\n"

    cartouche = f"""
  <g transform="translate(135,17)">
    <rect width="60" height="26" rx="1.5" ry="1.5" fill="#fff" stroke="#666" stroke-width="0.35" />
    <text x="30" y="9" text-anchor="middle" font-family='{FONT_STACK}' font-size="5.6" font-weight="700" letter-spacing="0.2">FACTURE</text>
    <line x1="8" x2="52" y1="11" y2="11" stroke="{_esc(company.get('accent_color','#2B6CB0'))}" stroke-width="0.6" />
    <text x="10" y="17" font-family='{FONT_STACK}' font-size="3.5">N° {_esc(invoice.get('number',''))}</text>
    <text x="10" y="22" font-family='{FONT_STACK}' font-size="3.5">Date {_esc(invoice_date_fr)}</text>
  </g>
"""

    recipient_block = "  <g transform=\"translate(15,52)\">\n"
    recipient_block += f"    <text font-family='{FONT_STACK}' font-size='3.5' font-weight='600'>Destinataire</text>\n"
    recipient_block += f"    <text y='6' font-family='{FONT_STACK}' font-size='4'>{_esc(context.get('patient_name',''))}</text>\n"
    for idx, line in enumerate(address_lines):
        recipient_block += f"    <text y='{12 + idx * 4}' font-family='{FONT_STACK}' font-size='3.2' fill='#444'>{_esc(line)}</text>\n"
    recipient_block += "  </g>\n"

    table_header = [
        "Date",
        "Prestation",
        "Durée",
        "PU (€)",
        "Montant (€)",
    ]

    column_offsets = [0.0]
    for width in COL_WIDTHS:
        column_offsets.append(column_offsets[-1] + width)

    table_svg = "  <g transform=\"translate(15,85)\">\n"
    table_svg += "    <rect width='180' height='" + f"{table_height:.2f}" + "' fill='none' stroke='#666' stroke-width='0.35' />\n"
    table_svg += "    <rect width='180' height='8' fill='#f7f9fc' stroke='#666' stroke-width='0.35' />\n"
    for idx, title in enumerate(table_header):
        x = column_offsets[idx] + 2
        table_svg += (
            f"    <text x='{x}' y='5' font-family='{FONT_STACK}' font-size='3.5' font-weight='600' text-transform='uppercase'>{_esc(title)}</text>\n"
        )
    for offset in column_offsets[1:-1]:
        table_svg += f"    <line x1='{offset}' x2='{offset}' y1='0' y2='{table_height:.2f}' stroke='#666' stroke-width='0.35' />\n"

    current_y = HEADER_HEIGHT
    for row in table["rows"]:
        height = row["height"]
        table_svg += f"    <line x1='0' x2='180' y1='{current_y + height:.2f}' y2='{current_y + height:.2f}' stroke='#666' stroke-width='0.35' />\n"
        line: InvoiceLine = row["line"]
        desc_lines = row["desc_lines"]
        table_svg += f"    <text x='2' y='{current_y + 4:.2f}' font-family='{FONT_STACK}' font-size='3.4'>{_esc(fmt_date_iso_to_fr(line.date))}</text>\n"
        for i, desc in enumerate(desc_lines):
            table_svg += f"    <text x='{column_offsets[1] + 2}' y='{current_y + 4 + i * 4:.2f}' font-family='{FONT_STACK}' font-size='3.4'>{_esc(desc)}</text>\n"
        table_svg += f"    <text x='{column_offsets[2] + 2}' y='{current_y + 4:.2f}' font-family='{FONT_STACK}' font-size='3.4'>{_esc(line.duration)}</text>\n"
        table_svg += f"    <text x='{column_offsets[3] + COL_WIDTHS[3] - 2}' y='{current_y + 4:.2f}' font-family='{FONT_STACK}' font-size='3.4' text-anchor='end'>{_esc(format_eur(line.unit_price))}</text>\n"
        table_svg += f"    <text x='{column_offsets[4] + COL_WIDTHS[4] - 2}' y='{current_y + 4:.2f}' font-family='{FONT_STACK}' font-size='3.4' text-anchor='end'>{_esc(format_eur(line.total))}</text>\n"
        current_y += height
    table_svg += "  </g>\n"

    totals_x = 15 + 100
    totals_svg = f"""
  <g transform="translate({totals_x},{totals_y})">
    <rect width="80" height="28" fill="#fff" stroke="#666" stroke-width="0.35" />
    <line x1="4" x2="76" y1="18" y2="18" stroke="{_esc(company.get('accent_color','#2B6CB0'))}" stroke-width="0.6" />
    <text x="4" y="8" font-family='{FONT_STACK}' font-size="3.4">Sous-total</text>
    <text x="76" y="8" font-family='{FONT_STACK}' font-size="3.4" text-anchor="end">{_esc(format_eur(subtotal))}</text>
    <text x="4" y="13" font-family='{FONT_STACK}' font-size="3.4">TVA (0 %)</text>
    <text x="76" y="13" font-family='{FONT_STACK}' font-size="3.4" text-anchor="end">0,00\u202F€</text>
    <text x="4" y="23" font-family='{FONT_STACK}' font-size="4.2" font-weight="600">TOTAL TTC</text>
    <text x="76" y="23" font-family='{FONT_STACK}' font-size="4.2" font-weight="600" text-anchor="end">{_esc(format_eur(subtotal))}</text>
    <text x="4" y="27" font-family='{FONT_STACK}' font-size="3" fill="#444">{_esc(company.get('vat_note',''))}</text>
  </g>
"""

    footer_y = 297 - 15 - 20
    regulation_parts = []
    if context.get("paid_via"):
        regulation_parts.append(f"Règlement : {str(context.get('paid_via')).title()}")
    if company.get("iban"):
        regulation_parts.append(f"IBAN {company['iban']}")
    if company.get("bic"):
        regulation_parts.append(f"BIC {company['bic']}")
    regulation_text = " — ".join(regulation_parts)

    footer_svg = "  <g transform=\"translate(15,{})\">\n".format(footer_y)
    if regulation_text:
        footer_svg += f"    <text font-family='{FONT_STACK}' font-size='3.2'>{_esc(regulation_text)}</text>\n"
    footer_svg += (
        f"    <text y='6' font-family='{FONT_STACK}' font-size='3.2'>Fait à {_esc(company.get('city',''))}, le {_esc(today_fr)}</text>\n"
    )
    footer_svg += f"    <text y='18' font-family='{FONT_STACK}' font-size='3' fill='#666'>{_esc(company.get('legal_footer',''))}</text>\n"
    footer_svg += "  </g>\n"

    signature_block = f"""
  <g transform="translate(150,{footer_y - 4})">
    <text y="-2" font-family='{FONT_STACK}' font-size="3" fill="#444">Signature</text>
    <g transform="scale(1)">{signature_svg}</g>
  </g>
"""

    svg = f"""<svg width="210mm" height="297mm" viewBox="0 0 210 297" xmlns="http://www.w3.org/2000/svg">
  <style>
    text {{ fill: #111; }}
  </style>
{header_block}{cartouche}{recipient_block}{table_svg}{totals_svg}{footer_svg}{signature_block}
</svg>"""
    return svg


def svg_to_pdf(svg_str: str, _out_path: Path | None = None) -> bytes:
    return cairosvg.svg2pdf(bytestring=svg_str.encode("utf-8"))


def save_invoice_files(svg_str: str, pdf_path: Path, svg_path: Path, pdf_bytes: bytes | None = None) -> None:
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_svg = svg_path.with_suffix(svg_path.suffix + ".tmp")
    tmp_svg.write_text(svg_str, encoding="utf-8")
    tmp_svg.replace(svg_path)
    if pdf_bytes is not None:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_pdf = pdf_path.with_suffix(pdf_path.suffix + ".tmp")
        tmp_pdf.write_bytes(pdf_bytes)
        tmp_pdf.replace(pdf_path)


def render_and_save(context: Dict[str, object]) -> Dict[str, object]:
    paths = context.get("paths", {})
    svg_path = Path(paths.get("svg")) if paths.get("svg") else None
    pdf_path = Path(paths.get("pdf")) if paths.get("pdf") else None
    if svg_path is None or pdf_path is None:
        raise ValueError("Both SVG and PDF paths must be provided in context['paths']")
    svg = render_invoice_svg(context)
    pdf_bytes = svg_to_pdf(svg, pdf_path)
    save_invoice_files(svg, pdf_path, svg_path, pdf_bytes=pdf_bytes)
    return {"paths": {"svg": str(svg_path), "pdf": str(pdf_path)}, "svg": svg, "pdf_bytes": pdf_bytes}


__all__ = [
    "DEFAULT_DESC",
    "DEFAULT_DURATION",
    "service_title_from_amount",
    "format_eur",
    "fmt_date_iso_to_fr",
    "next_invoice_number",
    "render_invoice_svg",
    "svg_to_pdf",
    "save_invoice_files",
    "render_and_save",
]
