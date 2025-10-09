import json
import importlib
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def library_llm_module(monkeypatch: pytest.MonkeyPatch):
    server_pkg = types.ModuleType("server")
    server_pkg.__path__ = []  # type: ignore[attr-defined]
    services_pkg = types.ModuleType("server.services")
    services_pkg.__path__ = []  # type: ignore[attr-defined]
    openai_client_module = types.ModuleType("server.services.openai_client")
    openai_client_module.DEFAULT_TEXT_MODEL = "gpt-test"

    def _not_configured():
        return None

    openai_client_module.get_openai_client = _not_configured  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "server", server_pkg)
    monkeypatch.setitem(sys.modules, "server.services", services_pkg)
    monkeypatch.setitem(sys.modules, "server.services.openai_client", openai_client_module)
    monkeypatch.delitem(sys.modules, "modules.library_llm", raising=False)
    return importlib.import_module("modules.library_llm")


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    def create(self, **_: object) -> _FakeResponse:  # pragma: no cover - trivial
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.completions = _FakeCompletions(content)


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = _FakeChat(content)


@pytest.fixture
def fake_plan_payload() -> str:
    payload = {
        "doc_id": "patient:123",
        "proposed_notions": [
            {
                "title": "Notion",
                "summary": "Résumé",
                "clinical_uses": ["usage"],
                "key_quotes": [
                    {
                        "text": "Citation",
                        "pages": [1],
                        "segment_ids": ["seg_1"],
                    }
                ],
                "limitations_risks": ["risk"],
                "tags": ["tag"],
                "evidence": {"type": "revue", "strength": "faible"},
                "source_spans": ["span"],
                "autosuggest_pre": True,
                "autosuggest_post": False,
                "priority": 0.5,
                "candidate_notion_id": "notion-1",
            }
        ],
    }
    return json.dumps(payload)


def test_propose_notions_logs_with_sanitized_filename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_plan_payload: str,
    library_llm_module,
) -> None:
    library_llm = library_llm_module
    monkeypatch.setattr(library_llm, "LOGS_DIR", tmp_path)
    fake_client = _FakeClient(fake_plan_payload)
    monkeypatch.setattr(library_llm, "get_openai_client", lambda: fake_client)

    result = library_llm.propose_notions(
        "patient:123",
        segments=[{"segment_id": "seg_1", "text": "Texte", "pages": [1]}],
        pseudonymize=False,
    )

    assert result.doc_id == "patient:123"
    assert result.raw_content == fake_plan_payload

    log_files = list(tmp_path.glob("*_plan.json"))
    assert log_files, "Expected a plan log file to be created"
    log_path = log_files[0]
    assert ":" not in log_path.name
    entry = json.loads(log_path.read_text(encoding="utf-8"))
    assert entry["doc_id"] == "patient:123"
