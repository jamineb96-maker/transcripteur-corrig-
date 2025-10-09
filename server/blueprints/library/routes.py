"""Blueprints offering library-related endpoints.

Ce fichier héberge désormais deux blueprints :

* ``bp`` : historique, accessible sous ``/api/library`` pour les
  fonctionnalités existantes de recherche légère.
* ``library_ingest_bp`` : nouvel espace ``/library`` dédié à la future
  chaîne d'ingestion et de curation. Les routes sont ajoutées de manière
  incrémentale afin de respecter la contrainte d'additivité.
"""
from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from collections import Counter

from flask import Blueprint, jsonify, request, current_app
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFSyntaxError
from pydantic import ValidationError

from modules.library_index import ensure_index_layout, hybrid_search, index_notion, index_segments
from modules.library_ingest import (
    InvalidDocumentId,
    compute_doc_hash,
    extract_text,
    persist_extraction,
    segment_pages,
)
from modules.library_llm import (
    LLMPlanGeneration,
    LibraryLLMError,
    LibraryLLMUpstreamError,
    RelaxedParseResult,
    parse_llm_plan_relaxed,
    propose_notions,
)
from server.library.store.manifest import (
    append_manifest_history,
    ensure_manifest,
    load_manifest,
    resolve_extraction_dir,
    update_manifest,
)
from server.utils.docid import doc_id_to_fs_path, ensure_dir, legacy_fs_path, parse_doc_id
from server.utils.fs_atomic import atomic_write, atomic_write_bytes, atomic_write_text
from server.services.metadata_infer import (
    default_toggles,
    extract_pdf_streams,
    infer_authors,
    infer_domains,
    infer_evidence_level,
    infer_keywords,
    infer_title,
    infer_type,
    infer_year,
    propose_critical_notes,
    should_pseudonymize,
)
from .json_tools import lenient_json_loads
from .plan_schema import (
    PlanV1,
    SCHEMA_VERSION,
    normalize_plan_payload,
)

try:  # pragma: no cover - dépendance optionnelle
    from filelock import FileLock
except ModuleNotFoundError:  # pragma: no cover - fallback sans verrouillage
    FileLock = None  # type: ignore[misc]


LOGGER = logging.getLogger(__name__)

bp = Blueprint("library", __name__, url_prefix="/api/library")
library_ingest_bp = Blueprint("library_ingest", __name__ + "_ingest", url_prefix="/library")

ensure_index_layout()

EXECUTOR = ThreadPoolExecutor(max_workers=2)
STATE_LOCK = threading.Lock()
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

LLM_PLAN_COUNTERS: Counter[str] = Counter()


@dataclass(frozen=True)
class LibraryFSConfig:
    library_root: Path
    extracted_root: Path
    raw_root: Path
    log_root: Path
    lock_root: Path
    feature_v2: bool
    shard: bool
    feature_autofill: bool
    use_locks: bool


def _resolve_fs_config() -> LibraryFSConfig:
    config = current_app.config
    library_root = Path(config.get("LIBRARY_ROOT", Path(current_app.instance_path) / "library"))
    extracted_root = Path(config.get("LIBRARY_EXTRACTED_ROOT", library_root / "extracted"))
    raw_root = Path(config.get("LIBRARY_RAW_ROOT", library_root / "raw_pdfs"))
    log_root = Path(config.get("LIBRARY_LOG_ROOT", library_root / "logs"))
    lock_root = Path(config.get("LIBRARY_LOCK_ROOT", log_root / "locks"))
    shard_value = config.get("LIBRARY_FS_SHARDING", True)
    if isinstance(shard_value, str):
        shard = shard_value.strip().lower() not in {"0", "false", "no", "off", "flat"}
    else:
        shard = bool(shard_value)
    feature_v2 = bool(config.get("FEATURE_LIBRARY_FS_V2", True))
    feature_autofill = bool(config.get("FEATURE_LIBRARY_AUTOFILL", True))
    locks_value = config.get("FEATURE_LIBRARY_FILE_LOCKS", False)
    if isinstance(locks_value, str):
        locks_enabled = locks_value.strip().lower() not in {"0", "false", "no", "off"}
    else:
        locks_enabled = bool(locks_value)
    ensure_dir(library_root)
    ensure_dir(extracted_root)
    ensure_dir(raw_root)
    ensure_dir(log_root)
    ensure_dir(lock_root)
    return LibraryFSConfig(
        library_root=library_root,
        extracted_root=extracted_root,
        raw_root=raw_root,
        log_root=log_root,
        lock_root=lock_root,
        feature_v2=feature_v2,
        shard=shard,
        feature_autofill=feature_autofill,
        use_locks=locks_enabled,
    )


@contextlib.contextmanager
def _doc_lock(fs_config: LibraryFSConfig, doc_id: str):
    """Retourne un verrou fichier si activé, sinon un contexte neutre."""

    if not fs_config.use_locks or FileLock is None:
        yield None
        return
    lock_target = doc_id_to_fs_path(fs_config.lock_root, doc_id, shard=fs_config.shard).with_suffix(".lock")
    ensure_dir(lock_target.parent)
    lock = FileLock(str(lock_target))
    try:
        lock.acquire()
        yield lock
    finally:
        try:
            lock.release()
        except Exception:  # pragma: no cover - lib filelock peut lever
            LOGGER.debug("lock_release_failed", extra={"doc_id": doc_id}, exc_info=True)


def _state_path(fs_config: LibraryFSConfig) -> Path:
    return fs_config.log_root / "state.json"


def _metadata_path(fs_config: LibraryFSConfig) -> Path:
    return fs_config.library_root / "metadata.jsonl"


def _notions_path(fs_config: LibraryFSConfig) -> Path:
    return fs_config.library_root / "notions.jsonl"


def _load_state(fs_config: LibraryFSConfig) -> Dict[str, Dict[str, object]]:
    path = _state_path(fs_config)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


TASK_STATE: Dict[str, Dict[str, object]] = {}


def _ensure_state_loaded(fs_config: LibraryFSConfig) -> None:
    if TASK_STATE:
        return
    TASK_STATE.update(_load_state(fs_config))


def _save_state(fs_config: LibraryFSConfig) -> None:
    path = _state_path(fs_config)
    ensure_dir(path.parent)
    atomic_write_text(path, json.dumps(TASK_STATE, ensure_ascii=False, indent=2))


def _update_task(fs_config: LibraryFSConfig, doc_id: str, **values: object) -> None:
    with STATE_LOCK:
        task = TASK_STATE.setdefault(doc_id, {})
        task.update(values)
        _save_state(fs_config)

    status_value = values.get("status")
    if isinstance(status_value, str):
        try:
            manifest_dir, _ = _load_manifest_entry(doc_id, fs_config)
            if manifest_dir is None:
                manifest_dir = _primary_extraction_dir(doc_id, fs_config)
            update_manifest(manifest_dir, {"state": status_value})
        except Exception:  # pragma: no cover - persistance best-effort
            LOGGER.warning("manifest_state_update_failed", extra={"doc_id": doc_id}, exc_info=True)


def _append_jsonl(path: Path, payload: Dict[str, object]) -> None:
    ensure_dir(path.parent)
    entries = _load_jsonl(path)
    entries.append(dict(payload))

    def _writer(tmp_path: Path) -> None:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False))
                handle.write("\n")

    atomic_write(path, _writer)


def _load_jsonl(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    entries: List[Dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _upsert_metadata(fs_config: LibraryFSConfig, entry: Dict[str, object]) -> None:
    path = _metadata_path(fs_config)
    entries = _load_jsonl(path)
    doc_id = entry.get("doc_id")
    updated = False
    for idx, existing in enumerate(entries):
        if existing.get("doc_id") == doc_id:
            entries[idx] = entry
            updated = True
            break
    if not updated:
        entries.append(entry)
    ensure_dir(path.parent)

    def _writer(tmp_path: Path) -> None:
        with tmp_path.open("w", encoding="utf-8") as handle:
            for item in entries:
                handle.write(json.dumps(item, ensure_ascii=False))
                handle.write("\n")

    atomic_write(path, _writer)


def _get_metadata(doc_id: str, fs_config: LibraryFSConfig) -> Optional[Dict[str, object]]:
    for entry in _load_jsonl(_metadata_path(fs_config)):
        if entry.get("doc_id") == doc_id:
            return entry
    return None


def _next_notion_version(notion_id: str, fs_config: LibraryFSConfig) -> int:
    version = 0
    for entry in _load_jsonl(_notions_path(fs_config)):
        if entry.get("kind") == "notion" and entry.get("notion_id") == notion_id:
            version = max(version, int(entry.get("version", 0)))
    return version + 1


def _candidate_extraction_dirs(doc_id: str, fs_config: LibraryFSConfig) -> List[Path]:
    try:
        parse_doc_id(doc_id)
    except ValueError:
        return []
    candidates: List[Path] = []
    primary = doc_id_to_fs_path(fs_config.extracted_root, doc_id, shard=fs_config.shard)
    legacy = legacy_fs_path(fs_config.extracted_root, doc_id)
    for path in (primary, legacy):
        if path not in candidates:
            candidates.append(path)
    return candidates


def _raw_pdf_candidates(fs_config: LibraryFSConfig, doc_id: str) -> List[Path]:
    primary = doc_id_to_fs_path(fs_config.raw_root, doc_id, shard=fs_config.shard).with_suffix(".pdf")
    legacy = legacy_fs_path(fs_config.raw_root, doc_id).with_suffix(".pdf")
    flat = fs_config.raw_root / f"{doc_id}.pdf"
    candidates: List[Path] = []
    for candidate in (primary, legacy, flat):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _resolve_raw_pdf_path(
    fs_config: LibraryFSConfig, doc_id: str, *, ensure_parent: bool = False
) -> Path:
    for candidate in _raw_pdf_candidates(fs_config, doc_id):
        if candidate.exists():
            return candidate
    target = doc_id_to_fs_path(fs_config.raw_root, doc_id, shard=fs_config.shard).with_suffix(".pdf")
    if ensure_parent:
        ensure_dir(target.parent)
    return target


def _load_manifest_entry(doc_id: str, fs_config: LibraryFSConfig) -> tuple[Path | None, Dict[str, object]]:
    for candidate in _candidate_extraction_dirs(doc_id, fs_config):
        manifest = load_manifest(candidate)
        if manifest:
            return candidate, manifest
    return None, {}


def _primary_extraction_dir(doc_id: str, fs_config: LibraryFSConfig) -> Path:
    return resolve_extraction_dir(
        fs_config.extracted_root,
        doc_id,
        shard=fs_config.shard,
        feature_v2=fs_config.feature_v2,
    )


def _validate_pdf_payload(
    file: "werkzeug.datastructures.FileStorage", payload: bytes
) -> tuple[bool, Dict[str, object]]:
    mimetype = (file.mimetype or "").lower()
    if mimetype and "pdf" not in mimetype:
        return False, {"error": "invalid_mimetype", "message": "Le fichier doit être un PDF."}
    try:
        page_iter = PDFPage.get_pages(BytesIO(payload), caching=False)
        page_count = sum(1 for _ in page_iter)
    except PDFSyntaxError:
        return False, {"error": "invalid_pdf", "message": "Fichier PDF illisible."}
    except Exception:
        return False, {"error": "invalid_pdf", "message": "Lecture du PDF impossible."}
    if page_count <= 0:
        return False, {"error": "empty_pdf", "message": "Le PDF ne contient aucune page."}
    return True, {"pages": page_count}


def _build_prefill_payload(streams: Dict[str, object]) -> Dict[str, object]:
    title_value, title_provenance = infer_title(streams)
    authors_value, authors_provenance = infer_authors(streams)
    year_value, year_provenance = infer_year(streams)
    doc_type, type_details = infer_type(streams)
    evidence_value, evidence_details = infer_evidence_level(doc_type, streams)
    domains_value = infer_domains(streams)
    keywords_value = infer_keywords(streams)
    critical_notes = propose_critical_notes(streams)
    toggles_value = default_toggles(doc_type, evidence_value, streams, None)
    pseudonymize_flag = should_pseudonymize(streams)

    return {
        "title": {"value": title_value, "provenance": title_provenance},
        "authors": {"value": authors_value, "provenance": authors_provenance},
        "year": {"value": year_value, "provenance": year_provenance},
        "type": {"value": doc_type, **type_details},
        "evidence_level": {"value": evidence_value, **evidence_details},
        "domains": {"value": domains_value, "provenance": "nlp_local"},
        "keywords": keywords_value,
        "critical_candidates": critical_notes,
        "toggles": toggles_value,
        "pseudonymize": pseudonymize_flag,
    }


def _effective_prefill(manifest: Mapping[str, object]) -> Dict[str, object]:
    prefill = manifest.get("prefill") if isinstance(manifest, Mapping) else None
    overrides = manifest.get("user_overrides") if isinstance(manifest, Mapping) else None
    prefill_map: Dict[str, object] = {}
    if isinstance(prefill, Mapping):
        for key, value in prefill.items():
            prefill_map[key] = value
    if isinstance(overrides, Mapping):
        for key, payload in overrides.items():
            if isinstance(payload, Mapping) and "value" in payload:
                prefill_map[key] = {
                    "value": payload.get("value"),
                    "provenance": "user_override",
                    "updated_at": payload.get("updated_at"),
                }
    return prefill_map


def _run_metadata_autofill(
    doc_id: str,
    pdf_path: Path,
    fs_config: LibraryFSConfig,
    *,
    force: Mapping[str, bool] | None = None,
) -> Dict[str, object]:
    streams = extract_pdf_streams(pdf_path)
    prefill_payload = _build_prefill_payload(streams)
    language = streams.get("language") if isinstance(streams, Mapping) else None

    extraction_dir = _primary_extraction_dir(doc_id, fs_config)
    with _doc_lock(fs_config, doc_id):
        manifest = load_manifest(extraction_dir)
        overrides = manifest.get("user_overrides") if isinstance(manifest, Mapping) else {}
        existing_prefill = manifest.get("prefill") if isinstance(manifest, Mapping) else {}
        overrides = dict(overrides) if isinstance(overrides, Mapping) else {}
        force_map = {str(key): bool(value) for key, value in (force or {}).items()}

        for field, payload in list(overrides.items()):
            if force_map.get(field):
                overrides.pop(field, None)
                continue
            if isinstance(existing_prefill, Mapping) and field in existing_prefill:
                prefill_payload[field] = existing_prefill[field]

        update_manifest(
            extraction_dir,
            {
                "language": language,
                "prefill": prefill_payload,
                "prefill_generated_at": datetime.now(timezone.utc).isoformat(),
                "user_overrides": overrides,
            },
        )
        return load_manifest(extraction_dir)


def _extraction_worker(
    doc_id: str,
    pdf_path: Path,
    fs_config: LibraryFSConfig,
    manifest_context: Dict[str, object],
) -> None:
    start_time = datetime.now(timezone.utc).isoformat()
    with _doc_lock(fs_config, doc_id):
        _update_task(fs_config, doc_id, status="running", reason=None, updated_at=start_time)
    LOGGER.info(
        "started_extraction",
        extra={"doc_id": doc_id, "pdf_path": str(pdf_path), "feature_v2": fs_config.feature_v2},
    )
    try:
        pages = extract_text(pdf_path)
        segments = segment_pages(pages)
        with _doc_lock(fs_config, doc_id):
            target_dir = persist_extraction(
                doc_id,
                pages,
                segments,
                extracted_root=fs_config.extracted_root,
                shard=fs_config.shard,
                source_filename=manifest_context.get("source_filename"),
                file_size_bytes=manifest_context.get("bytes"),
                tags=manifest_context.get("tags") or [],
                options=manifest_context.get("options") or {},
                feature_v2=fs_config.feature_v2,
            )
        index_segments(doc_id, segments)
        with _doc_lock(fs_config, doc_id):
            _update_task(
                fs_config,
                doc_id,
                status="done",
                reason=None,
                pages=len(pages),
                segments=len(segments),
                fs_path=str(target_dir),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        LOGGER.info(
            "finished_extraction",
            extra={
                "doc_id": doc_id,
                "fs_path": str(target_dir),
                "pages": len(pages),
                "segments": len(segments),
            },
        )
    except InvalidDocumentId as exc:
        LOGGER.warning(
            "failed_extraction",
            extra={"doc_id": doc_id, "reason": "invalid_doc_id", "message": str(exc)},
        )
        with _doc_lock(fs_config, doc_id):
            _update_task(
                fs_config,
                doc_id,
                status="failed",
                reason="invalid_doc_id",
                message=str(exc),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
    except Exception as exc:  # pragma: no cover - robustesse
        LOGGER.exception(
            "failed_extraction",
            extra={"doc_id": doc_id, "reason": "extraction_failed"},
        )
        with _doc_lock(fs_config, doc_id):
            _update_task(
                fs_config,
                doc_id,
                status="failed",
                reason="extraction_failed",
                message="internal_error",
                updated_at=datetime.now(timezone.utc).isoformat(),
            )


def _enqueue_extraction(
    doc_id: str,
    pdf_path: Path,
    fs_config: LibraryFSConfig,
    manifest_context: Dict[str, object],
) -> None:
    _ensure_state_loaded(fs_config)
    with _doc_lock(fs_config, doc_id):
        _update_task(
            fs_config,
            doc_id,
            status="queued",
            reason=None,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
    LOGGER.info(
        "queued_extraction",
        extra={"doc_id": doc_id, "pdf_path": str(pdf_path), "feature_v2": fs_config.feature_v2},
    )

    def _runner() -> None:
        _extraction_worker(doc_id, pdf_path, fs_config, manifest_context)

    EXECUTOR.submit(_runner)


def _parse_list(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [item.strip() for item in str(raw).replace(";", ",").split(",") if item.strip()]


def _parse_checkbox(value: object) -> bool:
    """Interpret raw checkbox form values into a boolean."""

    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    normalised = str(value).strip().lower()
    if not normalised:
        return False
    if normalised in {"0", "false", "no", "off"}:
        return False
    return normalised in {"1", "true", "yes", "on", "checked"}


def _build_metadata_payload(form: Dict[str, str], doc_id: str, pdf_path: Path, existing: Dict[str, object] | None = None) -> Dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "doc_id": doc_id,
        "title": form.get("title", "Document sans titre"),
        "authors": _parse_list(form.get("authors")),
        "year": int(form.get("year", 0) or 0) or None,
        "type": form.get("type") or "article",
        "domains": _parse_list(form.get("domains")),
        "keywords": _parse_list(form.get("keywords")),
        "evidence_level": form.get("evidence_level") or "theorique",
        "notes": form.get("notes") or "",
        "autosuggest_pre_default": _parse_checkbox(form.get("autosuggest_pre_default")),
        "autosuggest_post_default": _parse_checkbox(form.get("autosuggest_post_default")),
        "created_at": existing.get("created_at") if existing else now,
        "source_path": str(pdf_path),
    }
    return entry


def _read_segments(doc_id: str, fs_config: LibraryFSConfig) -> List[Dict[str, object]]:
    for extraction_dir in _candidate_extraction_dirs(doc_id, fs_config):
        segments_path = extraction_dir / "segments.jsonl"
        if segments_path.exists():
            return _load_jsonl(segments_path)
    return []


def _validate_plan_schema(payload: Mapping[str, Any], *, doc_id: str) -> tuple[Dict[str, Any], str, str]:
    """Validate the payload against PlanV1 and return the normalised plan."""

    normalised = normalize_plan_payload(dict(payload or {}), doc_id=doc_id)
    model = PlanV1.model_validate(normalised)
    plan = model.model_dump()
    quality = "full" if plan.get("proposed_notions") else "partial"
    return plan, quality, model.schema_version


def _persist_plan_artifact(
    extraction_dir: Path,
    doc_id: str,
    generation: LLMPlanGeneration,
    *,
    plan: Mapping[str, Any] | None,
    quality: str,
    reason: str | None,
    parse_errors: List[str],
    errors: List[str],
    schema_version: str | None = None,
) -> Path:
    ensure_dir(extraction_dir)
    artifact = {
        "doc_id": doc_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "degraded" if quality == "degraded" else "ok",
        "quality": quality,
        "model": generation.model,
        "finish_reason": generation.finish_reason,
        "has_tool_calls": generation.has_tool_calls,
        "raw_llm": generation.raw_content[:4096],
        "raw_length": len(generation.raw_content),
        "parse_errors": parse_errors,
        "errors": errors,
    }
    if len(generation.raw_content) > 4096:
        artifact["raw_truncated"] = True
    if plan is not None:
        artifact["parsed"] = plan
    if reason:
        artifact["reason"] = reason
    if schema_version:
        artifact["schema_version"] = schema_version
    artifact_path = extraction_dir / "llm_plan.json"

    def _writer(tmp_path: Path) -> None:
        tmp_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    atomic_write(artifact_path, _writer)
    return artifact_path


@library_ingest_bp.post("/upload")
def upload_document():
    file = request.files.get("file")
    if file is None:
        return jsonify({"ok": False, "error": "Fichier PDF requis."}), 400
    payload = file.read()
    if not payload:
        return jsonify({"ok": False, "error": "Le fichier est vide."}), 400
    if len(payload) > MAX_UPLOAD_BYTES:
        return jsonify({"ok": False, "error": "Le fichier dépasse la taille autorisée (25 Mo)."}), 413

    is_valid_pdf, pdf_info = _validate_pdf_payload(file, payload)
    if not is_valid_pdf:
        return jsonify(pdf_info), 400

    fs_config = _resolve_fs_config()
    doc_id = compute_doc_hash(payload)

    try:
        parse_doc_id(doc_id)
    except ValueError:
        return jsonify({"error": "invalid_doc_id"}), 400

    target_path = _resolve_raw_pdf_path(fs_config, doc_id)
    extraction_dir = _primary_extraction_dir(doc_id, fs_config)

    with _doc_lock(fs_config, doc_id):
        if not target_path.exists():
            ensure_dir(target_path.parent)
            atomic_write_bytes(target_path, payload)
        else:
            try:
                existing_size = target_path.stat().st_size
            except OSError:
                existing_size = -1
            if existing_size != len(payload):
                atomic_write_bytes(target_path, payload)

        ensure_manifest(
            doc_id,
            extraction_dir,
            source_filename=file.filename,
            file_size_bytes=len(payload),
        )

        existing = _get_metadata(doc_id, fs_config) or {}
        form_data = {key: request.form.get(key, "") for key in request.form.keys()}
        metadata_entry = _build_metadata_payload(form_data, doc_id, target_path, existing=existing)
        _upsert_metadata(fs_config, metadata_entry)

        manifest_context = {
            "source_filename": file.filename,
            "bytes": len(payload),
            "pages": pdf_info.get("pages"),
            "tags": metadata_entry.get("keywords") or [],
            "options": {
                "autosuggest_pre_default": metadata_entry.get("autosuggest_pre_default", False),
                "autosuggest_post_default": metadata_entry.get("autosuggest_post_default", False),
            },
        }

        update_manifest(
            extraction_dir,
            {
                "metadata_form": metadata_entry,
                "uploaded_pages": pdf_info.get("pages"),
            },
        )

    manifest_data = load_manifest(extraction_dir)
    prefill_manifest: Dict[str, object] | None = None
    if fs_config.feature_autofill:
        try:
            manifest_data = _run_metadata_autofill(doc_id, target_path, fs_config)
            prefill_manifest = manifest_data.get("prefill") if isinstance(manifest_data, Mapping) else None
            LOGGER.info(
                "metadata_prefill_generated",
                extra={
                    "doc_id": doc_id,
                    "fields": sorted(prefill_manifest.keys()) if isinstance(prefill_manifest, Mapping) else [],
                },
            )
        except Exception as exc:  # pragma: no cover - robustesse
            LOGGER.warning("metadata_prefill_failed", extra={"doc_id": doc_id, "error": str(exc)})

    manifest_data = manifest_data or load_manifest(extraction_dir)

    _ensure_state_loaded(fs_config)
    existing_state = TASK_STATE.get(doc_id, {})
    segments_exists = any((candidate / "segments.jsonl").exists() for candidate in _candidate_extraction_dirs(doc_id, fs_config))
    if existing_state.get("status") == "done" and segments_exists:
        with _doc_lock(fs_config, doc_id):
            _update_task(
                fs_config,
                doc_id,
                status="done",
                reason=None,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        LOGGER.info("reuse_extraction", extra={"doc_id": doc_id})
    else:
        _enqueue_extraction(doc_id, target_path, fs_config, manifest_context)

    return jsonify(
        {
            "ok": True,
            "doc_id": doc_id,
            "status": TASK_STATE.get(doc_id),
            "metadata": metadata_entry,
            "prefill": manifest_data.get("prefill") if isinstance(manifest_data, Mapping) else None,
            "language": manifest_data.get("language") if isinstance(manifest_data, Mapping) else None,
            "user_overrides": manifest_data.get("user_overrides") if isinstance(manifest_data, Mapping) else {},
        }
    )


@library_ingest_bp.get("/extract/<doc_id>/status")
def extraction_status(doc_id: str):
    fs_config = _resolve_fs_config()
    try:
        parse_doc_id(doc_id)
    except ValueError:
        return jsonify({"error": "invalid_doc_id"}), 400

    _ensure_state_loaded(fs_config)
    status = TASK_STATE.get(doc_id)
    if not status:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "status": status})


@library_ingest_bp.get("/extract/<doc_id>/prefill")
def extraction_prefill(doc_id: str):
    fs_config = _resolve_fs_config()
    if not fs_config.feature_autofill:
        return jsonify({"error": "feature_disabled"}), 404
    try:
        parse_doc_id(doc_id)
    except ValueError:
        return jsonify({"error": "invalid_doc_id"}), 400

    manifest_dir, manifest = _load_manifest_entry(doc_id, fs_config)
    if not manifest:
        return jsonify({"error": "not_found"}), 404
    effective = _effective_prefill(manifest)
    return jsonify(
        {
            "ok": True,
            "doc_id": doc_id,
            "prefill": manifest.get("prefill"),
            "user_overrides": manifest.get("user_overrides") or {},
            "effective": effective,
            "language": manifest.get("language"),
            "generated_at": manifest.get("prefill_generated_at"),
        }
    )


@library_ingest_bp.post("/extract/<doc_id>/prefill")
def extraction_prefill_refresh(doc_id: str):
    fs_config = _resolve_fs_config()
    if not fs_config.feature_autofill:
        return jsonify({"error": "feature_disabled"}), 403
    try:
        parse_doc_id(doc_id)
    except ValueError:
        return jsonify({"error": "invalid_doc_id"}), 400

    pdf_path = _resolve_raw_pdf_path(fs_config, doc_id)
    if not pdf_path.exists():
        return jsonify({"error": "pdf_not_found"}), 404

    payload = request.get_json(silent=True) or {}
    force_map = payload.get("force") if isinstance(payload, dict) else {}
    if force_map and not isinstance(force_map, dict):
        return jsonify({"error": "invalid_force"}), 400

    manifest = _run_metadata_autofill(doc_id, pdf_path, fs_config, force=force_map or None)
    effective = _effective_prefill(manifest)
    return jsonify(
        {
            "ok": True,
            "doc_id": doc_id,
            "prefill": manifest.get("prefill"),
            "user_overrides": manifest.get("user_overrides") or {},
            "effective": effective,
            "language": manifest.get("language"),
            "generated_at": manifest.get("prefill_generated_at"),
        }
    )


@library_ingest_bp.post("/extract/<doc_id>/apply_overrides")
def extraction_apply_overrides(doc_id: str):
    fs_config = _resolve_fs_config()
    try:
        parse_doc_id(doc_id)
    except ValueError:
        return jsonify({"error": "invalid_doc_id"}), 400

    payload = request.get_json(silent=True) or {}
    overrides_payload = payload.get("overrides") if isinstance(payload, dict) else None
    if overrides_payload is None or not isinstance(overrides_payload, dict):
        return jsonify({"error": "invalid_request"}), 400

    with _doc_lock(fs_config, doc_id):
        manifest_dir, manifest = _load_manifest_entry(doc_id, fs_config)
        if manifest_dir is None:
            manifest_dir = _primary_extraction_dir(doc_id, fs_config)
            manifest = load_manifest(manifest_dir)

        current_overrides = manifest.get("user_overrides") if isinstance(manifest, Mapping) else {}
        current_overrides = dict(current_overrides) if isinstance(current_overrides, Mapping) else {}
        changed = False
        now = datetime.now(timezone.utc).isoformat()

        for field, value in overrides_payload.items():
            if isinstance(value, Mapping) and "value" in value:
                entry_value = value.get("value")
            else:
                entry_value = value
            if entry_value is None:
                if field in current_overrides:
                    current_overrides.pop(field)
                    changed = True
                continue
            current_overrides[field] = {"value": entry_value, "updated_at": now}
            changed = True

        if changed:
            update_manifest(manifest_dir, {"user_overrides": current_overrides})

        manifest = load_manifest(manifest_dir)
    effective = _effective_prefill(manifest)
    return jsonify(
        {
            "ok": True,
            "doc_id": doc_id,
            "prefill": manifest.get("prefill"),
            "user_overrides": manifest.get("user_overrides") or {},
            "effective": effective,
            "language": manifest.get("language"),
            "generated_at": manifest.get("prefill_generated_at"),
        }
    )


@library_ingest_bp.post("/llm/plan/<doc_id>")
def llm_plan(doc_id: str):
    fs_config = _resolve_fs_config()
    try:
        parse_doc_id(doc_id)
    except ValueError:
        return jsonify({"error": "invalid_doc_id"}), 400

    started_at = time.perf_counter()
    LLM_PLAN_COUNTERS["requested"] += 1
    LOGGER.info("llm_plan_requested", extra={"doc_id": doc_id})

    with _doc_lock(fs_config, doc_id):
        manifest_dir, manifest = _load_manifest_entry(doc_id, fs_config)
    if not manifest:
        LLM_PLAN_COUNTERS["not_found"] += 1
        return jsonify({"error": "not_found"}), 404

    state = str(manifest.get("state") or "").strip().lower()
    if state and state != "done":
        LLM_PLAN_COUNTERS["invalid_state"] += 1
        return jsonify({"error": "invalid_state", "state": manifest.get("state")}), 409

    artifact_dir = doc_id_to_fs_path(fs_config.extracted_root, doc_id, shard=fs_config.shard)

    with _doc_lock(fs_config, doc_id):
        append_manifest_history(manifest_dir, {"event": "llm_plan_requested"})

    segments = _read_segments(doc_id, fs_config)
    if not segments:
        LLM_PLAN_COUNTERS["not_found"] += 1
        return jsonify({"error": "not_found"}), 404
    options = request.get_json(silent=True) or {}
    pseudonymize = bool(options.get("pseudonymize", True))
    keep_prompt_clear = bool(options.get("keep_prompt_clear", False))
    try:
        generation = propose_notions(
            doc_id,
            segments,
            pseudonymize=pseudonymize,
            keep_prompt_clear=keep_prompt_clear,
        )
    except LibraryLLMUpstreamError as exc:
        LLM_PLAN_COUNTERS["upstream_failure"] += 1
        return jsonify({"error": "upstream_failure", "message": str(exc)}), 502
    except LibraryLLMError as exc:
        LLM_PLAN_COUNTERS["invalid"] += 1
        return jsonify({"error": "invalid_plan", "message": str(exc)}), 422

    parse_result = parse_llm_plan_relaxed(generation.raw_content)
    parse_errors = list(dict.fromkeys(parse_result.errors))
    preview = parse_result.preview or generation.preview()
    reason = parse_result.reason

    if generation.has_tool_calls and not generation.raw_content.strip():
        parse_errors.append("empty_content_with_tool_calls")
        preview = generation.preview()
        reason = reason or "non_conforming_output"
        parse_result = RelaxedParseResult(False, None, parse_errors, preview, reason=reason)

    if (not parse_result.ok or parse_result.data is None) and generation.raw_content.strip():
        try:
            repaired_payload = lenient_json_loads(generation.raw_content)
        except ValueError as repair_error:
            parse_errors.append(f"lenient_json:{repair_error}")
        else:
            parse_errors.append("lenient_json_repair_applied")
            preview = generation.preview()
            parse_result = RelaxedParseResult(True, repaired_payload, parse_errors, preview, reason=None)
            reason = None

    parse_errors = list(dict.fromkeys(parse_errors))

    if not parse_result.ok or parse_result.data is None:
        reason = reason or "non_conforming_output"
        with _doc_lock(fs_config, doc_id):
            _persist_plan_artifact(
                artifact_dir,
                doc_id,
                generation,
                plan=None,
                quality="degraded",
                reason=reason,
                parse_errors=parse_errors,
                errors=[],
                schema_version=SCHEMA_VERSION,
            )
            append_manifest_history(manifest_dir, {"event": "llm_plan_degraded", "reason": reason})
        LLM_PLAN_COUNTERS["degraded"] += 1
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        LOGGER.info(
            "llm_plan_degraded",
            extra={"doc_id": doc_id, "reason": reason, "duration_ms": duration_ms, "schema_version": SCHEMA_VERSION},
        )
        return jsonify(
            {
                "status": "degraded",
                "quality": "degraded",
                "reason": reason,
                "raw_preview": preview,
                "parse_errors": parse_errors,
                "ok": False,
                "schema_version": SCHEMA_VERSION,
            }
        )

    try:
        plan_payload, quality, schema_version = _validate_plan_schema(parse_result.data, doc_id=doc_id)
    except ValidationError as exc:
        issues: List[str] = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            message = error.get("msg", "invalid")
            issues.append(f"{location}: {message}" if location else message)
        validator_trace = " | ".join(issues)
        why = issues[0] if issues else "invalid_plan_schema"
        with _doc_lock(fs_config, doc_id):
            _persist_plan_artifact(
                artifact_dir,
                doc_id,
                generation,
                plan=parse_result.data,
                quality="degraded",
                reason="invalid_plan_schema",
                parse_errors=parse_errors,
                errors=issues,
                schema_version=SCHEMA_VERSION,
            )
            append_manifest_history(
                manifest_dir,
                {
                    "event": "llm_plan_degraded",
                    "reason": "invalid_plan_schema",
                    "details": {"issues": issues},
                },
            )
        LLM_PLAN_COUNTERS["invalid_schema"] += 1
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        LOGGER.info(
            "llm_plan_degraded",
            extra={
                "doc_id": doc_id,
                "reason": "invalid_plan_schema",
                "duration_ms": duration_ms,
                "schema_version": SCHEMA_VERSION,
                "errors": issues[:3],
            },
        )
        degraded_payload = {
            "status": "degraded",
            "quality": "degraded",
            "reason": "invalid_plan_schema",
            "error": "invalid_plan_schema",
            "parse_errors": parse_errors,
            "raw_preview": preview,
            "ok": False,
            "why": why,
            "validator_trace": validator_trace,
            "schema_version": SCHEMA_VERSION,
            "raw_excerpt_saved": True,
        }
        return jsonify(degraded_payload)

    with _doc_lock(fs_config, doc_id):
        _persist_plan_artifact(
            artifact_dir,
            doc_id,
            generation,
            plan=plan_payload,
            quality=quality,
            reason=None,
            parse_errors=parse_errors,
            errors=[],
            schema_version=schema_version,
        )
        append_manifest_history(
            manifest_dir,
            {"event": "llm_plan_parsed", "quality": quality, "schema_version": schema_version},
        )
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    if quality == "full":
        LLM_PLAN_COUNTERS["ok"] += 1
    else:
        LLM_PLAN_COUNTERS["partial"] += 1
    LOGGER.info(
        "llm_plan_parsed",
        extra={"doc_id": doc_id, "quality": quality, "duration_ms": duration_ms, "schema_version": schema_version},
    )

    return jsonify(
        {
            "status": "ok",
            "ok": True,
            "quality": quality,
            "plan": plan_payload,
            "schema_version": schema_version,
        }
    )


@library_ingest_bp.post("/review/commit")
def commit_review():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_request"}), 400
    doc_id = payload.get("doc_id")
    if not isinstance(doc_id, str):
        return jsonify({"error": "invalid_doc_id"}), 400
    try:
        parse_doc_id(doc_id)
    except ValueError:
        return jsonify({"error": "invalid_doc_id"}), 400
    fs_config = _resolve_fs_config()
    notions_path = _notions_path(fs_config)
    notions_input = payload.get("notions", [])
    if not isinstance(notions_input, list) or not notions_input:
        return jsonify({"error": "invalid_request"}), 400

    indexed = []
    for entry in notions_input:
        canonical = entry.get("notion") or entry.get("canonical")
        if not isinstance(canonical, dict):
            continue
        notion_id = canonical.get("notion_id")
        if not notion_id:
            continue
        canonical = dict(canonical)
        canonical.setdefault("kind", "notion")
        canonical["version"] = _next_notion_version(notion_id, fs_config)
        canonical.setdefault("priority", 0.0)
        canonical.setdefault("source_contributions", [])
        canonical.setdefault("allowed_for_autosuggest_pre", canonical.get("autosuggest_pre", True))
        canonical.setdefault("allowed_for_autosuggest_post", canonical.get("autosuggest_post", True))
        canonical["updated_at"] = datetime.now(timezone.utc).isoformat()
        canonical["doc_id"] = doc_id
        contributions = entry.get("contributions", [])
        contribution_ids: List[str] = []
        for index, contribution in enumerate(contributions, start=1):
            if not isinstance(contribution, dict):
                continue
            contribution = dict(contribution)
            contribution.setdefault("kind", "contribution")
            contribution.setdefault("notion_id", notion_id)
            contribution.setdefault("doc_id", doc_id)
            contribution_id = contribution.get("contribution_id") or f"{notion_id}::{doc_id}::{index}"
            contribution["contribution_id"] = contribution_id
            contribution.setdefault("tags", canonical.get("canonical_tags", []))
            contribution_ids.append(contribution_id)
            _append_jsonl(notions_path, contribution)
        if contribution_ids and isinstance(canonical.get("source_contributions"), list):
            canonical["source_contributions"] = list(dict.fromkeys(canonical["source_contributions"] + contribution_ids))

        _append_jsonl(notions_path, canonical)

        index_notion(canonical)
        indexed.append({"notion_id": notion_id, "version": canonical["version"]})

    return jsonify({"ok": True, "indexed": indexed})


@library_ingest_bp.get("/search")
def library_search():
    query = (request.args.get("q") or "").strip()
    mode = (request.args.get("mode") or "pre").lower()
    mode = mode if mode in {"pre", "post"} else "pre"
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        limit = 10
    tags = _parse_list(request.args.get("tags"))
    evidence = _parse_list(request.args.get("evidence"))
    years = _parse_list(request.args.get("year")) or _parse_list(request.args.get("years"))
    filters = {}
    if tags:
        filters["tags"] = tags
    if evidence:
        filters["evidence"] = evidence
    if years:
        filters["year"] = years
    results = hybrid_search(query, mode=mode, filters=filters, limit=limit)
    return jsonify({"ok": True, "results": results, "query": query, "mode": mode})


@library_ingest_bp.get("/notion/<notion_id>")
def notion_detail(notion_id: str):
    entries = _load_jsonl(_notions_path(_resolve_fs_config()))
    canonical: Dict[str, object] | None = None
    max_version = -1
    contributions: List[Dict[str, object]] = []
    for entry in entries:
        if entry.get("notion_id") != notion_id:
            continue
        if entry.get("kind") == "notion":
            version = int(entry.get("version", 0))
            if version >= max_version:
                canonical = entry
                max_version = version
        elif entry.get("kind") == "contribution":
            contributions.append(entry)
    if canonical is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify({"ok": True, "notion": canonical, "contributions": contributions})


def _library_root() -> Path:
    return _resolve_fs_config().library_root


def _load_jsonl_entries(path: Path) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                results.append(payload)
    except OSError as exc:
        LOGGER.warning("Lecture impossible de %s : %s", path, exc)
    return results


def _search_fallback_documents(root: Path, query: str, limit: int) -> List[Dict[str, object]]:
    matches: List[Dict[str, object]] = []
    lower_query = query.lower()
    for pattern in ("*.md", "*.txt"):
        for path in sorted(root.rglob(pattern)):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            snippet = text.strip().splitlines()[0:3]
            snippet_text = " ".join(snippet)[:240]
            if lower_query and lower_query not in text.lower():
                continue
            matches.append(
                {
                    "title": path.stem.replace("_", " ").title(),
                    "author": None,
                    "year": None,
                    "snippet": snippet_text,
                    "path": str(path.relative_to(root)),
                }
            )
            if len(matches) >= limit:
                return matches
    return matches


@bp.get("/search")
def search_library():
    query = (request.args.get("q") or "").strip()
    try:
        limit = int(request.args.get("limit", "8"))
    except ValueError:
        limit = 8
    limit = max(1, min(limit, 50))

    library_root = _library_root()
    jsonl_path = library_root / "library_index.jsonl"
    source = "demo"
    items: List[Dict[str, object]] = []

    if jsonl_path.exists():
        entries = _load_jsonl_entries(jsonl_path)
        lower_query = query.lower()
        for entry in entries:
            title = str(entry.get("title", ""))
            snippet = str(entry.get("snippet", ""))
            haystack = " ".join([title.lower(), snippet.lower()])
            if lower_query and lower_query not in haystack:
                continue
            items.append(
                {
                    "title": title,
                    "author": entry.get("author"),
                    "year": entry.get("year"),
                    "snippet": snippet,
                    "path": entry.get("path"),
                }
            )
            if len(items) >= limit:
                break
        source = "jsonl"
    else:
        items = _search_fallback_documents(library_root, query, limit)

    LOGGER.info(
        "Library search : %s résultat(s) pour '%s' (source %s)",
        len(items),
        query or "*",
        source,
    )
    return jsonify({"ok": True, "items": items, "source": source, "query": query, "limit": limit})


@library_ingest_bp.get("/health")
def library_healthcheck():
    """Vérifie l'accessibilité minimale des dossiers de la bibliothèque.

    Cette route est volontairement simple pour le scaffolding initial :
    elle garantit que les dossiers requis existent et retourne un statut
    explicite. Les contrôles seront enrichis lors des commits suivants.
    """

    layout = ensure_index_layout()
    raw_dir = Path("library/raw_pdfs")
    extracted_dir = Path("library/extracted")
    logs_dir = Path("library/logs")
    for folder in (raw_dir, extracted_dir, logs_dir):
        folder.mkdir(parents=True, exist_ok=True)

    payload = {
        "ok": True,
        "paths": {
            "raw_pdfs": str(raw_dir.resolve()),
            "extracted": str(extracted_dir.resolve()),
            "index_root": str(layout["root"].resolve()),
            "vectors": str(layout["vectors"].resolve()),
            "logs": str(logs_dir.resolve()),
        },
        "message": "Scaffolding OK",
    }
    return jsonify(payload)


__all__ = ["bp", "library_ingest_bp", "LLM_PLAN_COUNTERS"]
