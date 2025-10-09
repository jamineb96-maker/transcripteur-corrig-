"""Smoke test for the Anatomy 3D viewer assets."""

from __future__ import annotations

from typing import Final

import requests

BASE_URL: Final[str] = "http://127.0.0.1:1421"


def _get(path: str) -> requests.Response:
    response = requests.get(f"{BASE_URL}{path}", timeout=5)
    response.raise_for_status()
    return response


def main() -> int:
    health = _get("/anatomy3d/health").json()
    print("Health:", health)
    assert "ok" in health, "health payload missing 'ok' flag"
    for url in [
        "/static/vendor/three/build/three.module.js",
        "/static/vendor/three/examples/jsm/controls/OrbitControls.js",
    ]:
        asset = _get(url)
        assert asset.status_code == 200, f"Asset check failed for {url}"
    print("Smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
