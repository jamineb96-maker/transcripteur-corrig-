"""Routes pour l'onglet Post‑séance.

Ce module expose un pipeline complet permettant de traiter une séance à
partir d'un fichier audio envoyé par le client.  Le point d'entrée
`/process` orchestre la transcription, l'extraction d'un plan, la
recherche documentaire et la génération du prompt final.
"""

import hashlib
import time
from pathlib import Path

from flask import abort, current_app, jsonify, request, send_file, url_for
from typing import Any, Dict, List, Optional

from server.services.env import is_true

from . import bp
from .logic import (
    _derive_patient_name,
    _should_use_tu,
    compute_plan_artifacts,
    format_plan_text,
    load_recent_history,
    pack_plan_artifacts,
    pack_research_context,
    process_post_session,
    run_prompt_stage,
    run_research_stage,
    summarize_research_for_ui,
    transcribe_audio,
    unpack_plan_artifacts,
    unpack_research_context,
    build_canonical_transcript_text,
)
from .research_engine_v2 import search_evidence as search_evidence_v2


_ERROR_STATUS = {
    'missing_audio': 400,
    'unsupported_audio_format': 415,
    'audio_too_large': 413,
    'corrupted_audio': 422,
    'empty_audio': 422,
    'empty_transcript': 422,
    'transcription_failed': 502,
    'invalid_reperes_count': 422,
    'invalid_reperes_section': 422,
    'duplicate_reperes_title': 422,
    'reperes_too_short': 422,
    'missing_plan': 500,
    'search_failed': 502,
    'invalid_search_limit': 400,
    'empty_plan': 422,
    'invalid_context': 400,
}

_ERROR_MESSAGES = {
    'missing_audio': 'Aucun fichier audio reçu.',
    'unsupported_audio_format': "Format audio non pris en charge (wav, mp3, m4a).",
    'audio_too_large': "Le fichier audio est trop volumineux (50 Mo max).",
    'corrupted_audio': "Le fichier audio semble corrompu ou incomplet.",
    'empty_audio': "Le fichier audio est vide.",
    'empty_transcript': "La transcription n'a produit aucun contenu exploitable.",
    'transcription_failed': "La transcription automatique a échoué après plusieurs tentatives.",
    'invalid_reperes_count': "La section 'Pistes de lecture' doit contenir entre 3 et 6 sous-parties.",
    'invalid_reperes_section': "Chaque repère doit comporter un titre et un développement.",
    'duplicate_reperes_title': "Les titres des repères doivent être distincts.",
    'reperes_too_short': "Chaque repère doit dépasser 120 mots pour rester consistant.",
    'missing_plan': "Le plan n'a pas pu être généré.",
    'search_failed': "La recherche documentaire a échoué.",
    'invalid_search_limit': 'Le paramètre searchLimit doit être un entier.',
    'empty_plan': 'Le plan fourni est vide.',
    'invalid_context': 'Le contexte transmis est invalide.',
}


def _handle_value_error(exc: ValueError):
    code = str(exc) or 'processing_error'
    status = _ERROR_STATUS.get(code, 400)
    message = _ERROR_MESSAGES.get(code, 'Erreur lors du traitement post-séance.')
    return jsonify({'success': False, 'error': code, 'message': message}), status




def _build_research_query(plan: Dict[str, Any]) -> str:
    if not isinstance(plan, dict):
        return ""
    segments: List[str] = []
    overview = plan.get("overview")
    if isinstance(overview, str) and overview.strip():
        segments.append(overview.strip())
    for step in plan.get("steps", [])[:6]:
        if isinstance(step, dict):
            detail = step.get("detail")
            if isinstance(detail, str) and detail.strip():
                segments.append(detail.strip())
    keywords = plan.get("keywords")
    if isinstance(keywords, (list, tuple)):
        segments.append(" ".join(str(value) for value in keywords if value))
    elif isinstance(keywords, str) and keywords.strip():
        segments.append(keywords.strip())
    return " ".join(segments).strip()


def _extract_filter_params(payload: Dict[str, Any]) -> Dict[str, Any]:
    domains: List[str] = []
    min_year_val: Optional[int] = None
    min_evidence: Optional[str] = None

    def _merge(source: Dict[str, Any]) -> None:
        nonlocal domains, min_year_val, min_evidence
        raw_domains = source.get("domains")
        if raw_domains and not domains:
            if isinstance(raw_domains, str):
                domains = [raw_domains]
            elif isinstance(raw_domains, (list, tuple)):
                domains = [str(item) for item in raw_domains if item]
        raw_year = source.get("min_year") or source.get("minYear")
        if raw_year is not None and min_year_val is None:
            try:
                min_year_val = int(raw_year)
            except (TypeError, ValueError):
                min_year_val = None
        raw_level = source.get("min_evidence_level") or source.get("minEvidenceLevel")
        if isinstance(raw_level, str) and not min_evidence:
            min_evidence = raw_level

    filters_candidate = payload.get("filters")
    if isinstance(filters_candidate, dict):
        _merge(filters_candidate)
    research_section = payload.get("research")
    if isinstance(research_section, dict) and isinstance(research_section.get("filters"), dict):
        _merge(research_section["filters"])
    if not domains and isinstance(payload.get("domains"), (list, tuple)):
        domains = [str(item) for item in payload.get("domains", []) if item]
    elif not domains and isinstance(payload.get("domains"), str):
        domains = [payload["domains"]]
    if min_year_val is None:
        raw_year = payload.get("min_year") or payload.get("minYear")
        if raw_year is not None:
            try:
                min_year_val = int(raw_year)
            except (TypeError, ValueError):
                min_year_val = None
    if not min_evidence:
        raw_level = payload.get("min_evidence_level") or payload.get("minEvidenceLevel")
        if isinstance(raw_level, str):
            min_evidence = raw_level
    return {
        "domains": domains,
        "min_year": min_year_val,
        "min_evidence_level": min_evidence,
    }


def _format_hits_for_ui(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted: List[Dict[str, Any]] = []
    for hit in hits:
        pages = ""
        start = hit.get("page_start")
        end = hit.get("page_end")
        if isinstance(start, int) and isinstance(end, int) and start and end:
            pages = f"p. {start}" if start == end else f"p. {start}-{end}"
        formatted.append({
            "title": hit.get("title", ""),
            "summary": hit.get("extract", ""),
            "source": hit.get("authors", ""),
            "pages": pages,
            "score": hit.get("score"),
        })
    return formatted


def _execute_research_v2(
    artifacts: Any,
    transcript: str,
    limit: int,
    filters: Dict[str, Any],
    query_override: Optional[str] = None,
) -> Dict[str, Any]:
    plan = getattr(artifacts, "plan", {}) if artifacts is not None else {}
    if not isinstance(plan, dict):
        plan = {}
    plan_query = _build_research_query(plan)
    candidates = [
        (query_override or "").strip(),
        plan_query,
        transcript.strip(),
    ]
    query = next((candidate for candidate in candidates if candidate), transcript.strip())
    current_app.logger.info("[research] v2=True query='%s'", query)
    hits = search_evidence_v2(
        query,
        domains=filters.get("domains"),
        min_year=filters.get("min_year"),
        min_evidence_level=filters.get("min_evidence_level"),
        k=max(1, limit),
    )
    evidence_sheet_parts = [hit.get("extract", "") for hit in hits if hit.get("extract")]
    evidence_sheet = "\n\n".join(evidence_sheet_parts).strip()
    return {
        "references": hits,
        "lenses_used": [],
        "evidence_sheet": evidence_sheet,
        "critical_sheet": "",
        "points_mail": [],
        "engine": "library_v2",
        "query": query,
        "filters": filters,
    }

def _handle_unexpected_error():
    return (
        jsonify(
            {
                'success': False,
                'error': 'unexpected_error',
                'message': 'Erreur inattendue lors du traitement.',
            }
        ),
        500,
    )


def _extract_segments(payload):
    segments = payload.get('segments') if isinstance(payload, dict) else None
    if isinstance(segments, (list, tuple)):
        return list(segments)
    return None


def _patient_options_from_payload(payload):
    options = {}
    if not isinstance(payload, dict):
        return options
    for key in ('patientName', 'patient', 'tutoiement', 'useTu'):
        if key in payload and payload[key] is not None:
            options[key] = payload[key]
    return options


@bp.get('/ping')
def ping():
    """Permet de tester la disponibilité du blueprint."""
    return jsonify({'success': True, 'data': 'post-pong'})


@bp.post('/process')
def process():
    """Orchestre le traitement complet post-séance."""

    file_key = None
    if 'audio' in request.files:
        file_key = 'audio'
    elif 'file' in request.files:
        file_key = 'file'
    if file_key is None:
        return _handle_value_error(ValueError('missing_audio'))

    audio_file = request.files[file_key]
    # Paramètres optionnels transmis sous forme de champs de formulaire
    options = {}
    raw_limit = request.form.get('searchLimit') or request.form.get('search_limit')
    if raw_limit:
        try:
            options['searchLimit'] = max(1, int(raw_limit))
        except Exception:
            return _handle_value_error(ValueError('invalid_search_limit'))
    for key in ('patientName', 'patient', 'tutoiement', 'useTu', 'debug'):
        if key in request.form:
            options[key] = request.form[key]

    try:
        payload = process_post_session(audio_file, options)
    except ValueError as exc:
        return _handle_value_error(exc)
    except Exception:
        return _handle_unexpected_error()

    return jsonify({'success': True, 'data': payload})


def _transcript_storage_dir() -> Path:
    base = Path(current_app.instance_path) / 'post_session' / 'transcripts'
    base.mkdir(parents=True, exist_ok=True)
    return base


@bp.get('/transcript/<path:filename>')
def get_transcript_file(filename: str):
    """Expose un transcript sauvegardé côté serveur."""

    base_dir = _transcript_storage_dir().resolve()
    candidate = (base_dir / filename).resolve()
    if base_dir not in candidate.parents and candidate != base_dir:
        abort(403)
    if not candidate.exists() or not candidate.is_file():
        abort(404)

    text = candidate.read_text(encoding='utf-8')
    length = len(text)
    sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()

    response = send_file(
        candidate,
        mimetype='text/plain',
        as_attachment=False,
        download_name=candidate.name,
        max_age=0,
    )
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Transcript-Length'] = str(length)
    response.headers['X-Transcript-Sha256'] = sha256
    return response


@bp.post('/transcribe')
def transcribe():
    """Transcrit un fichier audio sans lancer le reste du pipeline."""

    file_key = None
    if 'audio' in request.files:
        file_key = 'audio'
    elif 'file' in request.files:
        file_key = 'file'
    if file_key is None:
        return _handle_value_error(ValueError('missing_audio'))

    audio_file = request.files[file_key]
    try:
        transcript = transcribe_audio(audio_file, retries=3)
    except ValueError as exc:
        return _handle_value_error(exc)
    except Exception:
        return _handle_unexpected_error()

    canonical_text = build_canonical_transcript_text(transcript)
    length = len(canonical_text)
    sha256 = hashlib.sha256(canonical_text.encode('utf-8')).hexdigest()
    fname = f"ps-{int(time.time() * 1000)}-{sha256[:8]}.txt"
    storage_dir = _transcript_storage_dir()
    file_path = storage_dir / fname
    with open(file_path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(canonical_text)

    segments_count = len(transcript.segments or [])
    dur_raw = transcript.metadata.get('dur_raw') if isinstance(transcript.metadata, dict) else None
    last_end = transcript.metadata.get('last_end') if isinstance(transcript.metadata, dict) else None
    coverage = transcript.metadata.get('coverage') if isinstance(transcript.metadata, dict) else None
    chunked = bool(transcript.metadata.get('chunked_fallback')) if isinstance(transcript.metadata, dict) else False

    data = {
        'transcript': transcript.text,
        'segments': transcript.segments,
        'language': transcript.language,
        'duration': transcript.duration,
        'metadata': transcript.metadata,
        'transcript_url': url_for('post_session.get_transcript_file', filename=fname, _external=False),
        'length': length,
        'sha256': sha256,
        'segments_count': segments_count,
        'text_len': length,
        'dur_raw': dur_raw,
        'last_end': last_end,
        'coverage': coverage,
        'chunked_fallback': chunked,
    }
    current_app.logger.info(
        '[ps/transcribe] saved=%s len=%s sha=%s segs=%s dur_raw=%.2f last_end=%.2f coverage=%.2f chunked=%s',
        fname,
        length,
        sha256[:12],
        segments_count,
        dur_raw if dur_raw is not None else -1.0,
        last_end if last_end is not None else 0.0,
        coverage if coverage is not None else -1.0,
        'yes' if chunked else 'no',
    )
    response = jsonify({'success': True, 'ok': True, 'data': data})
    response.headers['X-Transcript-Length'] = str(length)
    response.headers['X-Transcript-Sha256'] = sha256
    return response


@bp.post('/plan')
def build_plan():
    """Génère un plan et les extractions associées à partir d'une transcription."""

    payload = request.get_json(silent=True) or {}
    transcript = (payload.get('transcript') or '').strip()
    if not transcript:
        return _handle_value_error(ValueError('empty_transcript'))

    plan_context_token = payload.get('planContext') or payload.get('plan_context')
    artifacts = None
    if plan_context_token:
        try:
            artifacts = unpack_plan_artifacts(plan_context_token)
        except ValueError:
            return _handle_value_error(ValueError('invalid_context'))

    if artifacts is None:
        plan_override = payload.get('planStructure') or payload.get('plan_structure')
        if not isinstance(plan_override, dict):
            plan_override = None
        plan_text_input = payload.get('planText') or payload.get('plan')
        segments = _extract_segments(payload)
        try:
            artifacts = compute_plan_artifacts(
                transcript,
                segments=segments,
                plan_override=plan_override,
                plan_text=plan_text_input,
            )
        except ValueError as exc:
            return _handle_value_error(exc)
        except Exception:
            return _handle_unexpected_error()

    context_token = pack_plan_artifacts(artifacts)
    data = {
        'plan': format_plan_text(artifacts.plan),
        'structure': artifacts.plan,
        'extractions': {
            'ai_requests': artifacts.ai_requests,
            'contradictions': artifacts.contradictions,
            'objectifs': artifacts.objectives,
            'chapters': artifacts.chapters,
        },
        'chapters': artifacts.chapters,
        'context': context_token,
    }
    return jsonify({'success': True, 'data': data})


@bp.post('/research')
def research():
    """Lance la recherche documentaire de manière indépendante."""

    payload = request.get_json(silent=True) or {}
    transcript = (payload.get('transcript') or '').strip()
    if not transcript:
        return _handle_value_error(ValueError('empty_transcript'))

    plan_context_token = payload.get('planContext') or payload.get('plan_context')
    artifacts = None
    if plan_context_token:
        try:
            artifacts = unpack_plan_artifacts(plan_context_token)
        except ValueError:
            return _handle_value_error(ValueError('invalid_context'))

    if artifacts is None:
        plan_override = payload.get('planStructure') or payload.get('plan_structure')
        if not isinstance(plan_override, dict):
            plan_override = None
        plan_text_input = payload.get('planText') or payload.get('plan')
        segments = _extract_segments(payload)
        try:
            artifacts = compute_plan_artifacts(
                transcript,
                segments=segments,
                plan_override=plan_override,
                plan_text=plan_text_input,
            )
        except ValueError as exc:
            return _handle_value_error(exc)
        except Exception:
            return _handle_unexpected_error()

    patient_hint = payload.get('patientName') or payload.get('patient') or payload.get('patientId')
    history = load_recent_history(str(patient_hint) if patient_hint else None)

    filters = _extract_filter_params(payload)
    limit_value = payload.get('searchLimit') or payload.get('limit')
    limit_override: Optional[int] = None
    if limit_value is not None:
        try:
            limit_override = max(1, int(limit_value))
        except (TypeError, ValueError):
            return _handle_value_error(ValueError('invalid_search_limit'))

    if is_true('RESEARCH_V2'):
        query_override = payload.get('query') or payload.get('searchQuery')
        try:
            research_payload = _execute_research_v2(
                artifacts,
                transcript,
                limit_override or 8,
                filters,
                query_override,
            )
        except Exception:
            return _handle_unexpected_error()
        context_token = pack_research_context(research_payload)
        data = {
            'summary': research_payload.get('evidence_sheet', ''),
            'results': _format_hits_for_ui(research_payload.get('references', [])),
            'references': research_payload.get('references', []),
            'lenses': research_payload.get('lenses_used', []),
            'context': context_token,
            'planContext': pack_plan_artifacts(artifacts),
        }
        return jsonify({'success': True, 'data': data})

    try:
        if limit_override is not None:
            research_payload = run_research_stage(transcript, artifacts, history, limit=limit_override)
        else:
            research_payload = run_research_stage(transcript, artifacts, history)
    except ValueError as exc:
        return _handle_value_error(exc)
    except Exception:
        return _handle_unexpected_error()

    ui_summary = summarize_research_for_ui(research_payload)
    context_token = pack_research_context(research_payload)

    data = {
        'summary': ui_summary['summary'],
        'results': ui_summary['results'],
        'references': research_payload.get('references', []),
        'lenses': research_payload.get('lenses_used', []),
        'context': context_token,
        'planContext': pack_plan_artifacts(artifacts),
    }
    return jsonify({'success': True, 'data': data})


@bp.post('/prompt')
def generate_prompt():
    """Assemble le mail final et le prompt interne."""

    payload = request.get_json(silent=True) or {}
    transcript = (payload.get('transcript') or '').strip()
    if not transcript:
        return _handle_value_error(ValueError('empty_transcript'))

    plan_context_token = payload.get('planContext') or payload.get('plan_context')
    artifacts = None
    if plan_context_token:
        try:
            artifacts = unpack_plan_artifacts(plan_context_token)
        except ValueError:
            return _handle_value_error(ValueError('invalid_context'))

    if artifacts is None:
        plan_override = payload.get('planStructure') or payload.get('plan_structure')
        if not isinstance(plan_override, dict):
            plan_override = None
        plan_text_input = payload.get('planText') or payload.get('plan')
        segments = _extract_segments(payload)
        try:
            artifacts = compute_plan_artifacts(
                transcript,
                segments=segments,
                plan_override=plan_override,
                plan_text=plan_text_input,
            )
        except ValueError as exc:
            return _handle_value_error(exc)
        except Exception:
            return _handle_unexpected_error()

    research_context_token = None
    research_payload = payload.get('research') if isinstance(payload.get('research'), dict) else {}
    if isinstance(research_payload, dict):
        research_context_token = research_payload.get('context') or research_payload.get('contextToken')
    if not research_context_token:
        research_context_token = payload.get('researchContext') or payload.get('research_context')

    if research_context_token:
        try:
            research_result = unpack_research_context(research_context_token)
        except ValueError:
            return _handle_value_error(ValueError('invalid_context'))
    else:
        research_result = None

    patient_options = _patient_options_from_payload(payload)
    patient_name = _derive_patient_name(patient_options, None)
    use_tu = _should_use_tu(patient_options)
    history = load_recent_history(patient_name)

    filters = _extract_filter_params(payload)
    limit_value = payload.get('searchLimit') or (research_payload.get('limit') if isinstance(research_payload, dict) else None)
    limit_override: Optional[int] = None
    if limit_value is not None:
        try:
            limit_override = max(1, int(limit_value))
        except (TypeError, ValueError):
            return _handle_value_error(ValueError('invalid_search_limit'))

    if is_true('RESEARCH_V2'):
        query_override = None
        if isinstance(research_payload, dict):
            query_override = research_payload.get('query') or research_payload.get('searchQuery')
        if not query_override:
            query_override = payload.get('query') or payload.get('searchQuery')
        if research_result is None or research_result.get('engine') != 'library_v2':
            try:
                research_result = _execute_research_v2(
                    artifacts,
                    transcript,
                    limit_override or 8,
                    filters,
                    query_override,
                )
            except Exception:
                return _handle_unexpected_error()
    else:
        try:
            if research_result is None:
                if limit_override is not None:
                    research_result = run_research_stage(transcript, artifacts, history, limit=limit_override)
                else:
                    research_result = run_research_stage(transcript, artifacts, history)
        except ValueError as exc:
            return _handle_value_error(exc)
        except Exception:
            return _handle_unexpected_error()

    try:
        prompt_payload = run_prompt_stage(
            transcript,
            artifacts,
            research_result,
            history,
            patient_name,
            use_tu,
        )
    except ValueError as exc:
        return _handle_value_error(exc)
    except Exception:
        return _handle_unexpected_error()

    data = {
        'prompt': prompt_payload['prompt'],
        'mail': prompt_payload['mail'],
        'reperes': prompt_payload['reperes_sections'],
        'planContext': pack_plan_artifacts(artifacts),
        'researchContext': pack_research_context(research_result),
    }
    return jsonify({'success': True, 'data': data})
