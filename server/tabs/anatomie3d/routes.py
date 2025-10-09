"""Routes de base pour l'onglet Anatomie 3D."""

from __future__ import annotations

from pathlib import Path

from flask import current_app, jsonify

from ...utils.three_vendor import ensure_draco_decoder

from . import bp


@bp.get("/ping")
def ping() -> tuple[str, int] | tuple[dict[str, object], int] | dict[str, object]:
    """Endpoint de test renvoyant un message simple."""

    return jsonify({"success": True, "data": "anatomie3d-pong"})


@bp.get("/health")
def health() -> tuple[str, int] | tuple[dict[str, object], int] | dict[str, object]:
    """Expose l'état des vendors requis pour le viewer 3D."""

    static_root = Path(current_app.static_folder)
    ensure_draco_decoder(static_root)
    vendor_root = static_root / "vendor" / "three"
    required = [
        "build/three.module.js",
        "examples/jsm/controls/OrbitControls.js",
        "examples/jsm/loaders/GLTFLoader.js",
        "examples/jsm/loaders/DRACOLoader.js",
        "examples/jsm/libs/meshopt_decoder.module.js",
        "examples/jsm/libs/draco/draco_decoder.wasm",
    ]
    missing = [
        str(path)
        for path in (vendor_root / item for item in required)
        if not path.exists()
    ]
    if missing:
        base64_path = vendor_root / "examples/jsm/libs/draco/draco_decoder.wasm.base64"
        if base64_path.exists():
            missing = [m for m in missing if not m.endswith("draco_decoder.wasm")]
    ok = not missing
    payload = {
        "ok": ok,
        "vendor_present": ok,
        "checked": required,
        "missing": missing,
    }
    return jsonify(payload)
