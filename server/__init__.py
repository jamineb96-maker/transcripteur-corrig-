"""
Main Flask application for the post‑session transcription and summarisation service.

This module exposes a minimal API that is agnostic to the front‑end.  It focuses
on reliability, idempotence and clear contracts between the research and final
prompt stages.  The design draws from the specification provided by the
psychopraticien user: chunks are processed deterministically, transcripts are
deduplicated, and artefacts are persisted in a predictable directory tree.

The Flask application is defined in :func:`create_app` to ease testing.  When
executed as a script (``python -m server``) it will run a development server.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request, send_file, render_template

from .transcriber import Transcriber, Segment
from .pipeline import ResearchPipeline, FinalPipeline

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

DEFAULT_UPLOAD_DIR = os.environ.get("UPLOAD_DIR") or "instance/uploads"
DEFAULT_ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR") or "instance/archives"


def ensure_dir(path: Path) -> None:
    """Ensure that ``path`` exists and is a directory.

    Parameters
    ----------
    path : Path
        The directory to create if missing.
    """
    path.mkdir(parents=True, exist_ok=True)


def idempotency_key_for_audio(file_path: Path, params: Dict[str, Any]) -> str:
    """Compute a deterministic idempotency key based on audio bytes and parameters.

    The key is a SHA256 hash of the concatenation of the file contents and the
    JSON serialisation of the parameters.  Only stable keys (strings, numbers,
    booleans) are considered when computing the hash.

    Parameters
    ----------
    file_path : Path
        The path to the uploaded audio file.
    params : Dict[str, Any]
        The parameters used for transcription (e.g. chunk length, overlap).

    Returns
    -------
    str
        The hexadecimal SHA256 digest.
    """
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    # normalise params by sorting keys and converting values to JSON
    filtered = {k: v for k, v in params.items() if isinstance(v, (str, int, float, bool))}
    encoded = json.dumps(filtered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    h.update(encoded)
    return h.hexdigest()


def create_app(upload_dir: Optional[str] = None, archive_dir: Optional[str] = None) -> Flask:
    """Factory to create a configured Flask application.

    The application provides the following endpoints:

    - ``POST /transcribe``: accepts either an uploaded audio file or a raw
      transcript.  If an audio file is provided it is chunked and transcribed
      deterministically.  The response contains the full transcript and the
      individual segments with their timecodes.
    - ``POST /prepare_prompt?stage=research``: constructs an evidence sheet,
      critical commentary, repère suggestions and a simple chaptering of the
      transcript.
    - ``POST /prepare_prompt?stage=final``: consumes the research payload and
      produces a plan, an analysis and a formatted mail.
    - ``POST /post_session``: a convenience endpoint that orchestrates
      transcription → research → final in one call and persists all artefacts.
    - ``GET /artifacts/<path:rel_path>``: serves persisted artefacts from the
      archive directory.

    Parameters
    ----------
    upload_dir : Optional[str]
        Base directory where uploaded audio files are stored.  If ``None`` the
        value of ``UPLOAD_DIR`` from the environment or ``instance/uploads``
        is used.
    archive_dir : Optional[str]
        Base directory where session artefacts are persisted.  If ``None`` the
        value of ``ARCHIVE_DIR`` from the environment or ``instance/archives``
        is used.

    Returns
    -------
    Flask
        A configured Flask application instance.
    """
    # Configure Flask to serve static files from the accompanying client directory
    client_dir = Path(__file__).resolve().parents[1] / "client"
    app = Flask(__name__, static_folder=str(client_dir), static_url_path="/static")
    app.json_sort_keys = False

    # compute directories
    upload_base = Path(upload_dir or DEFAULT_UPLOAD_DIR)
    archive_base = Path(archive_dir or DEFAULT_ARCHIVE_DIR)
    ensure_dir(upload_base)
    ensure_dir(archive_base)

    # create service instances
    transcriber = Transcriber()
    research_pipeline = ResearchPipeline()
    final_pipeline = FinalPipeline()

    def json_response(data: Any, status: int = 200):
        if not isinstance(data, (dict, list)):
            data = {"message": data}
        resp = jsonify(data)
        resp.status_code = status
        return resp

    def handle_error(msg: str, code: int = 400):
        return json_response({"ok": False, "message": msg}, status=code)

    def persist_artifact(session_dir: Path, filename: str, content: bytes | str) -> str:
        session_dir.mkdir(parents=True, exist_ok=True)
        file_path = session_dir / filename
        if isinstance(content, str):
            file_path.write_text(content, encoding="utf-8")
        else:
            file_path.write_bytes(content)
        rel = file_path.relative_to(archive_base).as_posix()
        return rel

    def get_session_dir(meta: Dict[str, Any]) -> Path:
        """Compute the directory where artefacts for this session should live.

        The path is ``archive_base/<patient>/<session_id>`` where ``session_id``
        is the idempotency key if available, otherwise a timestamped UUID.
        """
        patient = (meta.get("patient") or meta.get("prenom") or "_global").strip() or "_global"
        patient = patient.replace("/", "_")
        session_id = meta.get("session_id") or uuid.uuid4().hex
        return archive_base / patient / session_id

    @app.post("/transcribe")
    def transcribe_route():
        """Handle transcription requests.

        The request must be JSON containing either a ``transcript`` field or an
        ``audio`` field encoded as a data URL (e.g. ``data:audio/mpeg;base64,...``).
        Alternatively, a multipart/form‑data request may include an ``audio`` file.

        An idempotency key can be supplied in ``options.idempotency_key`` to
        guarantee identical outputs for the same input.  When not provided and
        an audio file is sent, a key is computed automatically.

        Returns
        -------
        json
            A JSON object containing ``ok``, the full ``transcript``, a list
            of ``segments`` (each with ``t`` and ``text``), the ``duration``
            in seconds, the ``text_sha256`` and ``text_len``.
        """
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            audio_file = request.files.get("audio")
            if not audio_file:
                return handle_error("Fichier audio requis.")
            filename = audio_file.filename or "audio"
            temp_path = upload_base / f"{uuid.uuid4().hex}_{filename}"
            audio_file.save(temp_path)
            params = {
                "chunk_seconds": int(request.form.get("chunk_seconds") or 120),
                "overlap_seconds": int(request.form.get("overlap_seconds") or 4),
            }
            idem_key = request.form.get("idempotency_key")
            key = idem_key or idempotency_key_for_audio(temp_path, params)
            transcript_data = transcriber.transcribe_audio(temp_path, **params)
            # remove temporary file
            try:
                temp_path.unlink()
            except Exception:
                pass
        else:
            try:
                payload = request.get_json(force=True) or {}
            except Exception:
                return handle_error("Requête JSON invalide.")
            if "transcript" in payload:
                text = str(payload.get("transcript") or "").replace("\r\n", "\n")
                segments = []  # type: List[Dict[str, Any]]
                duration = None
                key = hashlib.sha256(text.encode("utf-8")).hexdigest()
                transcript_data = {
                    "text": text,
                    "segments": segments,
                    "duration": duration,
                }
            elif "audio" in payload:
                # Expect a data URL, e.g. data:audio/mpeg;base64,AAA...
                import base64
                data_url = str(payload.get("audio") or "")
                if not data_url.startswith("data:"):
                    return handle_error("Données audio invalides. Attendu un data URL.")
                try:
                    header, b64data = data_url.split(",", 1)
                except ValueError:
                    return handle_error("Données audio invalides.")
                binary = base64.b64decode(b64data, validate=True)
                suffix = header.split("/")[1].split(";")[0]
                temp_path = upload_base / f"{uuid.uuid4().hex}.{suffix}"
                temp_path.write_bytes(binary)
                params = payload.get("options") or {}
                chunk_sec = int(params.get("chunk_seconds") or 120)
                overlap_sec = int(params.get("overlap_seconds") or 4)
                key = params.get("idempotency_key") or idempotency_key_for_audio(temp_path, {"chunk_seconds": chunk_sec, "overlap_seconds": overlap_sec})
                transcript_data = transcriber.transcribe_audio(temp_path, chunk_seconds=chunk_sec, overlap_seconds=overlap_sec)
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            else:
                return handle_error("Aucun champ 'transcript' ou 'audio' fourni.")
        full_text = transcript_data.get("text", "")
        segments = [
            {"t": [seg.start, seg.end], "text": seg.text}
            for seg in transcript_data.get("segments", [])
        ]
        duration = transcript_data.get("duration")
        sha256 = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
        meta = {"ok": True, "transcript": full_text, "segments": segments, "duration": duration, "text_sha256": sha256, "text_len": len(full_text), "session_id": key}
        return json_response(meta)

    @app.post("/prepare_prompt")
    def prepare_prompt_route():
        """Prepare a prompt either for the research or final stage.

        The query parameter ``stage`` must be ``research`` or ``final``.

        For the research stage, the request body must contain at least ``transcript``.
        Optional fields: ``prenom``, ``base_name``, ``date``, ``register``.

        For the final stage, the request body must be the JSON object returned by
        the research stage augmented with any additional constraints (e.g.
        maximum length).
        """
        stage = (request.args.get("stage") or "").strip().lower()
        try:
            payload = request.get_json(force=True) or {}
        except Exception:
            return handle_error("Requête JSON invalide.")
        if stage == "research":
            transcript = str(payload.get("transcript") or "")
            if not transcript:
                return handle_error("Champ 'transcript' requis pour la phase de research.")
            prenom = payload.get("prenom") or payload.get("patient")
            base_name = payload.get("base_name") or payload.get("label")
            date_label = payload.get("date") or datetime.utcnow().strftime("%Y-%m-%d")
            register = payload.get("register") or "vous"
            result = research_pipeline.run(
                transcript, prenom=prenom, base_name=base_name, date=date_label, register=register
            )
            return json_response(result)
        elif stage == "final":
            if not isinstance(payload, dict):
                return handle_error("Corps JSON invalide pour la phase finale.")
            result = final_pipeline.run(payload)
            return json_response(result)
        else:
            return handle_error("Paramètre 'stage' inconnu ou manquant.", code=400)

    @app.post("/post_session")
    def post_session_route():
        """High‑level endpoint orchestrating the entire post‑session pipeline.

        Accepts either an ``audio`` file (multipart or data URL) or an existing
        ``transcript``.  Additional metadata (``prenom``, ``base_name``, ``date``,
        ``register``) are propagated to the research and final stages.  The
        returned JSON object contains the plan, analysis, mail and a map of
        persisted artefact paths relative to ``ARCHIVE_DIR``.
        """
        # Accept both multipart and JSON
        transcript = None
        meta: Dict[str, Any] = {}
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            form = request.form.to_dict(flat=True)
            for key in ("prenom", "base_name", "date", "register", "patient"):
                if key in form and form[key]:
                    meta[key] = form[key]
            if "audio" in request.files:
                audio_file = request.files["audio"]
                filename = audio_file.filename or "audio"
                temp_path = upload_base / f"{uuid.uuid4().hex}_{filename}"
                audio_file.save(temp_path)
                params = {
                    "chunk_seconds": int(form.get("chunk_seconds") or 120),
                    "overlap_seconds": int(form.get("overlap_seconds") or 4),
                }
                idem_key = form.get("idempotency_key") or idempotency_key_for_audio(temp_path, params)
                meta["session_id"] = idem_key
                trans_data = transcriber.transcribe_audio(temp_path, **params)
                transcript = trans_data["text"]
                segments = trans_data["segments"]
                duration = trans_data["duration"]
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            elif form.get("transcript"):
                transcript = str(form.get("transcript")).replace("\r\n", "\n")
                segments = []
                duration = None
                meta["session_id"] = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
            else:
                return handle_error("Champ 'audio' ou 'transcript' requis.")
        else:
            try:
                payload = request.get_json(force=True) or {}
            except Exception:
                return handle_error("Requête JSON invalide.")
            for key in ("prenom", "base_name", "date", "register", "patient"):
                if key in payload and payload[key]:
                    meta[key] = payload[key]
            if "transcript" in payload:
                transcript = str(payload.get("transcript") or "").replace("\r\n", "\n")
                segments = []
                duration = None
                meta["session_id"] = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
            elif "audio" in payload:
                import base64
                data_url = str(payload.get("audio") or "")
                header, b64data = data_url.split(",", 1)
                binary = base64.b64decode(b64data, validate=True)
                suffix = header.split("/")[1].split(";")[0]
                temp_path = upload_base / f"{uuid.uuid4().hex}.{suffix}"
                temp_path.write_bytes(binary)
                params = payload.get("options") or {}
                chunk_sec = int(params.get("chunk_seconds") or 120)
                overlap_sec = int(params.get("overlap_seconds") or 4)
                idem_key = params.get("idempotency_key") or idempotency_key_for_audio(temp_path, {"chunk_seconds": chunk_sec, "overlap_seconds": overlap_sec})
                meta["session_id"] = idem_key
                trans_data = transcriber.transcribe_audio(temp_path, chunk_seconds=chunk_sec, overlap_seconds=overlap_sec)
                transcript = trans_data["text"]
                segments = trans_data["segments"]
                duration = trans_data["duration"]
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            else:
                return handle_error("Champ 'audio' ou 'transcript' requis.")
        # Stage 1: research
        research_payload = research_pipeline.run(
            transcript,
            prenom=meta.get("prenom"),
            base_name=meta.get("base_name"),
            date=meta.get("date"),
            register=meta.get("register") or "vous",
        )
        # Stage 2: final
        final_payload = final_pipeline.run(research_payload)
        # Persist artefacts
        session_dir = get_session_dir({"patient": meta.get("prenom"), "session_id": meta.get("session_id")})
        artifacts: Dict[str, str] = {}
        artifacts["transcript_txt"] = persist_artifact(session_dir, "transcript.txt", transcript)
        artifacts["segments_json"] = persist_artifact(session_dir, "segments.json", json.dumps([{"t": [seg.start, seg.end], "text": seg.text} for seg in segments], ensure_ascii=False, indent=2))
        artifacts["research_json"] = persist_artifact(session_dir, "research.json", json.dumps(research_payload, ensure_ascii=False, indent=2))
        artifacts["analysis_json"] = persist_artifact(session_dir, "analysis.json", json.dumps(final_payload.get("analysis"), ensure_ascii=False, indent=2))
        artifacts["plan_txt"] = persist_artifact(session_dir, "plan.txt", final_payload.get("plan_markdown") or "")
        artifacts["mail_md"] = persist_artifact(session_dir, "mail.md", final_payload.get("mail_markdown") or "")
        result = {
            "meta": {
                "session_id": meta.get("session_id"),
                "patient": meta.get("prenom") or meta.get("patient"),
                "date": meta.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
                "base_name": meta.get("base_name"),
                "register": meta.get("register") or "vous",
            },
            "plan": final_payload.get("plan_markdown"),
            "analysis": final_payload.get("analysis"),
            "mail": final_payload.get("mail_markdown"),
            "artifacts": artifacts,
        }
        return json_response(result)

    @app.get("/artifacts/<path:rel_path>")
    def get_artifact(rel_path: str):
        """Serve an artefact previously persisted in the archive directory.

        Files are served in a read‑only manner.  Directory traversal outside the
        archive root is prevented by verifying the absolute path.
        """
        target = (archive_base / rel_path).resolve()
        if not str(target).startswith(str(archive_base.resolve())):
            return handle_error("Accès interdit.", 403)
        if not target.exists() or not target.is_file():
            return handle_error("Fichier introuvable.", 404)
        return send_file(str(target), as_attachment=True)

    # ----------------------------------------------------------------------
    # Front‑end routes
    # ----------------------------------------------------------------------
    @app.get("/")
    def index_page():
        """Serve the main HTML page for the SPA with asset versioning."""
        try:
            from server.services.assets import get_asset_version, detect_tab_duplicates
            asset_version = get_asset_version(static_dir=str(client_dir))
            tab_duplicates = detect_tab_duplicates(static_dir=str(client_dir))
        except Exception:
            asset_version = str(int(time.time()))
            tab_duplicates = []
        return render_template(
            "index.html",
            asset_version=asset_version,
            api_base_url="/",
            tab_duplicates=tab_duplicates,
            config=app.config,
        )
    @app.get("/assets/<path:filename>")
    def legacy_assets(filename: str):
        """Compatibility route: serve /assets/* from /static/assets/*."""
        from flask import send_from_directory, jsonify
        from pathlib import Path as _Path
        static_assets = _Path(app.static_folder) / "assets"
        target = static_assets / filename
        if target.exists() and target.is_file():
            return send_from_directory(str(static_assets), filename)
        try:
            return handle_error("Fichier introuvable.", 404)
        except NameError:
            return jsonify({"ok": False, "message": "Fichier introuvable."}), 404



    return app


if __name__ == "__main__":
    # Launch a development server when executed directly.  Use environment
    # variables to override the host/port or directories.
    from argparse import ArgumentParser

    parser = ArgumentParser(description="Post‑session transcription service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--upload-dir", default=DEFAULT_UPLOAD_DIR)
    parser.add_argument("--archive-dir", default=DEFAULT_ARCHIVE_DIR)
    args = parser.parse_args()
    flask_app = create_app(upload_dir=args.upload_dir, archive_dir=args.archive_dir)
    flask_app.run(host=args.host, port=args.port, debug=True)