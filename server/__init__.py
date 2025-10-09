"""Fabrique Flask et configuration de l'application."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import platform
import time
from pathlib import Path
from typing import Dict, Iterable, List

import flask
from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

try:  # pragma: no cover - dépendances optionnelles
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False

from config import settings

from .assets_bootstrap import ensure_assets
from .blueprints import get_blueprints
from .bootstrap import ensure_instance_bootstrap
from .services.assets import detect_tab_duplicates, get_asset_version
from .services.journal_service import JournalService
from .services.openai_client import get_openai_client, is_openai_configured
from .services.patients import (
    get_diagnostics,
    get_patients_source,
    list_patients,
    reload_patients,
)
from .utils.three_vendor import ensure_draco_decoder


LOGGER = logging.getLogger("assist.server")

mimetypes.add_type('application/wasm', '.wasm')


def _detect_static_assets(static_dir: Path) -> Dict[str, Dict[str, str]]:
    assets = {
        "app.js": (static_dir / "app.js", "/static/app.js"),
        "styles/base.css": (static_dir / "styles" / "base.css", "/static/styles/base.css"),
        "styles/diagnostics.css": (static_dir / "styles" / "diagnostics.css", "/static/styles/diagnostics.css"),
        "js/debug.js": (static_dir / "js" / "debug.js", "/static/js/debug.js"),
        "unregister-sw.js": (static_dir / "unregister-sw.js", "/static/unregister-sw.js"),
    }
    manifest: Dict[str, Dict[str, str]] = {}
    for key, (path, url) in assets.items():
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        info = {
            "path": str(path),
            "url": url,
            "size": 0,
            "hash": None,
            "contentType": content_type,
        }
        if path.exists():
            data = path.read_bytes()
            info["size"] = len(data)
            info["hash"] = hashlib.sha256(data).hexdigest()
        manifest[key] = info
    return manifest


def create_app() -> Flask:
    base_dir = Path(__file__).resolve().parent.parent
    env_candidates: Iterable[Path] = (
        base_dir / ".env",
        base_dir / ".env.dev",
    )
    loaded_env_files: List[str] = []
    for candidate in env_candidates:
        try:
            if load_dotenv(dotenv_path=candidate, override=False):
                loaded_env_files.append(str(candidate))
        except TypeError:  # pragma: no cover - compatibilité fallback
            if load_dotenv():  # type: ignore[func-returns-value]
                loaded_env_files.append(str(candidate))

    def _mask_env_value(key: str, value: str | None) -> str | None:
        if value is None:
            return None
        sensitive_markers = ("KEY", "SECRET", "TOKEN", "PASSWORD")
        if any(marker in key.upper() for marker in sensitive_markers):
            return "***"
        return value

    def _snapshot_env(keys: Iterable[str]) -> Dict[str, str | None]:
        return {key: _mask_env_value(key, os.getenv(key)) for key in keys}

    env_snapshot = _snapshot_env(
        (
            "PORT",
            "API_BASE_URL",
            "API_BASE_RELATIVE",
            "HOST",
            "CORS_EXTRA_ORIGINS",
            "PATIENTS_DIR",
            "PATIENTS_ARCHIVES_DIRS",
            "FLASK_ENV",
            "FLASK_DEBUG",
        )
    )
    LOGGER.info(
        "Configuration .env chargée depuis %s : %s",
        ", ".join(loaded_env_files) if loaded_env_files else "<aucun>",
        env_snapshot,
        extra={
            "loaded_env_files": loaded_env_files or ["<none>"],
            "env_snapshot": env_snapshot,
        },
    )

    bootstrap_info = ensure_instance_bootstrap(base_dir)
    patients_snapshot = reload_patients()
    initial_patients = patients_snapshot.get("patients", []) if isinstance(patients_snapshot, dict) else []
    patients_count = len(initial_patients)
    patients_source = patients_snapshot.get("source") if isinstance(patients_snapshot, dict) else get_patients_source()

    static_dir = base_dir / "client"
    templates_dir = Path(__file__).resolve().parent / "templates"

    app = Flask(
        __name__,
        static_folder=str(static_dir),
        static_url_path="/static",
        template_folder=str(templates_dir),
    )

    ensure_assets()
    ensure_draco_decoder(Path(app.static_folder))

    app.extensions["journal_service"] = JournalService(Path(app.instance_path))

    api_base_url = os.getenv("API_BASE_URL", settings.API_BASE_RELATIVE)
    allowed_origins = list(dict.fromkeys(settings.ALLOWED_ORIGINS))
    resolved_port = int(os.getenv("PORT", settings.PORT))
    openai_configured = is_openai_configured()
    # Limite globale pour les uploads audio/POST.  On privilégie AUDIO_MAX_MB
    # pour l'audio mais conservons POST_MAX_SIZE_MB comme valeur de secours.
    post_max_size_mb = int(os.getenv("AUDIO_MAX_MB", os.getenv("POST_MAX_SIZE_MB", "300")))

    config_path = base_dir / "config" / "app_config.json"
    features = {}
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                features = payload.get("features", {}) or {}
        except json.JSONDecodeError:
            LOGGER.warning("Fichier app_config.json invalide", exc_info=True)

    if not os.getenv("ASSET_VERSION"):
        generated_version = f"postv2-{int(time.time())}"
        os.environ["ASSET_VERSION"] = generated_version
    asset_version = get_asset_version(static_dir)
    tab_duplicates = detect_tab_duplicates(static_dir)

    def _resolve_bool(name: str, *, feature_key: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            value = features.get(feature_key, default)
        if isinstance(value, str):
            value = value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    library_root_env = os.getenv("LIBRARY_ROOT")
    if library_root_env:
        library_root = Path(library_root_env).expanduser().resolve()
    else:
        library_root = Path(app.instance_path) / "library"
    try:
        library_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        LOGGER.error("Impossible de créer le répertoire de bibliothèque %s", library_root, exc_info=True)
        raise

    extracted_root = library_root / "extracted"
    logs_root = library_root / "logs"
    raw_root = library_root / "raw_pdfs"
    lock_root = logs_root / "locks"
    try:
        extracted_root.mkdir(parents=True, exist_ok=True)
        logs_root.mkdir(parents=True, exist_ok=True)
        raw_root.mkdir(parents=True, exist_ok=True)
        lock_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        LOGGER.error("Impossible de créer le répertoire d'extraction %s", extracted_root, exc_info=True)
        raise

    feature_library_fs_v2 = _resolve_bool("FEATURE_LIBRARY_FS_V2", feature_key="library_fs_v2", default=True)
    feature_library_autofill = _resolve_bool(
        "FEATURE_LIBRARY_AUTOFILL", feature_key="library_autofill", default=True
    )
    feature_library_file_locks = _resolve_bool(
        "FEATURE_LIBRARY_FILE_LOCKS", feature_key="library_file_locks", default=False
    )

    sharding_flag = os.getenv("LIBRARY_FS_SHARDING")
    if sharding_flag is None:
        sharding_flag = features.get("library_fs_sharding", True)
    if isinstance(sharding_flag, str):
        library_fs_sharding = sharding_flag.strip().lower() not in {"0", "false", "no", "off", "flat"}
    else:
        library_fs_sharding = bool(sharding_flag)

    # Configurer la taille maximale du contenu et le timeout des requêtes
    request_timeout = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "120"))
    app.config.update(
        ASSET_VERSION=asset_version,
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret"),
        API_BASE_URL=api_base_url,
        TEMPLATES_AUTO_RELOAD=True,
        JSON_AS_ASCII=False,
        SERVER_PORT=resolved_port,
        SERVER_HOST=settings.HOST,
        DEMO_MODE=bool(bootstrap_info.get("demo_mode")) if isinstance(bootstrap_info, dict) else False,
        PATIENTS_SOURCE=patients_source,
        PATIENTS_COUNT=patients_count,
        OPENAI_CONFIGURED=openai_configured,
        TAB_DUPLICATES=tab_duplicates,
        MAX_CONTENT_LENGTH=post_max_size_mb * 1024 * 1024,
        REQUEST_TIMEOUT_SECONDS=request_timeout,
        LIBRARY_ROOT=str(library_root),
        LIBRARY_EXTRACTED_ROOT=str(extracted_root),
        LIBRARY_LOG_ROOT=str(logs_root),
        LIBRARY_RAW_ROOT=str(raw_root),
        LIBRARY_LOCK_ROOT=str(lock_root),
        LIBRARY_FS_SHARDING=library_fs_sharding,
        FEATURE_LIBRARY_FS_V2=feature_library_fs_v2,
        FEATURE_LIBRARY_AUTOFILL=feature_library_autofill,
        FEATURE_LIBRARY_FILE_LOCKS=feature_library_file_locks,
    )

    LOGGER.info(
        "Bibliothèque initialisée",
        extra={
            "library_root": str(library_root),
            "library_extracted_root": str(extracted_root),
            "library_log_root": str(logs_root),
            "library_raw_root": str(raw_root),
            "library_lock_root": str(lock_root),
            "feature_library_fs_v2": feature_library_fs_v2,
            "feature_library_autofill": feature_library_autofill,
            "feature_library_file_locks": feature_library_file_locks,
            "library_fs_sharding": library_fs_sharding,
        },
    )

    CORS(
        app,
        resources={r"/api/*": {"origins": allowed_origins}},
    )

    assets_manifest = _detect_static_assets(static_dir)

    @app.after_request
    def _cache_headers(response: Response) -> Response:
        path = request.path or ""
        is_static = path.startswith("/static/") or path.startswith("/assets/")
        if is_static and not app.debug:
            if response.mimetype in {"application/javascript", "text/javascript", "text/css"}:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                response.set_etag(app.config["ASSET_VERSION"])
            return response

        response.headers.pop("ETag", None)
        if app.debug:
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for blueprint in get_blueprints():
        app.register_blueprint(blueprint)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_413(_error: RequestEntityTooLarge):
        max_mb = int(os.getenv("POST_MAX_SIZE_MB", "300"))
        return (
            jsonify(
                {
                    "ok": False,
                    "error": {
                        "type": "request_entity_too_large",
                        "message": f"Fichier audio trop volumineux (limite {max_mb} MB).",
                        "max_mb": max_mb,
                    },
                }
            ),
            413,
        )

    def _probe_openai_health() -> Dict[str, object]:
        ok_env = is_openai_configured()
        ok_llm = False
        detail: str | None = None
        if ok_env:
            client = get_openai_client()
            if client is None:
                detail = "Client OpenAI non initialisé"
            else:
                try:  # pragma: no cover - réseau
                    client.models.list()
                    ok_llm = True
                except Exception as exc:  # pragma: no cover - réseau
                    detail = f"{type(exc).__name__}: {exc}"
                    print("[health] OpenAI check failed ->", detail)
                    LOGGER.warning("OpenAI health check failed", exc_info=True)
        return {"env": ok_env, "llm": ok_llm, "detail": detail}

    def _build_health_payload(llm_status: Dict[str, object] | None = None) -> Dict[str, object]:
        if llm_status is None:
            status = _probe_openai_health()
        else:
            env_ok = bool(llm_status.get("env"))
            llm_ok = bool(llm_status.get("llm")) if env_ok else False
            detail = llm_status.get("detail") if isinstance(llm_status, dict) else None
            status = {"env": env_ok, "llm": llm_ok, "detail": detail}
        app.config["OPENAI_CONFIGURED"] = bool(status["env"])
        diagnostics = get_diagnostics()
        patients_count = int(diagnostics.get("count") or len(list_patients()) or 0)
        patients_source = diagnostics.get("source") or get_patients_source()
        raw_roots = diagnostics.get("roots") or []
        patients_roots = [str(root) for root in raw_roots if str(root)]

        def _resolve_patients_dir() -> str:
            candidates = list(patients_roots)
            if not candidates and patients_source:
                candidates.extend(
                    [segment for segment in str(patients_source).split(os.pathsep) if segment]
                )
            for candidate in candidates:
                try:
                    path = Path(candidate)
                    if not path.is_absolute():
                        path = (base_dir / candidate).resolve()
                    else:
                        path = path.resolve()
                except (OSError, RuntimeError):
                    continue
                return str(path)
            return ""

        patients_dir_abs = _resolve_patients_dir()
        static_ok = all(Path(info["path"]).exists() for info in assets_manifest.values())
        from server.blueprints import library as library_bp  # type: ignore  # noqa: E402

        plan_counters = getattr(library_bp, "LLM_PLAN_COUNTERS", None)
        if isinstance(plan_counters, dict):
            plan_metrics = dict(plan_counters)
        else:
            try:
                plan_metrics = dict(plan_counters or {})
            except TypeError:  # pragma: no cover - defensive
                plan_metrics = {}
        return {
            "ts": int(time.time()),
            "python": platform.python_version(),
            "flask": flask.__version__,
            "patients_count": patients_count,
            "patients_source": patients_source,
            "patients_dir_abs": patients_dir_abs,
            "patients_roots": patients_roots,
            "static_ok": bool(static_ok),
            "demo_mode": bool(app.config.get("DEMO_MODE", False)),
            "api_base": app.config.get("API_BASE_URL", ""),
            "port_effective": app.config.get("SERVER_PORT", settings.PORT),
            "blueprints": sorted(app.blueprints.keys()),
            "openai_configured": bool(app.config.get("OPENAI_CONFIGURED", False)),
            "openai_health": status,
            "env": status["env"],
            "llm": status["llm"],
            "detail": status.get("detail"),
            "llm_plan_counters": plan_metrics,
        }

    @app.get("/api/health")
    def api_health():
        payload = _build_health_payload()
        return jsonify({"ok": True, **payload})

    @app.get("/health")
    def health():  # pragma: no cover - simple proxy
        payload = _build_health_payload()
        return jsonify({"ok": True, **payload})

    @app.get("/api/assets-manifest")
    def api_assets_manifest():
        return jsonify({"ok": True, "assets": assets_manifest})

    @app.get("/api/version")
    def api_version():
        return jsonify(
            {
                "ok": True,
                "assetVersion": app.config["ASSET_VERSION"],
                "port": app.config.get("SERVER_PORT", settings.PORT),
            }
        )

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            asset_version=app.config["ASSET_VERSION"],
            api_base_url=app.config["API_BASE_URL"],
            openai_configured=app.config.get("OPENAI_CONFIGURED", False),
            tab_duplicates=tab_duplicates,
            debug_mode=app.debug,
        )

    @app.route("/assets/<path:filename>")
    def serve_assets(filename: str):
        return send_from_directory(base_dir / "assets", filename)

    LOGGER.info("Flask %s — Python %s", flask.__version__, platform.python_version())
    LOGGER.info("Base dir: %s", base_dir)
    LOGGER.info("Static dir: %s", static_dir)
    LOGGER.info("Templates dir: %s", templates_dir)
    LOGGER.info("Instance dir: %s", app.instance_path)
    LOGGER.info("Port effectif: %s", resolved_port)
    LOGGER.info("API base URL: %s", app.config["API_BASE_URL"] or "relative")
    LOGGER.info("Patients source : %s", patients_source or "inconnue")
    LOGGER.info("Patients détectés : %d", patients_count)
    LOGGER.info("CORS origins: %s", ", ".join(allowed_origins))
    LOGGER.info(
        "Blueprints actifs: %s",
        ", ".join(sorted(app.blueprints.keys())),
    )
    for key, info in assets_manifest.items():
        LOGGER.info("Asset %s — %s octets — présent=%s", key, info["size"], Path(info["path"]).exists())

    return app


__all__ = ["create_app"]

