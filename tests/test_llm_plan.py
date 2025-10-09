import importlib
import json
import re
import sys
import types
from pathlib import Path
from pathlib import Path

from flask import Flask
import pytest


def _install_optional_stubs() -> None:
    """Install small stubs for optional packages required at import time."""

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

from server.blueprints.library.plan_schema import SCHEMA_VERSION  # type: ignore  # noqa: E402
from server.blueprints.library import routes as library_routes  # type: ignore  # noqa: E402
from server.utils.docid import doc_id_to_fs_path  # type: ignore  # noqa: E402


@pytest.fixture()
def plan_app(tmp_path, monkeypatch: pytest.MonkeyPatch):
    library_root = tmp_path / "library"
    extracted_root = library_root / "extracted"
    logs_root = library_root / "logs"

    monkeypatch.setenv("LIBRARY_ROOT", str(library_root))
    monkeypatch.setenv("LIBRARY_FS_SHARDING", "1")
    monkeypatch.setenv("FEATURE_LIBRARY_FS_V2", "1")

    current_response = {
        "content": json.dumps({"doc_id": "placeholder", "schema_version": SCHEMA_VERSION, "proposed_notions": []}),
        "tool_calls": None,
        "finish_reason": "stop",
        "function_call": None,
    }

    class _FakeCompletions:
        def create(self, **_kwargs):
            message = types.SimpleNamespace(
                content=current_response["content"],
                tool_calls=current_response.get("tool_calls"),
                function_call=current_response.get("function_call"),
            )
            choice = types.SimpleNamespace(message=message, finish_reason=current_response.get("finish_reason"))
            return types.SimpleNamespace(choices=[choice])

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self):
            self.chat = _FakeChat()

    fake_client = _FakeClient()

    import modules.library_llm as library_llm  # type: ignore  # noqa: E402

    monkeypatch.setattr(library_llm, "get_openai_client", lambda: fake_client)
    monkeypatch.setattr(library_llm, "LOGS_DIR", logs_root)

    app = Flask("test-library")
    app.config.update(
        TESTING=True,
        LIBRARY_ROOT=str(library_root),
        LIBRARY_FS_SHARDING="1",
        FEATURE_LIBRARY_FS_V2=True,
        FEATURE_LIBRARY_AUTOFILL=True,
    )
    app.register_blueprint(library_routes.library_ingest_bp)

    def _set_response(content: str, *, tool_calls=None, finish_reason="stop", function_call=None):
        current_response["content"] = content
        current_response["tool_calls"] = tool_calls
        current_response["finish_reason"] = finish_reason
        current_response["function_call"] = function_call

    def _make_doc(doc_id: str, *, state: str = "done", segments: list[dict] | None = None) -> Path:
        segments = segments or [{"segment_id": "seg1", "text": "Texte", "pages": [1]}]
        doc_dir = doc_id_to_fs_path(extracted_root, doc_id, shard=True)
        doc_dir.mkdir(parents=True, exist_ok=True)
        segments_path = doc_dir / "segments.jsonl"
        segments_path.write_text(
            "\n".join(json.dumps(segment, ensure_ascii=False) for segment in segments) + "\n",
            encoding="utf-8",
        )
        manifest = {
            "doc_id": doc_id,
            "state": state,
            "history": [],
        }
        (doc_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return doc_dir

    def _valid_plan(doc_id: str) -> dict:
        return {
            "doc_id": doc_id,
            "schema_version": SCHEMA_VERSION,
            "resource_type": "Guide",
            "evidence_level": "Modéré",
            "proposed_notions": [
                {
                    "candidate_notion_id": "notion-1",
                    "title": "Notion",
                    "summary": "Résumé clinique.",
                    "clinical_uses": ["Usage"],
                    "key_quotes": [
                        {"text": "Citation", "pages": [1], "segment_ids": ["seg1"]}
                    ],
                    "limitations_risks": [],
                    "tags": [],
                    "evidence": {"type": "Guide", "strength": "Modéré"},
                    "source_spans": [],
                    "autosuggest_pre": True,
                    "autosuggest_post": False,
                    "priority": 0.8,
                }
            ],
        }

    return app, _set_response, _make_doc, extracted_root, _valid_plan


def _read_manifest(manifest_dir: Path) -> dict:
    path = manifest_dir / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_plan_degraded_on_plaintext(plan_app):
    app, set_response, make_doc, extracted_root, _valid_plan = plan_app
    doc_id = "sha256:" + "a" * 64
    doc_dir = make_doc(doc_id)
    set_response("Sortie non JSON")

    response = app.test_client().post(f"/library/llm/plan/{doc_id}", json={})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "degraded"
    assert payload["reason"] == "non_conforming_output"
    assert payload["ok"] is False
    assert payload["schema_version"] == SCHEMA_VERSION

    artifact_path = doc_dir / "llm_plan.json"
    assert artifact_path.exists()
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["quality"] == "degraded"
    history = _read_manifest(doc_dir)["history"]
    assert history[-1]["event"] == "llm_plan_degraded"


def test_plan_invalid_schema_returns_diagnostics(plan_app):
    app, set_response, make_doc, extracted_root, _valid_plan = plan_app
    doc_id = "sha256:" + "b" * 64
    doc_dir = make_doc(doc_id)
    invalid_payload = {
        "doc_id": doc_id,
        "schema_version": SCHEMA_VERSION,
        "proposed_notions": [
            {
                "title": "Sans identifiant",
                "summary": "Résumé manquant d'identifiant.",
                "clinical_uses": [],
                "key_quotes": [],
                "limitations_risks": [],
                "tags": [],
                "evidence": {"type": "Guide", "strength": "Modéré"},
                "source_spans": [],
                "autosuggest_pre": False,
                "autosuggest_post": False,
                "priority": 0.2,
            }
        ],
    }
    set_response(json.dumps(invalid_payload))

    response = app.test_client().post(f"/library/llm/plan/{doc_id}", json={})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["error"] == "invalid_plan_schema"
    assert payload["status"] == "degraded"
    assert payload["quality"] == "degraded"
    assert payload["ok"] is False
    assert "candidate_notion_id" in payload.get("validator_trace", "")
    assert payload.get("raw_excerpt_saved") is True

    artifact = json.loads((doc_dir / "llm_plan.json").read_text(encoding="utf-8"))
    assert artifact["reason"] == "invalid_plan_schema"
    history = _read_manifest(doc_dir)["history"]
    assert history[-1]["reason"] == "invalid_plan_schema"


def test_plan_409_on_state_not_ready(plan_app):
    app, set_response, make_doc, _, _valid_plan = plan_app
    doc_id = "sha256:" + "c" * 64
    make_doc(doc_id, state="running")

    response = app.test_client().post(f"/library/llm/plan/{doc_id}", json={})
    assert response.status_code == 409
    assert response.get_json()["error"] == "invalid_state"


def test_plan_404_on_missing_doc(plan_app):
    app, _set_response, _make_doc, _, _valid_plan = plan_app
    doc_id = "sha256:" + "d" * 64
    response = app.test_client().post(f"/library/llm/plan/{doc_id}", json={})
    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


def test_plan_ok_on_valid_json(plan_app):
    app, set_response, make_doc, _, valid_plan = plan_app
    doc_id = "sha256:" + "e" * 64
    doc_dir = make_doc(doc_id)
    set_response(json.dumps(valid_plan(doc_id)))

    response = app.test_client().post(f"/library/llm/plan/{doc_id}", json={})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["quality"] == "full"
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["plan"]["proposed_notions"]

    artifact = json.loads((doc_dir / "llm_plan.json").read_text(encoding="utf-8"))
    assert artifact["quality"] == "full"
    history = _read_manifest(doc_dir)["history"]
    assert history[-1]["event"] == "llm_plan_parsed"


def test_plan_never_builds_path_with_colon(plan_app, monkeypatch: pytest.MonkeyPatch):
    app, set_response, make_doc, _, valid_plan = plan_app
    doc_id = "sha256:" + "f" * 64
    doc_dir = make_doc(doc_id)
    set_response(json.dumps(valid_plan(doc_id)))

    calls: list[Path] = []
    original = library_routes.doc_id_to_fs_path

    def _tracking_doc_id_to_fs_path(root: Path, identifier: str, *, shard: bool = True) -> Path:
        path = original(root, identifier, shard=shard)
        calls.append(path)
        return path

    monkeypatch.setattr(library_routes, "doc_id_to_fs_path", _tracking_doc_id_to_fs_path)

    response = app.test_client().post(f"/library/llm/plan/{doc_id}", json={})
    assert response.status_code == 200
    assert (doc_dir / "llm_plan.json").exists()
    assert calls, "doc_id_to_fs_path should have been invoked"
    for path in calls:
        assert all(":" not in part for part in path.parts)
