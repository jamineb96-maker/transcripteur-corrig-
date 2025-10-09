#!/usr/bin/env python3
"""Synchronise une copie minimale de Three.js dans static/vendor."""

from __future__ import annotations

import base64
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
nm = ROOT / "node_modules" / "three"
dest = ROOT / "static" / "vendor" / "three"
needed = [
    ("build/three.module.js", "build/three.module.js"),
    ("examples/jsm/controls/OrbitControls.js", "examples/jsm/controls/OrbitControls.js"),
    ("examples/jsm/loaders/GLTFLoader.js", "examples/jsm/loaders/GLTFLoader.js"),
    ("examples/jsm/loaders/DRACOLoader.js", "examples/jsm/loaders/DRACOLoader.js"),
    ("examples/jsm/libs/meshopt_decoder.module.js", "examples/jsm/libs/meshopt_decoder.module.js"),
]
draco_dir = nm / "examples/jsm/libs/draco"


def copyfile(src_rel: str, dst_rel: str) -> None:
    src = nm / src_rel
    dst = dest / dst_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> int:
    if not nm.exists():
        print("node_modules/three introuvable, copie vendor ignorée", file=sys.stderr)
        return 0
    for src, dst in needed:
        copyfile(src, dst)
    if draco_dir.exists():
        out = dest / "examples/jsm/libs/draco"
        out.mkdir(parents=True, exist_ok=True)
        for filename in ["draco_decoder.js", "draco_wasm_wrapper.js"]:
            shutil.copy2(draco_dir / filename, out / filename)
        wasm_src = draco_dir / "draco_decoder.wasm"
        if wasm_src.exists():
            encoded = base64.b64encode(wasm_src.read_bytes()).decode("ascii")
            (out / "draco_decoder.wasm.base64").write_text(encoded, encoding="utf-8")
            wasm_dest = out / "draco_decoder.wasm"
            if not wasm_dest.exists():
                wasm_dest.write_bytes(base64.b64decode(encoded))
    print("Three.js vendorisée dans static/vendor/three")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
