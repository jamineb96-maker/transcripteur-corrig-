"""Outils de génération de graphiques pour les exports Budget."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

try:  # pragma: no cover - dépendance optionnelle
    from reportlab.graphics import renderPDF, renderPM
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors
    HAS_REPORTLAB = True
except ModuleNotFoundError:  # pragma: no cover - fallback pour les tests
    Drawing = object  # type: ignore
    Line = Rect = String = None  # type: ignore
    colors = None  # type: ignore
    renderPDF = renderPM = None  # type: ignore
    HAS_REPORTLAB = False

from .budget_engine import ActivityResult, RecoveryResult


def _format_value(value: float) -> str:
    return f"{value:.1f}".replace('.', ',')


def build_spoon_balance(stock: float, cost: float, recovery: float) -> Drawing:
    if not HAS_REPORTLAB:
        raise RuntimeError('reportlab_missing')
    width, height = 420, 160
    drawing = Drawing(width, height)
    baseline_y = 50
    max_total = max(stock, cost + recovery, 1.0)
    bar_width = width - 80
    scale = bar_width / max_total

    # Stock
    stock_width = stock * scale
    drawing.add(Rect(40, baseline_y, stock_width, 30, fillColor=colors.HexColor('#2563eb'), strokeColor=None))
    drawing.add(String(40, baseline_y + 36, f"Stock { _format_value(stock)}", fontSize=11, fillColor=colors.HexColor('#1e3a8a')))

    # Coût
    cost_width = cost * scale
    drawing.add(Rect(40, baseline_y - 40, cost_width, 30, fillColor=colors.HexColor('#dc2626'), strokeColor=None))
    drawing.add(String(40, baseline_y - 46, f"Coût { _format_value(cost)}", fontSize=11, fillColor=colors.HexColor('#7f1d1d')))

    # Récupération
    rec_width = recovery * scale
    drawing.add(Rect(40, baseline_y - 80, rec_width, 30, fillColor=colors.HexColor('#16a34a'), strokeColor=None))
    drawing.add(String(40, baseline_y - 86, f"Récup { _format_value(recovery)}", fontSize=11, fillColor=colors.HexColor('#14532d')))

    return drawing


def build_timeline(
    consumption: Sequence[ActivityResult],
    recovery: Sequence[RecoveryResult],
    period_label: str,
) -> Drawing:
    if not HAS_REPORTLAB:
        raise RuntimeError('reportlab_missing')
    width, height = 480, 180
    drawing = Drawing(width, height)
    baseline_y = 70
    drawing.add(String(20, height - 30, f"Timeline effort/repos ({period_label})", fontSize=12, fillColor=colors.HexColor('#0f172a')))
    drawing.add(Line(20, baseline_y, width - 20, baseline_y, strokeColor=colors.HexColor('#334155'), strokeWidth=1))

    total_cost = sum(max(item.value, 0.0) for item in consumption)
    total_recovery = sum(max(item.value, 0.0) for item in recovery)
    total = total_cost + total_recovery
    if total <= 0:
        drawing.add(String(20, baseline_y + 10, "Aucune donnée disponible.", fontSize=11))
        return drawing

    scale = (width - 60) / total
    cursor = 30.0

    def _add_block(label: str, value: float, color: colors.Color, offset: float) -> None:
        nonlocal cursor
        block_width = max(value * scale, 6)
        drawing.add(Rect(cursor, baseline_y + offset, block_width, 24, fillColor=color, strokeColor=None, strokeWidth=0))
        drawing.add(String(cursor + 2, baseline_y + offset + 26, f"{label} ({_format_value(value)})", fontSize=9, fillColor=colors.HexColor('#0f172a')))
        cursor += block_width + 6

    for item in consumption:
        _add_block(item.label, max(item.value, 0.0), colors.HexColor('#f87171'), -26)

    cursor = 30.0
    for item in recovery:
        _add_block(item.label, max(item.value, 0.0), colors.HexColor('#4ade80'), 10)

    return drawing


def draw_on_canvas(canvas, drawing: Drawing, x: float, y: float) -> None:
    """Dessine un objet ReportLab sur le canvas à la position donnée."""

    if not HAS_REPORTLAB:
        raise RuntimeError('reportlab_missing')
    renderPDF.draw(drawing, canvas, x, y)


def save_as_png(drawing: Drawing, path: Path, width: int = 480, height: int = 200) -> Path:
    """Exporte le dessin au format PNG (utilisé pour l'export DOCX)."""

    if not HAS_REPORTLAB:
        raise RuntimeError('reportlab_missing')
    path.parent.mkdir(parents=True, exist_ok=True)
    renderPM.drawToFile(drawing, str(path), fmt='PNG', dpi=180)
    return path
