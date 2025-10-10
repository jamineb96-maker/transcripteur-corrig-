"""
post_v1.py
---------------

This module exposes a minimal post‑session API compatible with the legacy
behaviour described by the psychopraticien.  It is intentionally
lightweight: rather than relying on the new research/prompt pipeline
implemented elsewhere in the project, it provides three endpoints
(`/transcribe`, `/prepare_plan` and `/prepare_prompt`) which mirror
those of the historical `server.py`.  The intent is to offer a stable
contract to the front‑end without pulling in any external services.

The implementation here is deliberately pragmatic.  When audio is
uploaded the file is passed through the existing :class:`Transcriber`
class to produce a full transcript and a list of segments.  Plans,
historique and prompts are derived from the transcript in a simple
manner: the plan echoes the transcript with a maximum of 500
characters, chapters are emitted as a single item covering the whole
recording, and the prompt concatenates the provided elements into a
readable summary.  These behaviours should be replaced with calls to
more sophisticated routines if available, but for now they ensure
completeness and idempotence.

The blueprint registers its routes under the prefix ``/api/post_v1`` to
avoid clashing with existing post‑session routes.  To activate it,
import and register :data:`post_v1_bp` within your Flask application.
"""

from __future__ import annotations

import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

try:
    # The transcriber is part of the existing application and provides
    # deterministic chunked transcription using ffmpeg/ffprobe when
    # available.  Importing it here avoids any dependency on the legacy
    # server code.
    from server.transcriber import Transcriber
except Exception:
    Transcriber = None  # type: ignore


def _simple_auth() -> bool:
    """Return ``True`` if the request is authorised.

    The blueprint uses a very simple bearer token mechanism: if the
    environment variable ``API_AUTH_TOKEN`` is defined then every
    incoming request must include an ``Authorization`` header of the
    form ``Bearer <token>``.  When no token is configured the check
    always passes.
    """
    api_token = os.getenv("API_AUTH_TOKEN") or os.getenv("API_TOKEN")
    if not api_token:
        return True
    auth_header = request.headers.get("Authorization", "")
    parts: List[str] = auth_header.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        provided = parts[1].strip()
        # Use hmac.compare_digest if available for constant‑time compare
        try:
            import hmac
            return hmac.compare_digest(provided, api_token)
        except Exception:
            return provided == api_token
    return False


post_v1_bp = Blueprint("post_v1", __name__, url_prefix="/api/post_v1")


def _extract_multipart_audio() -> Tuple[Optional[Path], Optional[str]]:
    """Extract an uploaded audio file from a multipart request.

    Returns a tuple ``(path, base_name)``.  The file is saved to a
    temporary directory (``/tmp``) and the caller is responsible for
    removing it when finished.  If no suitable file is present the
    function returns ``(None, None)``.
    """
    # Look for common field names
    for field in ("audio", "file", "upload", "audio_file", "audio[]", "files[]"):
        file = request.files.get(field)
        if file and getattr(file, "filename", None):
            filename = file.filename or "audio"
            # Create a temporary path in /tmp; ensure unique name
            suffix = Path(filename).suffix or ".bin"
            temp_path = Path("/tmp") / f"post_v1_{datetime.utcnow().timestamp():.0f}{suffix}"
            try:
                file.save(temp_path)
            except Exception:
                return None, None
            base_name = Path(filename).stem
            return temp_path, base_name
    return None, None


@post_v1_bp.route("/transcribe", methods=["POST"])
def transcribe() -> Any:
    """Handle audio transcription and basic plan construction.

    The endpoint accepts either a multipart/form‑data request with an
    ``audio`` file or a JSON payload containing a ``transcript`` string.
    It returns a JSON object with the following keys:

    - ``transcript``: full transcript text
    - ``plan``: a simple textual plan (first 500 characters of the transcript)
    - ``prenom``: optional patient name provided by the caller
    - ``base_name``: the base filename without extension if a file was uploaded
    - ``date``: current UTC date in ``YYYY‑MM‑DD`` format
    - ``register``: language register (defaults to ``vous``)
    - ``ok``: always ``True`` for backwards compatibility

    If an API token is configured and the caller is unauthorised a
    ``401`` response is returned.
    """
    if not _simple_auth():
        return jsonify({"error": "Unauthorized"}), 401
    transcript = ""
    base_name: str = ""
    # Prefer multipart file upload
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        path, base = _extract_multipart_audio()
        base_name = base or ""
        if path and Transcriber is not None:
            try:
                tr = Transcriber()
                data = tr.transcribe_audio(path)
                transcript = str(data.get("text") or "").replace("\r\n", "\n").strip()
            except Exception as exc:
                # If transcription fails, include the exception message in the transcript
                transcript = f"[Transcription échouée] {exc}"
            finally:
                try:
                    path.unlink()
                except Exception:
                    pass
    # JSON fallbacks: accept explicit transcript
    payload: Dict[str, Any] = {}
    if not transcript:
        try:
            payload = request.get_json(silent=True) or {}
        except Exception:
            payload = {}
        transcript = str(payload.get("transcript") or "").replace("\r\n", "\n").strip()
    # Construct a naive plan: first 500 characters of the transcript
    plan = transcript[:500] if transcript else ""
    # Extract metadata
    prenom: str = ""
    register: str = "vous"
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        form_data = request.form.to_dict(flat=True)
        prenom = form_data.get("prenom") or form_data.get("patient") or ""
        register = form_data.get("register") or "vous"
    else:
        if isinstance(payload, dict):
            prenom = payload.get("prenom") or payload.get("patient") or ""
            register = payload.get("register") or "vous"
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    result = {
        "transcript": transcript,
        "plan": plan,
        "prenom": prenom,
        "base_name": base_name,
        "date": date_str,
        "register": register,
        "ok": True,
    }
    return jsonify(result)


@post_v1_bp.route("/prepare_plan", methods=["POST"])
def prepare_plan() -> Any:
    """Construct a simple plan, historique and chapters from a transcript.

    The request body must be JSON and may contain ``transcript``,
    ``plan_text``, ``historique``, ``prenom`` and ``register``.  The
    returned JSON object contains:

    - ``plan_text``: the plan (use existing ``plan_text`` if provided or
      derive from ``transcript``)
    - ``historique``: echoed from the input or an empty string
    - ``chapters``: a single chapter covering the entire session
    - ``prenom``: echoed from the input
    - ``register``: echoed from the input or ``vous``
    - ``ok``: always ``True``
    """
    if not _simple_auth():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}
    transcript = str(payload.get("transcript") or "").replace("\r\n", "\n").strip()
    plan_text = str(payload.get("plan_text") or "").strip()
    historique = str(payload.get("historique") or "").strip()
    prenom = payload.get("prenom") or payload.get("patient") or ""
    register = payload.get("register") or "vous"
    # If no plan provided, derive a naive one from the transcript
    if not plan_text and transcript:
        plan_text = transcript[:500]
    # Build a single chapter spanning the entire transcript
    chapters: List[Dict[str, Any]] = []
    if transcript:
        chapters.append({"t0": 0.0, "t1": None, "title": "Séance", "bullets": []})
    result = {
        "plan_text": plan_text or "",
        "historique": historique or "",
        "chapters": chapters,
        "prenom": prenom,
        "register": register,
        "ok": True,
    }
    return jsonify(result)


@post_v1_bp.route("/prepare_prompt", methods=["POST"])
def prepare_prompt() -> Any:
    """Produce a final prompt from the provided plan and transcript.

    This endpoint accepts a JSON body with at least a ``transcript``
    field.  Optional fields include ``plan_text`` and ``historique``.
    The response contains a single ``prompt`` key with a human‑readable
    summary composed of the transcript and plan.  A ``stage`` query
    parameter is accepted for compatibility but ignored.
    """
    if not _simple_auth():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        payload = {}
    stage = (request.args.get("stage") or "final").lower()
    transcript = str(payload.get("transcript") or "").replace("\r\n", "\n").strip()
    plan_text = str(payload.get("plan_text") or payload.get("plan") or "").strip()
    historique = str(payload.get("historique") or "").strip()
    prenom = payload.get("prenom") or payload.get("patient") or ""
    register = payload.get("register") or "vous"
    # Synthesize a rudimentary prompt
    parts: List[str] = []
    if prenom:
        parts.append(f"Séance avec {prenom}")
    if plan_text:
        parts.append("Résumé clinique:\n" + plan_text)
    elif transcript:
        parts.append("Extrait de la séance:\n" + transcript[:1000])
    if historique:
        parts.append("Historique:\n" + historique)
    prompt = "\n\n".join(part for part in parts if part)
    if not prompt:
        prompt = transcript[:1000] or ""
    return jsonify({"prompt": prompt, "ok": True})