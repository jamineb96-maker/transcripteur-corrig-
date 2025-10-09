from types import ModuleType, SimpleNamespace

from types import ModuleType, SimpleNamespace

import pytest

# Inject lightweight stubs to avoid importing Flask or requests when loading the RAG modules.
fake_library = ModuleType("server.library")
fake_embeddings_backend = ModuleType("server.library.embeddings_backend")
fake_vector_db = ModuleType("server.library.vector_db")
fake_requests = ModuleType("requests")


def _requests_not_configured(*_args, **_kwargs):
    raise RuntimeError("requests module is stubbed in tests")


class _PlaceholderBackend:
    def embed_texts(self, texts):
        return [[0.0] for _ in texts]


class _PlaceholderVectorDB:
    def search(self, *args, **kwargs):
        return []


fake_embeddings_backend.EmbeddingsBackend = _PlaceholderBackend
fake_vector_db.VectorDB = _PlaceholderVectorDB
fake_library.embeddings_backend = fake_embeddings_backend
fake_library.vector_db = fake_vector_db
fake_requests.get = _requests_not_configured

import sys

sys.modules.setdefault("server.library", fake_library)
sys.modules.setdefault("server.library.embeddings_backend", fake_embeddings_backend)
sys.modules.setdefault("server.library.vector_db", fake_vector_db)
sys.modules.setdefault("requests", fake_requests)

from server.post_v2 import rag_local, rag_web
from server.post_v2.schemas import SessionFacts


@pytest.fixture(autouse=True)
def reset_singletons():
    rag_local._VECTOR_DB = None
    rag_local._EMBED_BACKEND = None
    rag_web._ALLOWLIST_CACHE = None
    yield
    rag_local._VECTOR_DB = None
    rag_local._EMBED_BACKEND = None
    rag_web._ALLOWLIST_CACHE = None


def _session_facts(**overrides):
    base = SessionFacts(
        patient="alice",
        date="2024-02-01",
        themes=["travail"],
        meds=[],
        context={},
        asks=[],
        quotes=[],
        flags={"risques": [], "incertitudes": []},
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_rag_local_returns_enriched_items(monkeypatch):
    monkeypatch.setenv("RESEARCH_V2", "true")

    class DummyVectorDB:
        def search(self, vector, k, filters=None):
            meta = SimpleNamespace(
                title="Guide des pratiques",
                doc_id="doc-1",
                page_start=2,
                page_end=3,
                evidence_level="modéré",
                year=2022,
                domains=["psy"],
                chunk_id="chunk-1",
            )
            return [SimpleNamespace(meta=meta, text="Texte informatif.", similarity=0.82)]

    class DummyBackend:
        def embed_texts(self, texts):
            return [[0.1, 0.9] for _ in texts]

    monkeypatch.setattr(rag_local, "_vector_db", lambda: DummyVectorDB())
    monkeypatch.setattr(rag_local, "_embeddings_backend", lambda: DummyBackend())

    facts = _session_facts(themes=["travail"], asks=["Comment soutenir une reprise ?"])
    results = rag_local.search_local_evidence(facts)
    assert results, "La recherche locale doit renvoyer au moins un extrait."
    first = results[0]
    assert first.pages
    assert first.evidence_level
    assert first.extract


def test_rag_web_respects_allowlist(monkeypatch):
    monkeypatch.setenv("RAG_WEB_PROVIDER", "dummy")

    def fake_allowlist():
        return ["allowed.org"]

    def fake_fetch(provider, query, max_results):
        return [
            rag_web._WebResult(
                title="Article validé",
                url="https://news.allowed.org/item",
                snippet="Étude récente sur les aménagements au travail.",
                source="Allowed News",
                author="Equipe",
                date="2023-02-01",
            ),
            rag_web._WebResult(
                title="Blog non fiable",
                url="https://random.example.com/post",
                snippet="Contenu anecdotique",
                source="Random",
                author=None,
                date=None,
            ),
        ]

    monkeypatch.setattr(rag_web, "_load_allowlist", fake_allowlist)
    monkeypatch.setattr(rag_web, "_fetch", fake_fetch)

    facts = _session_facts(themes=["travail"], asks=["Comment soutenir une reprise ?"])
    items = rag_web.search_web_evidence(facts, max_results=4)
    assert items, "La recherche web doit retourner au moins une source autorisée."
    assert all(item.url.startswith("https://news.allowed.org") for item in items)
    assert all(item.quote and len(item.quote) <= 280 for item in items)
    assert all(item.reliability_tag in {"fort", "moyen", "faible"} for item in items)
