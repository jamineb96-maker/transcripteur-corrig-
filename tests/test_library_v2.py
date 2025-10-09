"""Offline integration tests for the clinical library v2 stack."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import importlib.util
import pytest

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")

    class _Blueprint:  # pragma: no cover - minimal stub for import
        def __init__(self, *_args, **_kwargs):
            pass

        def get(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

        def post(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

        def route(self, *_args, **_kwargs):  # pragma: no cover - unused
            def decorator(func):
                return func

            return decorator

    flask_stub.Blueprint = _Blueprint
    flask_stub.current_app = types.SimpleNamespace(config={}, instance_path="")
    flask_stub.request = types.SimpleNamespace(args={}, _json=None)
    flask_stub.request.get_json = lambda silent=False: flask_stub.request._json
    flask_stub.jsonify = lambda payload=None, **_kwargs: payload
    sys.modules["flask"] = flask_stub

if "yaml" not in sys.modules:
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda _stream=None: {}
    yaml_stub.safe_dump = lambda data, *_args, **_kwargs: ""
    sys.modules["yaml"] = yaml_stub

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - robustness
        raise RuntimeError(f"unable to load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


from modules import research_engine
library_api = _load_module("tests.library_api", Path("server/blueprints/library_api.py"))
from server.library import journal, notions
from server.library.indexer import chunk_pdf, embed_chunks
from server.library.models import Notion, NotionSource
from server.library.vector_db import VectorDB
research_engine_v2 = _load_module("tests.research_engine_v2", Path("server/tabs/post_session/research_engine_v2.py"))


def _make_pdf(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _force_feature_flags(monkeypatch):
    monkeypatch.setenv("ALLOW_FAKE_EMBEDS", "true")
    monkeypatch.setenv("USE_FAISS", "false")
    monkeypatch.setenv("RESEARCH_V2", "true")


@pytest.fixture(autouse=True)
def _redirect_journal(tmp_path_factory, monkeypatch):
    journal_dir = tmp_path_factory.mktemp("journal")
    journal_path = journal_dir / "journal.log"
    monkeypatch.setattr(journal, "_store_path", lambda: str(journal_path))


@pytest.fixture
def notion_store(tmp_path, monkeypatch):
    path = tmp_path / "notions.jsonl"
    monkeypatch.setattr(notions, "_store_path", lambda: str(path))
    return path


def test_chunk_indexer_creates_entries(tmp_path, notion_store, monkeypatch):
    store_dir = tmp_path / "vector"
    monkeypatch.setenv("LIBRARY_VECTOR_STORE_DIR", str(store_dir))
    pdf_path = _make_pdf(
        tmp_path,
        "doc.pdf",
        "Trauma care improves outcomes. Plan personnalisé avec suivi clinique.",
    )
    meta = {
        "title": "Trauma care",
        "authors": "Doe, Jane",
        "year": 2022,
        "domains": ["Trauma"],
        "keywords": ["plan", "soin"],
        "evidence_level": "élevé",
    }
    chunks = chunk_pdf(str(pdf_path), doc_id="doc-test", base_meta=meta)
    assert chunks, "chunking should yield data"
    embed_chunks(chunks)
    db = VectorDB(store_dir=str(store_dir))
    inserted = db.upsert(chunks)
    assert inserted == len(chunks)
    assert db.stats("doc-test")["chunks_indexed"] == len(chunks)
    assert db.total_chunks() == len(chunks)


def test_save_and_list_notions(tmp_path, notion_store, monkeypatch):
    store_dir = tmp_path / "vector"
    monkeypatch.setenv("LIBRARY_VECTOR_STORE_DIR", str(store_dir))
    pdf_path = _make_pdf(
        tmp_path,
        "notion.pdf",
        "Approche validée en trois étapes. Les patient·es suivent un protocole gradué.",
    )
    meta = {
        "title": "Plan validé",
        "authors": "Durand, Alice",
        "year": 2023,
        "domains": ["Trauma"],
        "keywords": ["plan", "protocole"],
        "evidence_level": "modéré",
    }
    doc_id = "doc-notion"
    chunks = chunk_pdf(str(pdf_path), doc_id=doc_id, base_meta=meta)
    embed_chunks(chunks)
    db = VectorDB(store_dir=str(store_dir))
    db.upsert(chunks)
    source = NotionSource(
        doc_id=doc_id,
        chunk_ids=[chunks[0].meta.chunk_id],
        citation="p. 1",
    )
    notion = Notion(
        id="plan-trauma",
        label="Plan trauma",
        definition="Ce plan décrit trois étapes concrètes et mesurables pour la prise en charge clinique.",
        synonyms=["Plan personnalisé"],
        domains=["Trauma"],
        evidence_level="élevé",
        sources=[source],
    )
    saved = notions.save_notion(notion, vector_db=db)
    assert saved.id == "plan-trauma"
    listed = notions.list_notions_for_doc(doc_id)
    assert listed and listed[0]["id"] == "plan-trauma"
    search_results = notions.search_notions("plan", doc_id=doc_id)
    assert search_results and search_results[0].id == "plan-trauma"


def test_search_evidence_vector_engine(tmp_path, notion_store, monkeypatch):
    store_dir = tmp_path / "vector"
    monkeypatch.setenv("LIBRARY_VECTOR_STORE_DIR", str(store_dir))
    research_engine_v2._VECTOR_DB = None
    pdf_path = _make_pdf(
        tmp_path,
        "vector.pdf",
        "Le plan de trauma personnalisé améliore la prise en charge. Approche validée en clinique.",
    )
    meta = {
        "title": "Plan personnalisé",
        "authors": "Durand, Alice",
        "year": 2023,
        "domains": ["Trauma"],
        "keywords": ["plan", "clinique"],
        "evidence_level": "modéré",
    }
    doc_id = "doc-vector"
    chunks = chunk_pdf(str(pdf_path), doc_id=doc_id, base_meta=meta)
    embed_chunks(chunks)
    db = VectorDB(store_dir=str(store_dir))
    db.upsert(chunks)
    source = NotionSource(
        doc_id=doc_id,
        chunk_ids=[chunks[0].meta.chunk_id],
        citation="p. 1",
    )
    notion = Notion(
        id="plan-trauma-valide",
        label="Plan trauma validé",
        definition="Ce plan structuré détaille les trois phases évaluables d'un suivi post-traumatique moderne.",
        synonyms=[],
        domains=["Trauma"],
        evidence_level="élevé",
        sources=[source],
    )
    notions.save_notion(notion, vector_db=db)
    results = research_engine_v2.search_evidence("plan trauma personnalisé", k=3)
    assert results
    first = results[0]
    assert first["doc_id"] == doc_id
    assert first["extract"], "extract should not be empty"
    assert first["page_start"] == chunks[0].meta.page_start
    assert first["notions"], "notions should link back to canonical entries"
    assert "score" in first and first["score"] >= 0.0


def test_library_api_endpoints_flow(tmp_path, notion_store, monkeypatch):
    store_dir = tmp_path / "vector"
    monkeypatch.setenv("LIBRARY_VECTOR_STORE_DIR", str(store_dir))
    library_api._VECTOR_DB = None
    library_api.current_app.config = {"LIBRARY_VECTOR_STORE_DIR": str(store_dir), "RESEARCH_V2": True}
    library_api.current_app.instance_path = str(tmp_path)

    library_api.request.args = {}
    library_api.request._json = None
    health_payload = library_api.health_endpoint()
    assert health_payload["store_writable"] is True

    doc_id = "doc-int"
    pdf_path = _make_pdf(
        tmp_path,
        "integration.pdf",
        "Plan clinique détaillé. Étapes mesurables avec suivi annuel et recommandations validées.",
    )
    body = {
        "doc_id": doc_id,
        "doc_path": str(pdf_path),
        "meta": {
            "title": "Plan clinique",
            "authors": "Martin, Chloé",
            "year": 2021,
            "domains": ["Trauma"],
            "keywords": ["plan", "clinique"],
            "evidence_level": "modéré",
        },
    }
    library_api.request._json = body
    index_json = library_api.index_chunks_endpoint()
    assert index_json["inserted"] > 0

    debug_json = library_api.debug_doc_endpoint(doc_id)
    assert debug_json["chunks_indexed"] == index_json["total"]

    library_api.request.args = {"doc_id": doc_id}
    chunks_json = library_api.list_chunks_endpoint()
    assert chunks_json["chunks"], "chunks endpoint should return data"
    chunk_id = chunks_json["chunks"][0]["chunk_id"]

    notion_payload = {
        "id": "plan-integration",
        "label": "Plan d'intégration clinique",
        "definition": "Ce plan structuré détaille trois jalons vérifiables pour assurer la continuité clinique annuelle.",
        "synonyms": ["Plan clinique intégré"],
        "domains": ["Trauma"],
        "evidence_level": "élevé",
        "sources": [
            {"doc_id": doc_id, "chunk_ids": [chunk_id], "citation": "p. 1"},
        ],
    }
    library_api.request._json = notion_payload
    notion_json = library_api.save_notion_endpoint()
    assert notion_json["id"] == "plan-integration"

    library_api.request.args = {"doc_id": doc_id}
    notions_json = library_api.list_notions_endpoint()
    assert notions_json["count"] == 1

    library_api.request._json = {"query": "plan clinique", "filters": {"doc_id": doc_id}, "k": 4}
    search_debug_json = library_api.search_debug_endpoint()
    assert search_debug_json["hits"]
    assert search_debug_json["hits"][0]["chunk_id"] == chunk_id


def test_search_local_library_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_V2", "false")
    monkeypatch.setattr(research_engine, "LIBRARY_DIR", str(tmp_path))
    sample = tmp_path / "note.txt"
    sample.write_text("Approche résilience en soin post-traumatique.", encoding="utf-8")

    def _should_not_call(*_args, **_kwargs):
        raise AssertionError("search_evidence should not be invoked when RESEARCH_V2=false")

    stub_module = types.ModuleType("server.tabs.pre_session.research_engine_v2")
    stub_module.search_evidence = _should_not_call
    monkeypatch.setitem(sys.modules, "server.tabs.pre_session.research_engine_v2", stub_module)
    results = research_engine.search_local_library("résilience", k=1)
    assert results
    assert all("source" in item for item in results)
