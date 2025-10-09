import os

import pytest

from modules import research_engine


@pytest.fixture(autouse=True)
def clear_flag(monkeypatch):
    monkeypatch.delenv("PRESESSION_RESEARCH_V2", raising=False)


def test_run_research_default_structure(monkeypatch):
    plan = {"orientation": "", "objectif_prioritaire": ""}
    result = research_engine.run_research(plan=plan, raw_context={}, allow_internet=False)
    assert set(result.keys()) >= {"local_library", "internet", "notes_integration"}
    assert "research_v2" not in result


def test_run_research_v2_activation(monkeypatch):
    payload = {"facets": [{"name": "demo", "status": "ok", "citations": []}], "audit": {}}

    def fake_run(*args, **kwargs):
        return payload

    monkeypatch.setattr(research_engine, "run_research_v2", fake_run)
    result = research_engine.run_research(plan={}, raw_context={}, allow_internet=False, options={"use_v2": True})
    assert result["research_v2"] == payload
    assert result["internet"] == []
