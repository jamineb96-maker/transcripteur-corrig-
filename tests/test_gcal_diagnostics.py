import json
import os
import importlib
import re
import sys
import types
from pathlib import Path

from flask import Flask
import pytest


def _install_optional_stubs() -> None:
    """Install light stubs for optional dependencies required during import."""

    root = Path(__file__).resolve().parents[1]

    if "server" not in sys.modules:
        server_pkg = types.ModuleType("server")
        server_pkg.__path__ = [str(root / "server")]
        sys.modules["server"] = server_pkg

    if "server.services" not in sys.modules:
        services_pkg = types.ModuleType("server.services")
        services_pkg.__path__ = [str(root / "server" / "services")]
        sys.modules["server.services"] = services_pkg
    sys.modules["server"].services = sys.modules["server.services"]  # type: ignore[attr-defined]

    if "server.blueprints" not in sys.modules:
        blueprints_pkg = types.ModuleType("server.blueprints")
        blueprints_pkg.__path__ = [str(root / "server" / "blueprints")]
        sys.modules["server.blueprints"] = blueprints_pkg
    sys.modules["server"].blueprints = sys.modules["server.blueprints"]  # type: ignore[attr-defined]

    if "server.blueprints.library" not in sys.modules:
        library_pkg = types.ModuleType("server.blueprints.library")
        library_pkg.__path__ = [str(root / "server" / "blueprints" / "library")]
        sys.modules["server.blueprints.library"] = library_pkg

    if "modules" not in sys.modules:
        modules_pkg = types.ModuleType("modules")
        modules_pkg.__path__ = [str(root / "modules")]
        sys.modules["modules"] = modules_pkg

    try:  # pragma: no cover - optional dependency
        importlib.import_module("docx")
    except ModuleNotFoundError:  # pragma: no cover - triggered only when package missing
        module = types.ModuleType("docx")

        class _Doc:
            def add_paragraph(self, *_args, **_kwargs):  # pragma: no cover - import stub only
                return types.SimpleNamespace(add_run=lambda *_a, **_k: None)

            def save(self, *_args, **_kwargs):  # pragma: no cover - import stub only
                return None

        module.Document = lambda *_a, **_k: _Doc()  # type: ignore[assignment]
        enum_module = types.ModuleType("docx.enum")
        text_module = types.ModuleType("docx.enum.text")
        text_module.WD_PARAGRAPH_ALIGNMENT = types.SimpleNamespace(CENTER=1)  # type: ignore[attr-defined]
        sys.modules["docx"] = module
        sys.modules["docx.enum"] = enum_module
        sys.modules["docx.enum.text"] = text_module

    try:  # pragma: no cover - optional dependency
        importlib.import_module("cairosvg")
    except ModuleNotFoundError:  # pragma: no cover - triggered only when package missing
        module = types.ModuleType("cairosvg")
        module.svg2pdf = lambda *_a, **_k: b""  # type: ignore[attr-defined]
        sys.modules["cairosvg"] = module

    try:  # pragma: no cover - optional dependency
        importlib.import_module("reportlab")
    except ModuleNotFoundError:  # pragma: no cover - triggered only when package missing
        root = types.ModuleType("reportlab")
        lib = types.ModuleType("reportlab.lib")
        pagesizes = types.ModuleType("reportlab.lib.pagesizes")
        pagesizes.A4 = (595, 842)  # type: ignore[attr-defined]

        pdfbase = types.ModuleType("reportlab.pdfbase")
        pdfmetrics_module = types.ModuleType("reportlab.pdfbase.pdfmetrics")
        pdfmetrics_module.registerFont = lambda *_a, **_k: None  # type: ignore[attr-defined]
        pdfmetrics_module.getRegisteredFontNames = lambda: ["Helvetica"]  # type: ignore[attr-defined]

        ttfonts_module = types.ModuleType("reportlab.pdfbase.ttfonts")

        class _TTFont:  # pragma: no cover - import stub only
            def __init__(self, *_a, **_k) -> None:
                pass

        ttfonts_module.TTFont = _TTFont  # type: ignore[attr-defined]

        pdfgen_module = types.ModuleType("reportlab.pdfgen")
        canvas_module = types.ModuleType("reportlab.pdfgen.canvas")

        class _Canvas:  # pragma: no cover - import stub only
            def __init__(self, *_a, **_k) -> None:
                pass

            def setFont(self, *_a, **_k) -> None:
                return None

            def drawString(self, *_a, **_k) -> None:
                return None

            def showPage(self) -> None:
                return None

            def save(self) -> None:
                return None

        canvas_module.Canvas = _Canvas  # type: ignore[attr-defined]

        pdfgen_module.canvas = canvas_module  # type: ignore[attr-defined]
        pdfbase.pdfmetrics = pdfmetrics_module  # type: ignore[attr-defined]
        pdfbase.ttfonts = ttfonts_module  # type: ignore[attr-defined]

        root.lib = lib  # type: ignore[attr-defined]
        root.pdfbase = pdfbase  # type: ignore[attr-defined]
        root.pdfgen = pdfgen_module  # type: ignore[attr-defined]

        sys.modules["reportlab"] = root
        sys.modules["reportlab.lib"] = lib
        sys.modules["reportlab.lib.pagesizes"] = pagesizes
        sys.modules["reportlab.pdfbase"] = pdfbase
        sys.modules["reportlab.pdfbase.pdfmetrics"] = pdfmetrics_module
        sys.modules["reportlab.pdfbase.ttfonts"] = ttfonts_module
        sys.modules["reportlab.pdfgen"] = pdfgen_module
        sys.modules["reportlab.pdfgen.canvas"] = canvas_module

    try:  # pragma: no cover - optional dependency
        importlib.import_module("yaml")
    except ModuleNotFoundError:  # pragma: no cover - triggered only when package missing
        module = types.ModuleType("yaml")
        module.safe_load = lambda *_a, **_k: {}  # type: ignore[attr-defined]
        module.safe_dump = lambda *_a, **_k: ""  # type: ignore[attr-defined]
        sys.modules["yaml"] = module

    try:  # pragma: no cover - optional dependency
        importlib.import_module("pdfminer")
    except ModuleNotFoundError:  # pragma: no cover - triggered only when package missing
        root_pdfminer = types.ModuleType("pdfminer")
        pdfpage = types.ModuleType("pdfminer.pdfpage")
        pdfpage.PDFPage = type("PDFPage", (), {"get_pages": staticmethod(lambda *_a, **_k: [])})  # type: ignore[attr-defined]
        pdfparser = types.ModuleType("pdfminer.pdfparser")
        class _PDFSyntaxError(Exception):
            pass
        class _PDFParser:  # pragma: no cover - import stub only
            def __init__(self, *_a, **_k) -> None:
                pass
        pdfparser.PDFSyntaxError = _PDFSyntaxError  # type: ignore[attr-defined]
        pdfparser.PDFParser = _PDFParser  # type: ignore[attr-defined]
        pdfdocument = types.ModuleType("pdfminer.pdfdocument")
        class _PDFDocument:  # pragma: no cover - import stub only
            def __init__(self, *_a, **_k) -> None:
                self.info = []
        pdfdocument.PDFDocument = _PDFDocument  # type: ignore[attr-defined]
        high_level = types.ModuleType("pdfminer.high_level")
        high_level.extract_pages = lambda *_a, **_k: []  # type: ignore[attr-defined]
        high_level.extract_text = lambda *_a, **_k: ""  # type: ignore[attr-defined]
        layout_module = types.ModuleType("pdfminer.layout")
        class _LTTextContainer:  # pragma: no cover - import stub only
            def get_text(self):
                return ""
        layout_module.LTTextContainer = _LTTextContainer  # type: ignore[attr-defined]
        sys.modules["pdfminer"] = root_pdfminer
        sys.modules["pdfminer.pdfpage"] = pdfpage
        sys.modules["pdfminer.pdfparser"] = pdfparser
        sys.modules["pdfminer.pdfdocument"] = pdfdocument
        sys.modules["pdfminer.high_level"] = high_level
        sys.modules["pdfminer.layout"] = layout_module

    try:  # pragma: no cover - optional dependency
        importlib.import_module("regex")
    except ModuleNotFoundError:  # pragma: no cover - triggered only when package missing
        sys.modules["regex"] = re

    try:  # pragma: no cover - optional dependency
        importlib.import_module("langdetect")
    except ModuleNotFoundError:  # pragma: no cover - triggered only when package missing
        langdetect_module = types.ModuleType("langdetect")

        class _DetectorFactory:  # pragma: no cover - import stub only
            seed = 0

        langdetect_module.DetectorFactory = _DetectorFactory  # type: ignore[attr-defined]
        langdetect_module.detect_langs = lambda *_a, **_k: []  # type: ignore[attr-defined]
        langdetect_exc = types.ModuleType("langdetect.lang_detect_exception")

        class _LangDetectException(Exception):
            pass

        langdetect_exc.LangDetectException = _LangDetectException  # type: ignore[attr-defined]
        sys.modules["langdetect"] = langdetect_module
        sys.modules["langdetect.lang_detect_exception"] = langdetect_exc

    try:  # pragma: no cover - optional dependency
        importlib.import_module("sklearn")
    except ModuleNotFoundError:  # pragma: no cover - triggered only when package missing
        sklearn_module = types.ModuleType("sklearn")
        feature_extraction = types.ModuleType("sklearn.feature_extraction")
        text_module = types.ModuleType("sklearn.feature_extraction.text")

        class _TfidfVectorizer:  # pragma: no cover - import stub only
            def __init__(self, *_a, **_k) -> None:
                pass

            def fit(self, *_a, **_k):
                return self

            def transform(self, *_a, **_k):
                return []

        text_module.TfidfVectorizer = _TfidfVectorizer  # type: ignore[attr-defined]
        feature_extraction.text = text_module  # type: ignore[attr-defined]
        sklearn_module.feature_extraction = feature_extraction  # type: ignore[attr-defined]
        sys.modules["sklearn"] = sklearn_module
        sys.modules["sklearn.feature_extraction"] = feature_extraction
        sys.modules["sklearn.feature_extraction.text"] = text_module


_install_optional_stubs()

from oauthlib.oauth2.rfc6749.errors import InvalidClientError

from server.services.gcal_service import GCalService
from server.tabs.agenda import api_bp as agenda_api_bp, public_bp as agenda_public_bp


@pytest.fixture()
def gcal_app(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_JSON", raising=False)
    instance_path = tmp_path / "instance"
    instance_path.mkdir(parents=True, exist_ok=True)
    app = Flask("test-agenda", instance_path=str(instance_path))
    app.config.update(
        TESTING=True,
        SERVER_NAME="127.0.0.1:1421",
        PREFERRED_URL_SCHEME="http",
    )
    app.register_blueprint(agenda_public_bp)
    app.register_blueprint(agenda_api_bp)
    return app


def _extract_status(response):
    payload = response.get_json()
    if isinstance(payload, dict) and payload.get("success") is True:
        return payload.get("data", {})
    return payload or {}


def test_gcal_status_missing_secret(monkeypatch: pytest.MonkeyPatch, gcal_app):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    client = gcal_app.test_client()
    status = _extract_status(client.get("/api/agenda/status"))
    assert status["oauth_config_ok"] is False
    assert status["reason"] == "missing_client_secret"
    assert status["env_vars_present"]["GOOGLE_CLIENT_SECRET"] is False


def test_gcal_status_redirect_mismatch(monkeypatch: pytest.MonkeyPatch, gcal_app):
    config = {
        "web": {
            "client_id": "client",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["https://example.com/callback"],
        }
    }
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_JSON", json.dumps(config))
    client = gcal_app.test_client()
    status = _extract_status(client.get("/api/agenda/status"))
    assert status["configured"] is True
    assert status["oauth_config_ok"] is False
    assert status["reason"] == "redirect_uri_not_registered"
    assert status["redirect_uri_ok"] is False


def test_gcal_nominal_flow_sets_connected(monkeypatch: pytest.MonkeyPatch, gcal_app):
    config = {
        "web": {
            "client_id": "client",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://127.0.0.1:1421/agenda/gcal/oauth2callback"],
        }
    }
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_JSON", json.dumps(config))

    stored: dict[str, object] = {}

    class _FakeCredentials:
        valid = True
        expired = False
        refresh_token = None

        def to_json(self) -> str:
            return json.dumps({"token": "fake"})

    class _FakeFlow:
        def __init__(self, *_args, **_kwargs):
            self.redirect_uri = None
            self.credentials = _FakeCredentials()

        def authorization_url(self, **_kwargs):
            return "https://example.com/auth", _kwargs.get("state", "state")

        def fetch_token(self, **_kwargs):
            return None

    def _fake_store(self: GCalService, _credentials):
        stored["creds"] = types.SimpleNamespace(valid=True)

    def _fake_load(self: GCalService):
        return stored.get("creds")

    def _fake_delete(self: GCalService):
        stored.pop("creds", None)

    monkeypatch.setattr("server.services.gcal_service.Flow.from_client_config", lambda *_args, **_kwargs: _FakeFlow())
    monkeypatch.setattr(GCalService, "_store_credentials", _fake_store, raising=False)
    monkeypatch.setattr(GCalService, "_load_credentials", _fake_load, raising=False)
    monkeypatch.setattr(GCalService, "_delete_credentials", _fake_delete, raising=False)

    with gcal_app.app_context():
        service = GCalService(gcal_app)
        service.get_auth_url("state-token")
        service.handle_oauth2_callback({"code": "auth-code"})

    status = _extract_status(gcal_app.test_client().get("/api/agenda/status"))
    assert status["connected"] is True
    assert status["oauth_config_ok"] is True
    assert status["client_type"] == "web"


def test_gcal_invalid_client_fallback(monkeypatch: pytest.MonkeyPatch, gcal_app, tmp_path):
    primary_path = tmp_path / "primary.json"
    fallback_path = tmp_path / "fallback.json"
    primary_config = {
        "web": {
            "client_id": "client",
            "client_secret": "bad-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://127.0.0.1:1421/agenda/gcal/oauth2callback"],
        }
    }
    fallback_config = {
        "web": {
            "client_id": "client",
            "client_secret": "good-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://127.0.0.1:1421/agenda/gcal/oauth2callback"],
        }
    }
    primary_path.write_text(json.dumps(primary_config))
    fallback_path.write_text(json.dumps(fallback_config))
    monkeypatch.setenv(
        "GOOGLE_CLIENT_SECRET_FILE",
        os.pathsep.join([str(primary_path), str(fallback_path)]),
    )

    stored: dict[str, object] = {}

    class _FakeCredentials:
        valid = True
        expired = False
        refresh_token = None

        def to_json(self) -> str:
            return json.dumps({"token": "fake"})

    class _FakeFlow:
        def __init__(self, client_config, *_args, **_kwargs):
            self.client_config = client_config
            self.redirect_uri = None
            self.credentials = _FakeCredentials()

        def authorization_url(self, **_kwargs):  # pragma: no cover - simple stub
            return "https://example.com/auth", _kwargs.get("state", "state")

        def fetch_token(self, **_kwargs):
            secret = self.client_config["web"]["client_secret"]
            if secret == "bad-secret":
                raise InvalidClientError()
            stored["used_secret"] = secret

    def _fake_from_client_config(config, **_kwargs):
        return _FakeFlow(config)

    def _fake_store(self: GCalService, _credentials):
        stored["creds"] = types.SimpleNamespace(valid=True)
        resolved = self._last_resolved
        stored["source"] = resolved.source if resolved else None

    def _fake_load(self: GCalService):
        return stored.get("creds")

    def _fake_delete(self: GCalService):
        stored.pop("creds", None)

    monkeypatch.setattr("server.services.gcal_service.Flow.from_client_config", _fake_from_client_config)
    monkeypatch.setattr(GCalService, "_store_credentials", _fake_store, raising=False)
    monkeypatch.setattr(GCalService, "_load_credentials", _fake_load, raising=False)
    monkeypatch.setattr(GCalService, "_delete_credentials", _fake_delete, raising=False)

    with gcal_app.app_context():
        service = GCalService(gcal_app)
        service.get_auth_url("state-token")
        service.handle_oauth2_callback({"code": "auth-code"})

    status = _extract_status(gcal_app.test_client().get("/api/agenda/status"))
    assert status["connected"] is True
    assert stored["used_secret"] == "good-secret"
    assert stored["source"].endswith(fallback_path.name)


def test_gcal_installed_type_reports_mismatch(monkeypatch: pytest.MonkeyPatch, gcal_app):
    config = {
        "installed": {
            "client_id": "client",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [
                "http://localhost",
                "http://127.0.0.1:1421/agenda/gcal/oauth2callback",
            ],
        }
    }
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_JSON", json.dumps(config))
    client = gcal_app.test_client()
    status = _extract_status(client.get("/api/agenda/status"))
    assert status["oauth_config_ok"] is False
    assert status["reason"] == "client_type_installed_not_supported_for_this_redirect"
    assert status["client_type"] == "installed"
