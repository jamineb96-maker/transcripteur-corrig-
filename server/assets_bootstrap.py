"""Gestion des actifs nécessaires à la facturation."""

from __future__ import annotations

import base64
import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]
CLIENT_DIR = ROOT_DIR / "client"
SERVER_STATIC_DIR = ROOT_DIR / "server" / "static"
INSTANCE_DIR = ROOT_DIR / "instance"
TEMPLATES_DIR = INSTANCE_DIR / "templates"
ASSETS_DIR = INSTANCE_DIR / "assets"
INVOICES_DIR = INSTANCE_DIR / "invoices"
INDEX_PATH = INVOICES_DIR / "index.json"
COUNTER_PATH = INVOICES_DIR / "counter.json"
LOGO_SVG_PATH = ASSETS_DIR / "logo.svg"
LOGO_RASTER_PATH = ASSETS_DIR / "logo.raster.png"
SIGNATURE_PNG_PATH = ASSETS_DIR / "signature.png"

LOGO_SVG_SOURCE = """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 64 64\" fill=\"none\">\n  <g stroke=\"#6C3BA8\" stroke-width=\"3\" stroke-linecap=\"round\" stroke-linejoin=\"round\" fill=\"none\">\n    <!-- Tête stylisée -->\n    <path d=\"M22 10c-9 2-15 11-14 20 1 10 7 14 9 15 2 1 3 4 3 6 0 3 3 5 6 5h5c3 0 5-2 5-5 0-3 1-5 3-6 2-1 8-5 9-15 1-10-6-19-16-21-3-1-9-1-9-1z\"/>\n    <!-- Cerveau schématique -->\n    <path d=\"M25 18c3-3 9-3 12 0 2 2 2 4 1 6 2 1 3 3 2 5-1 3-4 4-7 4-4 0-7-2-8-5-1-2 0-4 2-5-1-2-1-4 0-5z\"/>\n    <circle cx=\"28.5\" cy=\"25\" r=\"1.7\"/>\n    <circle cx=\"36.5\" cy=\"22.5\" r=\"1.7\"/>\n    <path d=\"M28.5 26.7c1.8 1.2 4.2 1.2 6 0\"/>\n  </g>\n</svg>\n"""

SIGNATURE_PNG_B64 = (
    "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"
)


@dataclass(frozen=True)
class AssetPaths:
    """Chemins utiles à la génération des factures."""

    logo_svg: Path
    logo_raster: Path
    signature: Path


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    path.write_text(content, encoding="utf-8")


def _write_binary(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    path.write_bytes(data)


def _decode_signature() -> None:
    raw = base64.b64decode(SIGNATURE_PNG_B64)
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Signature PNG invalide")
    _write_binary(SIGNATURE_PNG_PATH, raw)


def _rasterize_logo() -> None:
    if not LOGO_SVG_PATH.exists():
        return
    svg_mtime = LOGO_SVG_PATH.stat().st_mtime
    needs_render = True
    if LOGO_RASTER_PATH.exists():
        needs_render = LOGO_RASTER_PATH.stat().st_mtime < svg_mtime
    if not needs_render:
        return
    try:
        import cairosvg  # type: ignore

        cairosvg.svg2png(
            url=str(LOGO_SVG_PATH),
            write_to=str(LOGO_RASTER_PATH),
            dpi=300,
        )
        LOGGER.info("assets.rasterized via cairosvg")
        return
    except Exception as exc:  # pragma: no cover - depends on optional deps
        LOGGER.debug("Rasterisation avec CairoSVG indisponible: %s", exc)
    try:
        from svglib.svglib import svg2rlg  # type: ignore
        from reportlab.graphics import renderPM  # type: ignore

        drawing = svg2rlg(str(LOGO_SVG_PATH))
        if drawing:  # type: ignore[truthy-function]
            scale = 1.0
            if drawing.minWidth():
                target_width_pt = 34 / 10 * 72 / 2.54  # 34 mm -> points
                scale = target_width_pt / float(drawing.minWidth())
            drawing.scale(scale, scale)
            renderPM.drawToFile(drawing, str(LOGO_RASTER_PATH), fmt="PNG", dpi=300)
            LOGGER.info("assets.rasterized via svglib")
            return
    except Exception as exc:  # pragma: no cover - optional fallback
        LOGGER.warning("Rasterisation du logo échouée: %s", exc)
    if LOGO_RASTER_PATH.exists():
        return
    try:  # pragma: no cover - dépend d'optional pillow
        from PIL import Image, ImageDraw

        size = (512, 512)
        image = Image.new("RGBA", size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((48, 32, 464, 440), outline="#6C3BA8", width=12)
        draw.arc((160, 160, 352, 320), 200, 340, fill="#6C3BA8", width=10)
        image.save(LOGO_RASTER_PATH, format="PNG")
        LOGGER.info("assets.rasterized via pillow fallback")
        return
    except Exception as exc:  # pragma: no cover - ultime recours
        LOGGER.error("Rasterisation impossible, création d'un PNG neutre: %s", exc)
        LOGO_RASTER_PATH.write_bytes(
            base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg==")
        )


def _ensure_json(path: Path, default) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(default, handle)


def _sync_static_asset(rel_path: str) -> None:
    """Mirror ``server/static`` assets into the ``client`` bundle.

    The Flask application serves ``/static`` from the ``client`` directory, yet
    some legacy assets (such as the bootstrap tabs helper or base theme
    stylesheets) still live under ``server/static``.  In development those files
    were manually copied which meant a fresh checkout would miss them and the UI
    would fail to initialise (stuck on the loading screen, missing dark-mode
    toggle, etc.).

    To make the bootstrap process deterministic we copy the required files on
    startup when ``ensure_assets`` is invoked.  The copy is skipped if the
    destination already contains identical content so repeated calls remain
    cheap.
    """

    src = SERVER_STATIC_DIR / rel_path
    if not src.exists():
        LOGGER.warning("static_asset_missing", extra={"asset": rel_path})
        return

    dest = CLIENT_DIR / rel_path
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        payload = src.read_bytes()
        if dest.exists() and dest.read_bytes() == payload:
            return
        dest.write_bytes(payload)
        LOGGER.debug("static_asset_synced", extra={"asset": rel_path})
    except OSError as exc:  # pragma: no cover - filesystem errors are runtime only
        LOGGER.warning(
            "static_asset_sync_failed",
            extra={"asset": rel_path, "error": str(exc)},
        )


def ensure_assets() -> AssetPaths:
    """Garantit la présence de l'arborescence et des actifs nécessaires."""

    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)

    _ensure_json(INDEX_PATH, [])
    _ensure_json(COUNTER_PATH, {})

    _write_text(LOGO_SVG_PATH, LOGO_SVG_SOURCE)
    _decode_signature()
    _rasterize_logo()

    static_assets = [
        "css/theme-base.css",
        "js/tabs_bootstrap.js",
    ]
    for asset in static_assets:
        _sync_static_asset(asset)

    return AssetPaths(
        logo_svg=LOGO_SVG_PATH,
        logo_raster=LOGO_RASTER_PATH,
        signature=SIGNATURE_PNG_PATH,
    )


def refresh_logo_cache() -> Path:
    """Recalcule la version raster du logo et renvoie son chemin."""

    _rasterize_logo()
    return LOGO_RASTER_PATH


__all__ = [
    "ensure_assets",
    "refresh_logo_cache",
    "AssetPaths",
    "LOGO_SVG_SOURCE",
    "SIGNATURE_PNG_B64",
]
