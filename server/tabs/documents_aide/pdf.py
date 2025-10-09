"""Génération du PDF et des aperçus pour les documents d'aide."""

from __future__ import annotations

import datetime as _dt
import io
from dataclasses import dataclass
from typing import List, Sequence
from xml.sax.saxutils import escape

from reportlab.graphics import renderPM
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


@dataclass
class ModuleRender:
    """Structure contenant les informations prêtes à être composées."""

    id: str
    title: str
    content: str
    summary: str


def _build_styles() -> dict:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('ModuleHeading', parent=styles['Heading1'], spaceAfter=8))
    styles.add(ParagraphStyle('SubHeading', parent=styles['Heading2'], spaceAfter=4))
    styles.add(ParagraphStyle('Encadre', parent=styles['Normal'], backColor=colors.HexColor('#f0f4ff'), leftIndent=6, rightIndent=6, spaceBefore=6, spaceAfter=6))
    styles.add(ParagraphStyle('Footnote', parent=styles['Normal'], fontSize=9, textColor=colors.grey))
    return styles


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace('\n', '<br/>'), style)


def _render_markdown(content: str, styles: dict) -> List[Paragraph]:
    lines = content.splitlines()
    story: List[Paragraph] = []
    buffer: List[str] = []
    mode = 'paragraph'

    def flush_buffer():
        nonlocal buffer, mode
        if not buffer:
            return
        if mode == 'list':
            for item in buffer:
                story.append(_paragraph(f"• {item}", styles['Normal']))
        else:
            story.append(_paragraph('\n'.join(buffer), styles['Normal']))
        buffer = []
        mode = 'paragraph'

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_buffer()
            story.append(Spacer(1, 6))
            continue
        if line.startswith('### '):
            flush_buffer()
            story.append(_paragraph(line[4:], styles['SubHeading']))
            continue
        if line.startswith('## '):
            flush_buffer()
            story.append(_paragraph(line[3:], styles['Heading2']))
            continue
        if line.startswith('# '):
            flush_buffer()
            story.append(_paragraph(line[2:], styles['ModuleHeading']))
            continue
        if line.startswith('> '):
            flush_buffer()
            story.append(_paragraph(line[2:], styles['Encadre']))
            continue
        if line.startswith('- '):
            if mode != 'list':
                flush_buffer()
                mode = 'list'
            buffer.append(line[2:])
            continue
        if line[0].isdigit() and line[1:2] == '.':
            flush_buffer()
            story.append(_paragraph(line, styles['Normal']))
            continue
        buffer.append(raw)
    flush_buffer()
    return story


def _footer(canvas, doc):  # pragma: no cover - dessin direct
    canvas.saveState()
    canvas.setFont('Helvetica', 9)
    footer_text = f"Document éducatif – { _dt.date.today().strftime('%d/%m/%Y') } – Page {doc.page}"  # type: ignore[attr-defined]
    canvas.drawString(20 * mm, 15 * mm, footer_text)
    canvas.restoreState()


def build_pdf(modules: Sequence[ModuleRender], patient_name: str, langage: str, notes: str = '', cabinet: str = 'Cabinet') -> bytes:
    """Compose le PDF final et renvoie les octets."""

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=f"Documents d'aide - {patient_name}",
        author=cabinet,
    )
    styles = _build_styles()
    story: List = []

    # Page de garde
    story.append(_paragraph('Documents d\'aide personnalisés', styles['Title']))
    story.append(Spacer(1, 12))
    info_table = Table(
        [
            ['Patient·e', patient_name],
            ['Mode de langage', 'Tutoiement' if langage == 'tu' else 'Vouvoiement'],
            ['Généré le', _dt.datetime.now().strftime('%d/%m/%Y %H:%M')],
            ['Cabinet', cabinet],
        ],
        style=TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f6f6f6')),
                ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
                ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.grey),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ]
        ),
        hAlign='LEFT',
        colWidths=[80 * mm, 80 * mm],
    )
    story.append(info_table)
    if notes:
        story.append(Spacer(1, 12))
        story.append(_paragraph('Notes praticien·ne', styles['Heading2']))
        story.append(_paragraph(notes, styles['Normal']))
    story.append(PageBreak())

    for index, module in enumerate(modules, start=1):
        story.append(_paragraph(f"{index}. {module.title}", styles['ModuleHeading']))
        story.extend(_render_markdown(module.content, styles))
        story.append(Spacer(1, 12))
    if not modules:
        story.append(_paragraph('Aucun module sélectionné.', styles['Normal']))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer.read()


def build_preview(modules: Sequence[ModuleRender], patient_name: str) -> bytes:
    """Génère une image PNG simplifiée présentant le sommaire."""

    width, height = 595, 842
    drawing = Drawing(width, height)
    drawing.add(Rect(0, 0, width, height, fillColor=colors.white, strokeColor=colors.HexColor('#d0d7ff'), strokeWidth=1))
    y = height - 60
    drawing.add(String(40, y, 'Aperçu documents d\'aide', fontSize=20, fontName='Helvetica-Bold'))
    y -= 30
    drawing.add(String(40, y, f'Patient·e : {patient_name}', fontSize=14, fontName='Helvetica'))
    y -= 40
    drawing.add(String(40, y, 'Modules sélectionnés :', fontSize=12, fontName='Helvetica-Bold'))
    y -= 24
    if not modules:
        drawing.add(String(60, y, '• Aucun module pour le moment', fontSize=11, fontName='Helvetica-Oblique'))
    else:
        for module in modules[:6]:
            drawing.add(String(60, y, f'• {module.title}', fontSize=11, fontName='Helvetica'))
            y -= 22
            if y < 80:
                break
    return renderPM.drawToString(drawing, fmt='PNG')
