import os
import sys
from pathlib import Path
import types

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("RESEARCH_V2_REQUEST_DELAY", "0")
os.environ.setdefault("RESEARCH_V2_MAX_RETRIES", "0")

if "server" not in sys.modules:
    server_module = types.ModuleType("server")
    services_module = types.ModuleType("server.services")
    openai_module = types.ModuleType("server.services.openai_client")
    openai_module.DEFAULT_TEXT_MODEL = "test-model"

    def _noop_client():
        return None

    openai_module.get_openai_client = _noop_client
    services_module.openai_client = openai_module
    server_module.services = services_module
    sys.modules["server"] = server_module
    sys.modules["server.services"] = services_module
    sys.modules["server.services.openai_client"] = openai_module
