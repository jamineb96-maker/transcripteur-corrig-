from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Dict

import pytest
from flask import Flask

fake_llm = types.ModuleType("modules.library_llm")


class _FakeLibraryLLMError(RuntimeError):
    pass


def _fake_embed_texts(texts: list[str]):
    return [[0.0] * 3 for _ in texts]


fake_llm.LibraryLLMError = _FakeLibraryLLMError
fake_llm.embed_texts = _fake_embed_texts
sys.modules.setdefault("modules.library_llm", fake_llm)

google_pkg = types.ModuleType("google")
google_auth_pkg = types.ModuleType("google.auth")
google_auth_exceptions_pkg = types.ModuleType("google.auth.exceptions")


class _FakeRefreshError(Exception):
    pass


google_auth_exceptions_pkg.RefreshError = _FakeRefreshError
google_auth_pkg.exceptions = google_auth_exceptions_pkg
google_auth_transport_pkg = types.ModuleType("google.auth.transport")
google_auth_transport_requests_pkg = types.ModuleType("google.auth.transport.requests")


class _FakeGoogleRequest:  # pragma: no cover - simple stub
    pass


google_auth_transport_requests_pkg.Request = _FakeGoogleRequest
google_auth_transport_pkg.requests = google_auth_transport_requests_pkg
google_auth_pkg.transport = google_auth_transport_pkg
google_oauth2_pkg = types.ModuleType("google.oauth2")
google_oauth2_credentials_pkg = types.ModuleType("google.oauth2.credentials")


class _FakeGoogleCredentials:  # pragma: no cover - simple stub
    def __init__(self, *args, **kwargs):
        pass


google_oauth2_credentials_pkg.Credentials = _FakeGoogleCredentials
google_oauth2_pkg.credentials = google_oauth2_credentials_pkg
google_pkg.auth = google_auth_pkg
google_pkg.oauth2 = google_oauth2_pkg
google_auth_oauthlib_pkg = types.ModuleType("google_auth_oauthlib")
google_auth_oauthlib_flow_pkg = types.ModuleType("google_auth_oauthlib.flow")


class _FakeOAuthFlow:  # pragma: no cover - simple stub
    def __init__(self, *args, **kwargs):
        pass

    def authorization_url(self, *args, **kwargs):
        return "https://example.com", None

    def fetch_token(self, *args, **kwargs):  # noqa: D401 - stub
        return {}


google_auth_oauthlib_flow_pkg.Flow = _FakeOAuthFlow
google_auth_oauthlib_pkg.flow = google_auth_oauthlib_flow_pkg
oauthlib_pkg = types.ModuleType("oauthlib")
oauthlib_oauth2_pkg = types.ModuleType("oauthlib.oauth2")
oauthlib_rfc_pkg = types.ModuleType("oauthlib.oauth2.rfc6749")
oauthlib_rfc_errors_pkg = types.ModuleType("oauthlib.oauth2.rfc6749.errors")


class _FakeInvalidClientError(Exception):
    pass


oauthlib_rfc_errors_pkg.InvalidClientError = _FakeInvalidClientError
oauthlib_rfc_pkg.errors = oauthlib_rfc_errors_pkg
oauthlib_oauth2_pkg.rfc6749 = oauthlib_rfc_pkg
oauthlib_pkg.oauth2 = oauthlib_oauth2_pkg
docx_module = types.ModuleType("docx")
docx_enum_module = types.ModuleType("docx.enum")
docx_enum_text_module = types.ModuleType("docx.enum.text")
docx_shared_module = types.ModuleType("docx.shared")
cairosvg_module = types.ModuleType("cairosvg")
reportlab_module = types.ModuleType("reportlab")
reportlab_lib_module = types.ModuleType("reportlab.lib")
reportlab_lib_pagesizes_module = types.ModuleType("reportlab.lib.pagesizes")
reportlab_pdfbase_module = types.ModuleType("reportlab.pdfbase")
reportlab_pdfbase_pdfmetrics_module = types.ModuleType("reportlab.pdfbase.pdfmetrics")
reportlab_pdfbase_ttfonts_module = types.ModuleType("reportlab.pdfbase.ttfonts")
reportlab_pdfgen_module = types.ModuleType("reportlab.pdfgen")
reportlab_pdfgen_canvas_module = types.ModuleType("reportlab.pdfgen.canvas")
yaml_module = types.ModuleType("yaml")


class _FakeDocxDocument:  # pragma: no cover - simple stub
    def __init__(self, *args, **kwargs):
        pass


docx_module.Document = _FakeDocxDocument
docx_enum_text_module.WD_PARAGRAPH_ALIGNMENT = types.SimpleNamespace(LEFT=0, RIGHT=1, CENTER=2, JUSTIFY=3)
docx_enum_module.text = docx_enum_text_module
docx_module.enum = docx_enum_module
docx_shared_module.Pt = lambda value: value
docx_module.shared = docx_shared_module
cairosvg_module.svg2pdf = lambda *args, **kwargs: b""
reportlab_lib_pagesizes_module.A4 = (595.27, 841.89)
reportlab_lib_module.pagesizes = reportlab_lib_pagesizes_module
reportlab_pdfbase_pdfmetrics_module.registerFont = lambda *args, **kwargs: None
reportlab_pdfbase_pdfmetrics_module.getFont = lambda *_args, **_kwargs: None
reportlab_pdfbase_module.pdfmetrics = reportlab_pdfbase_pdfmetrics_module
reportlab_module.lib = types.SimpleNamespace(pagesizes=reportlab_lib_pagesizes_module)
reportlab_module.pdfbase = types.SimpleNamespace(pdfmetrics=reportlab_pdfbase_pdfmetrics_module, ttfonts=reportlab_pdfbase_ttfonts_module)
reportlab_pdfbase_module.ttfonts = reportlab_pdfbase_ttfonts_module
reportlab_pdfbase_ttfonts_module.TTFont = lambda *args, **kwargs: None
reportlab_pdfgen_canvas_module.Canvas = type("_FakeCanvas", (), {"__init__": lambda self, *args, **kwargs: None, "save": lambda self: None})
reportlab_pdfgen_module.canvas = reportlab_pdfgen_canvas_module
reportlab_module.pdfgen = types.SimpleNamespace(canvas=reportlab_pdfgen_canvas_module)
yaml_module.safe_load = lambda _data: {}
yaml_module.dump = lambda _data, *args, **kwargs: ""
sys.modules.setdefault("google", google_pkg)
sys.modules.setdefault("google.auth", google_auth_pkg)
sys.modules.setdefault("google.auth.exceptions", google_auth_exceptions_pkg)
sys.modules.setdefault("google.auth.transport", google_auth_transport_pkg)
sys.modules.setdefault("google.auth.transport.requests", google_auth_transport_requests_pkg)
sys.modules.setdefault("google.oauth2", google_oauth2_pkg)
sys.modules.setdefault("google.oauth2.credentials", google_oauth2_credentials_pkg)
sys.modules.setdefault("google_auth_oauthlib", google_auth_oauthlib_pkg)
sys.modules.setdefault("google_auth_oauthlib.flow", google_auth_oauthlib_flow_pkg)
sys.modules.setdefault("oauthlib", oauthlib_pkg)
sys.modules.setdefault("oauthlib.oauth2", oauthlib_oauth2_pkg)
sys.modules.setdefault("oauthlib.oauth2.rfc6749", oauthlib_rfc_pkg)
sys.modules.setdefault("oauthlib.oauth2.rfc6749.errors", oauthlib_rfc_errors_pkg)
sys.modules.setdefault("docx", docx_module)
sys.modules.setdefault("docx.enum", docx_enum_module)
sys.modules.setdefault("docx.enum.text", docx_enum_text_module)
sys.modules.setdefault("docx.shared", docx_shared_module)
sys.modules.setdefault("cairosvg", cairosvg_module)
sys.modules.setdefault("reportlab", reportlab_module)
sys.modules.setdefault("reportlab.lib", reportlab_lib_module)
sys.modules.setdefault("reportlab.lib.pagesizes", reportlab_lib_pagesizes_module)
sys.modules.setdefault("reportlab.pdfbase", reportlab_pdfbase_module)
sys.modules.setdefault("reportlab.pdfbase.pdfmetrics", reportlab_pdfbase_pdfmetrics_module)
sys.modules.setdefault("reportlab.pdfbase.ttfonts", reportlab_pdfbase_ttfonts_module)
sys.modules.setdefault("reportlab.pdfgen", reportlab_pdfgen_module)
sys.modules.setdefault("reportlab.pdfgen.canvas", reportlab_pdfgen_canvas_module)
sys.modules.setdefault("yaml", yaml_module)

from modules import library_index


def _load_service_module(name: str):
    root = Path(__file__).resolve().parents[2]
    target = root / "server" / "services" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"server.services.{name}", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_module(name: str, path: Path):
    parts = name.split(".")
    for index in range(1, len(parts)):
        package_name = ".".join(parts[:index])
        if package_name not in sys.modules:
            package = types.ModuleType(package_name)
            package.__path__ = []  # type: ignore[attr-defined]
            sys.modules[package_name] = package
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


library_search = _load_service_module("library_search")
LocalSearchEngine = library_search.LocalSearchEngine


def _prepare_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Path]:
    layout = library_index.ensure_index_layout(tmp_path)

    def _patched_layout(root: Path | str = library_index.INDEX_ROOT) -> Dict[str, Path]:
        return layout

    monkeypatch.setattr(library_index, "ensure_index_layout", _patched_layout)
    return layout


@pytest.fixture()
def indexed_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    layout = _prepare_layout(tmp_path / "index", monkeypatch)
    library_index.index_segments(
        "doc-alpha",
        [
            {
                "segment_id": "doc-alpha::1",
                "pages": [1, 1],
                "text": "L'alliance therapeutique nécessite une attention soutenue.",
                "title": "Alliance thérapeutique",
                "year": 2021,
                "type": "Guide",
                "level": "Élevé",
                "domain": ["alliance thérapeutique"],
            },
        ],
    )
    library_index.index_segments(
        "doc-beta",
        [
            {
                "segment_id": "doc-beta::1",
                "pages": [3, 3],
                "text": "Développer l'assertivité aide à poser des limites relationnelles.",
                "title": "Assertivité et limites",
                "year": 2020,
                "type": "Article",
                "level": "Modéré",
                "domain": ["assertivité"],
            },
        ],
    )
    return LocalSearchEngine(db_path=layout["db"])


def test_search_returns_snippets_ordered_by_score(indexed_engine):
    results = indexed_engine.search(["assertivite limites"], top_k=2)
    assert results
    assert results[0]["doc_id"] == "doc-beta"
    assert "<mark>" in results[0]["snippet"]
    if len(results) > 1:
        assert results[0]["score"] >= results[1]["score"]


def test_indexed_segments_are_visible_via_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    layout = _prepare_layout(tmp_path / "api-index", monkeypatch)
    library_index.index_segments(
        "doc-gamma",
        [
            {
                "segment_id": "doc-gamma::1",
                "pages": [2, 4],
                "text": "L'intervention systémique structure des limites claires pour les patients.",
                "title": "Interventions systémiques",
                "year": 2022,
                "type": "Note clinique",
                "level": "Modéré",
                "domain": ["systémique"],
            }
        ],
    )

    engine = LocalSearchEngine(db_path=layout["db"])

    module_path = Path(__file__).resolve().parents[2] / "server" / "blueprints" / "library" / "search_api.py"
    search_api = _load_module("server.blueprints.library.search_api", module_path)
    search_api._ENGINE = engine
    monkeypatch.setattr(search_api, "_get_engine", lambda: engine)

    app = Flask("library_search_test")
    app.config["TESTING"] = True
    app.config["RESEARCH_WEB_ENABLED"] = False
    app.register_blueprint(search_api.bp)

    with app.test_client() as client:
        response = client.post(
            "/library/search",
            json={"queries": ["limites"], "scope": "local", "top_k": 5},
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["ok"] is True
        doc_ids = {item["doc_id"] for item in payload.get("results", [])}
        assert "doc-gamma" in doc_ids
