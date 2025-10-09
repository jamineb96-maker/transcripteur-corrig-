"""Pytest bootstrap to load service modules without initialising the full Flask app."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent
SERVER_DIR = ROOT / "server"
SERVICES_DIR = SERVER_DIR / "services"


def _ensure_stub_package() -> ModuleType:
    if "server" in sys.modules:
        return sys.modules["server"]
    server_stub = ModuleType("server")
    server_stub.__path__ = [str(SERVER_DIR)]  # type: ignore[attr-defined]
    sys.modules["server"] = server_stub
    services_stub = ModuleType("server.services")
    services_stub.__path__ = [str(SERVICES_DIR)]  # type: ignore[attr-defined]
    sys.modules["server.services"] = services_stub
    setattr(server_stub, "services", services_stub)
    return server_stub


def _load_service_module(name: str) -> None:
    module_name = f"server.services.{name}"
    if module_name in sys.modules:
        return
    target = SERVICES_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossible de charger {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)


_ensure_stub_package()
for _name in ("pii_guard", "research_queries", "library_search"):
    _load_service_module(_name)
