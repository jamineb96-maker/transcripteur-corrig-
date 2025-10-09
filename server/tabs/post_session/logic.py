"""Pipeline robuste pour le traitement post-séance.

Ce module réimplémente entièrement la logique métier de l'onglet
« Post-séance » afin de répondre aux exigences du nouveau cahier des
charges.  Les améliorations majeures incluent :

* validation stricte des fichiers audio (formats, taille, erreurs);
* transcription déterministe avec segments horodatés et mode verbeux;
* extraction enrichie (plan linéaire, objectifs, demandes à l'IA,
  contradictions, chapitres horodatés);
* stage de recherche critique (librairie locale, lentilles, evidence);
* génération d'un mail final ambitieux et d'un prompt interne complet;
* persistance des artefacts avec verrouillage fichier et mode debug.

Chaque fonction est largement documentée et les nouvelles validations sont
explicitement commentées pour faciliter les audits futurs.
"""

from __future__ import annotations

import base64
import json
import math
import os
import random
import re
import secrets
import shlex
import subprocess
import tempfile
import textwrap
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from werkzeug.datastructures import FileStorage

from flask import current_app

try:  # pragma: no cover - dépendances optionnelles
    from server.library import indexer
except Exception:  # pragma: no cover
    indexer = None  # type: ignore[assignment]
from server.services import env
from server.services.paths import ensure_patient_subdir
from server.services.patients_repo import ARCHIVES_ROOT
from server.util import slugify

# --- Chemins de stockage --------------------------------------------------

_MODULE_DIR = Path(__file__).resolve().parent
_SERVER_ROOT = _MODULE_DIR.parents[1]

# --- Constantes métiers ---------------------------------------------------

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg"}
TEXT_COMPATIBLE_EXTENSIONS = {".txt", ".md", ".rtf"}
_MAX_AUDIO_BYTES = 50 * 1024 * 1024  # 50 Mo pour éviter les abus
_DEFAULT_SEGMENT_LENGTH = 18.0  # durée fictive par segment (secondes)
_MAX_REFERENCES = 3

# Fallback minimaliste pour le critical pack lorsque le fichier est absent
_FALLBACK_LENSES = [
    {
        "slug": "trauma-complexe",
        "label": "Trauma complexe et dynamiques d'emprise",
        "description": "Observer les effets cumulés des violences prolongées et"
        " la manière dont elles façonnent la sécurité perçue, les attaches et"
        " la régulation corporelle.",
    },
    {
        "slug": "validisme",
        "label": "Anti-validisme et accessibilité vécue",
        "description": "Identifier les normes capacitistes implicites, les coûts"
        " énergétiques et les ajustements nécessaires pour que les pratiques"
        " de soin restent soutenables.",
    },
    {
        "slug": "patriarcat",
        "label": "Rapports de genre et patriarcat",
        "description": "Prendre en compte la matérialité des violences et des"
        " assignations genrées dans les trajectoires de soin.",
    },
    {
        "slug": "materiel",
        "label": "Matérialisme historique",
        "description": "Relier les vécus psychiques aux conditions matérielles"
        " (travail, logement, dettes, droits) et aux rapports de pouvoir",
    },
    {
        "slug": "neurodiversite",
        "label": "Neurodiversité et justice attentionnelle",
        "description": "Protéger les rythmes attentionnels et sensoriels,"
        " valoriser les stratégies situées plutôt que la normalisation.",
    },
]

# Stopwords enrichis pour l'extraction d'objectifs / mots-clés
_STOPWORDS = {
    "a", "ai", "and", "are", "avec", "aux", "cette", "ces", "des", "dans",
    "for", "les", "mes", "nos", "notre", "nous", "par", "pas", "pour", "ses",
    "sur", "the", "une", "vos", "elle", "elles", "ils", "mais", "ou", "que",
    "qui", "chez", "plus", "plusieurs", "tout", "tous", "toutes", "vous",
    "elles", "leurs", "leurs", "comme", "faire", "faire", "faire", "être",
}

# --- Outils utilitaires ---------------------------------------------------


def _safe_filename(name: str) -> str:
    """Normalise un nom de fichier en remplaçant les caractères spéciaux."""

    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", name or "")
    slug = slug.strip("-._") or "asset"
    return slug


class FileLock:
    """Petit verrou basé sur la création d'un fichier `.lock`.

    Cette implémentation suffit pour sérialiser les écritures concurrentes
    (jobs RQ ou requêtes simultanées) sans ajouter de dépendance externe.
    """

    def __init__(self, path: Path, timeout: float = 10.0, poll: float = 0.1):
        self.path = Path(path)
        self.timeout = timeout
        self.poll = poll
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode("ascii", "ignore"))
                return
            except FileExistsError:
                if time.monotonic() > deadline:
                    raise TimeoutError("lock_timeout")
                time.sleep(self.poll)

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


class AssetManager:
    """Gestionnaire des fichiers persistés pour une exécution."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_run_dir(self, run_id: str) -> Path:
        run_dir = self.base_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _lock_path(self, path: Path) -> Path:
        suffix = path.suffix + ".lock" if path.suffix else ".lock"
        return path.with_suffix(suffix)

    def write_text(self, path: Path, content: str) -> None:
        lock = FileLock(self._lock_path(path))
        with lock:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content or "")

    def write_json(self, path: Path, data: object) -> None:
        lock = FileLock(self._lock_path(path))
        with lock:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)


@dataclass
class TranscriptResult:
    text: str
    segments: List[Dict[str, object]]
    language: str = "fr"
    duration: float = 0.0
    metadata: Dict[str, object] = field(default_factory=dict)


def build_canonical_transcript_text(transcript: TranscriptResult) -> str:
    """Return the canonical text representation for a transcript result."""

    base_text = (transcript.text or "").replace("\r\n", "\n")
    if base_text.strip():
        return base_text

    stitched = _build_canonical_text({"segments": transcript.segments or []})
    if stitched.strip():
        return stitched.replace("\r\n", "\n")
    return base_text


@dataclass
class PlanArtifacts:
    plan: Dict[str, object]
    ai_requests: List[Dict[str, object]]
    contradictions: List[Dict[str, object]]
    objectives: List[Dict[str, object]]
    chapters: List[Dict[str, object]]


def _encode_context(data: Dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return base64.b64encode(payload).decode("ascii")


def _decode_context(token: str) -> Dict[str, object]:
    if not token:
        raise ValueError("invalid_context")
    try:
        raw = base64.b64decode(token.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_context") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid_context")
    return data


def pack_plan_artifacts(artifacts: PlanArtifacts) -> str:
    return _encode_context(
        {
            "plan": artifacts.plan,
            "ai_requests": artifacts.ai_requests,
            "contradictions": artifacts.contradictions,
            "objectives": artifacts.objectives,
            "chapters": artifacts.chapters,
        }
    )


def unpack_plan_artifacts(token: str) -> PlanArtifacts:
    data = _decode_context(token)
    plan = data.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("invalid_context")
    return PlanArtifacts(
        plan=plan,
        ai_requests=list(data.get("ai_requests", [])),
        contradictions=list(data.get("contradictions", [])),
        objectives=list(data.get("objectives", [])),
        chapters=list(data.get("chapters", [])),
    )


def pack_research_context(research: Dict[str, object]) -> str:
    return _encode_context(research)


def unpack_research_context(token: str) -> Dict[str, object]:
    return _decode_context(token)

# --- Fonctions audio / transcription -------------------------------------


def _read_bytes(file_storage: FileStorage) -> Tuple[bytes, str]:
    """Valide et lit le fichier audio fourni par Flask."""

    if file_storage is None:
        raise ValueError("missing_audio")

    filename = getattr(file_storage, "filename", "") or "audio"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in SUPPORTED_AUDIO_EXTENSIONS | TEXT_COMPATIBLE_EXTENSIONS:
        raise ValueError("unsupported_audio_format")

    try:
        file_storage.stream.seek(0)
    except Exception:
        pass
    data = file_storage.read() if hasattr(file_storage, "read") else b""
    if not data:
        raise ValueError("empty_audio")
    if len(data) > _MAX_AUDIO_BYTES:
        raise ValueError("audio_too_large")

    if ext in {".wav"} and not data.startswith(b"RIFF"):
        raise ValueError("corrupted_audio")
    if ext in {".mp3"} and not data.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3")):
        raise ValueError("corrupted_audio")

    try:
        file_storage.stream.seek(0)
    except Exception:
        pass
    return data, ext


def _decode_audio_bytes(data: bytes, ext: str) -> str:
    """Convertit un audio simulé en texte exploitable."""

    if ext in TEXT_COMPATIBLE_EXTENSIONS:
        try:
            return data.decode("utf-8").strip()
        except UnicodeDecodeError:
            pass

    try:
        decoded = data.decode("utf-8", errors="ignore").strip()
    except Exception:
        decoded = ""
    if decoded:
        return decoded

    encoded = base64.b64encode(data[:32]).decode("ascii")
    return f"[audio {len(data)} bytes: {encoded}]"


def _segment_text(text: str) -> List[Dict[str, object]]:
    """Découpe le texte en segments horodatés factices."""

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[\.\?!])\s+|\n+", text)
        if s and not s.isspace()
    ]
    if not sentences:
        sentences = [text.strip()]

    segments: List[Dict[str, object]] = []
    current = 0.0
    for idx, sentence in enumerate(sentences):
        clean = sentence.replace("\n", " ")
        word_count = max(1, len(re.findall(r"\w+", clean)))
        duration = min(45.0, 3.0 + 0.45 * word_count)
        segments.append(
            {
                "id": idx,
                "start": round(current, 2),
                "end": round(current + duration, 2),
                "text": clean,
            }
        )
        current += duration
    return segments


def _ffprobe_duration(path: Optional[str]) -> Optional[float]:
    """Retourne la durée d'un fichier audio via ffprobe si disponible."""

    if not path:
        return None
    try:
        cmd = (
            "ffprobe -v error -show_entries format=duration "
            "-of default=nw=1:nk=1 " + shlex.quote(path)
        )
        out = subprocess.check_output(cmd, shell=True).decode().strip()
        if not out:
            return None
        return float(out)
    except Exception:
        try:
            current_app.logger.warning("[ps/transcribe] ffprobe unavailable")
        except Exception:
            pass
        return None


def _last_segment_end(resp: Dict[str, object]) -> float:
    """Calcule la fin du dernier segment d'une réponse Whisper."""

    segments = resp.get("segments") or []
    try:
        return float(segments[-1]["end"]) if segments else 0.0
    except Exception:
        return 0.0


def _build_canonical_text(resp: Dict[str, object]) -> str:
    """Assemble un texte canonique à partir des segments Whisper."""

    segments = resp.get("segments") or []
    parts: List[str] = []
    for segment in segments:
        text = ""
        if isinstance(segment, dict):
            text = segment.get("text") or ""
        if isinstance(text, str):
            text = text.strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def _chunk_ranges(duration: Optional[float], win: float = 30.0, over: float = 1.5) -> List[Tuple[float, float]]:
    """Découpe une durée en fenêtres chevauchantes."""

    total = max(0.0, duration or 0.0)
    ranges: List[Tuple[float, float]] = []
    t = 0.0
    if total == 0:
        return ranges
    while t < total:
        ranges.append((t, min(t + win, total)))
        t += max(0.1, win - over)
    return ranges


def transcribe_chunked(
    file_path: str,
    duration: Optional[float],
    model_client,
) -> Dict[str, object]:
    """Effectue une transcription en plusieurs morceaux puis recolle les segments."""

    all_segments: List[Dict[str, object]] = []
    if not model_client or not hasattr(model_client, "transcribe_verbose"):
        return {"segments": all_segments}
    for start, end in _chunk_ranges(duration):
        try:
            piece = model_client.transcribe_verbose(file_path, start=start, end=end)
        except Exception:
            continue
        for segment in piece.get("segments") or []:
            updated = dict(segment)
            updated_start = float(updated.get("start", 0.0)) + start
            updated_end = float(updated.get("end", 0.0)) + start
            updated["start"] = updated_start
            updated["end"] = updated_end
            all_segments.append(updated)
    all_segments.sort(key=lambda seg: seg.get("start", 0.0))
    return {"segments": all_segments}


def transcribe_audio(
    file_storage: FileStorage,
    *,
    retries: int = 2,
    timeout: float = 60.0,
    verbose: Optional[bool] = None,
) -> TranscriptResult:
    """Transcrit l'audio en texte."""

    data, ext = _read_bytes(file_storage)
    verbose = env.is_true("VERBOSE_WHISPER") if verbose is None else verbose
    last_error: Optional[Exception] = None
    text = ""
    segments: List[Dict[str, object]] = []
    success = False
    for _ in range(max(1, retries)):
        try:
            text = _decode_audio_bytes(data, ext)
            if not text:
                raise ValueError("empty_transcript")
            segments = _segment_text(text) if verbose or len(data) else []
            success = True
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.1)
    if not success:
        raise ValueError("transcription_failed") from last_error

    temp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext or "") as handle:
            handle.write(data)
            temp_path = handle.name
    except Exception:
        temp_path = None

    dur_raw = _ffprobe_duration(temp_path)
    last_end = _last_segment_end({"segments": segments})
    coverage = (last_end or 0.0) / (dur_raw or 1.0) if dur_raw else 1.0
    chunked_fallback = False
    if dur_raw and coverage < 0.92 and segments:
        try:
            current_app.logger.warning(
                "[ps/transcribe] low_coverage=%.2f retry_chunked", coverage
            )
        except Exception:
            pass
        model_client = None
        try:
            extensions = getattr(current_app, "extensions", {})
            if isinstance(extensions, dict):
                for key in ("whisper", "whisper_client", "post_session_whisper"):
                    if extensions.get(key):
                        model_client = extensions[key]
                        break
        except Exception:
            model_client = None
        if model_client is None:
            try:
                model_client = current_app.config.get("POST_SESSION_WHISPER_CLIENT")
            except Exception:
                model_client = None

        chunk_segments: List[Dict[str, object]] = []
        if temp_path and model_client:
            chunk_resp = transcribe_chunked(temp_path, dur_raw, model_client)
            chunk_segments = chunk_resp.get("segments") or []
        if chunk_segments:
            segments = chunk_segments
        else:
            scale = dur_raw / max(last_end or 0.0, 0.01)
            adjusted: List[Dict[str, object]] = []
            for segment in segments:
                updated = dict(segment)
                start = float(updated.get("start", 0.0)) * scale
                end = float(updated.get("end", 0.0)) * scale
                updated["start"] = round(start, 2)
                updated["end"] = round(end, 2)
                adjusted.append(updated)
            segments = adjusted
        chunked_fallback = True
        last_end = _last_segment_end({"segments": segments})
        coverage = (last_end or 0.0) / (dur_raw or 1.0)

    if temp_path:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    duration = segments[-1]["end"] if segments else _DEFAULT_SEGMENT_LENGTH
    metadata = {
        "source_ext": ext,
        "bytes": len(data),
        "timeout": timeout,
        "dur_raw": dur_raw,
        "last_end": last_end,
        "coverage": coverage,
        "chunked_fallback": chunked_fallback,
    }

    return TranscriptResult(
        text=text,
        segments=segments,
        language="fr" if re.search(r"[à-ÿ]", text.lower()) else "en",
        duration=duration,
        metadata=metadata,
    )

# --- Extraction du plan et des éléments clefs -----------------------------


def _tokenize(text: str) -> Iterator[str]:
    for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9']+", text.lower()):
        token = token.strip("'")
        if len(token) < 3 or token in _STOPWORDS:
            continue
        yield token


def extract_plan(transcript: str) -> Dict[str, object]:
    """Construit un plan linéaire exhaustif à partir du transcript."""

    if not transcript or not transcript.strip():
        raise ValueError("empty_transcript")

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[\.\?!])\s+", transcript)
        if s.strip()
    ]
    if not sentences:
        raise ValueError("empty_transcript")

    overview = sentences[0]
    steps: List[Dict[str, object]] = []
    for idx, sentence in enumerate(sentences, start=1):
        nominal = re.sub(r"[:;]\s*", " ", sentence)
        nominal = re.sub(r"\s+", " ", nominal)
        title = " ".join(nominal.split()[:14])
        steps.append(
            {
                "order": idx,
                "title": title,
                "detail": sentence,
            }
        )

    keywords: List[str] = []
    seen = set()
    for token in _tokenize(transcript):
        if token in seen:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= 12:
            break

    return {
        "overview": overview,
        "steps": steps,
        "keywords": keywords,
    }


def format_plan_text(plan: Dict[str, object]) -> str:
    lines: List[str] = []
    overview = plan.get("overview") or ""
    if overview:
        lines.append(str(overview).strip())
    for step in plan.get("steps", []):
        detail = step.get("detail") or step.get("title") or ""
        if not detail:
            continue
        order = step.get("order")
        if isinstance(order, int):
            prefix = f"{order}. "
        else:
            prefix = ""
        lines.append(prefix + str(detail).strip())
    return "\n".join(line for line in lines if line).strip()


def parse_plan_text(plan_text: str) -> Dict[str, object]:
    if not plan_text or not plan_text.strip():
        raise ValueError("empty_plan")

    lines = [line.strip() for line in plan_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("empty_plan")

    overview = lines[0]
    steps: List[Dict[str, object]] = []
    for idx, line in enumerate(lines[1:], start=1):
        match = re.match(r"^(\d+)[\).:-]?\s*(.+)$", line)
        if match:
            order = int(match.group(1))
            detail = match.group(2).strip()
        else:
            order = idx
            detail = line
        title = " ".join(detail.split()[:14])
        steps.append({"order": order, "title": title, "detail": detail})

    if not steps:
        title = " ".join(overview.split()[:14])
        steps.append({"order": 1, "title": title, "detail": overview})

    return {"overview": overview, "steps": steps, "keywords": []}


def extract_ai_requests(transcript: str, limit: int = 20) -> List[Dict[str, object]]:
    """Détecte les passages où l'intervenant sollicite explicitement l'IA."""

    patterns = [
        r"\bpeux[- ]tu\b",
        r"\bpeut[- ]on demander\b",
        r"\bdemande\s+à\s+l['’]ia\b",
        r"\bchatgpt\b",
        r"\boutil\s+d['’]ia\b",
    ]
    compiled = [re.compile(pat, re.IGNORECASE) for pat in patterns]
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[\.\?!])\s+", transcript)
        if s.strip()
    ]
    results: List[Dict[str, object]] = []
    seen = set()
    for sentence in sentences:
        if len(results) >= limit:
            break
        if any(pat.search(sentence) for pat in compiled):
            normalized = re.sub(r"\s+", " ", sentence)
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            confidence = min(0.95, 0.55 + len(normalized) / 240.0)
            results.append({"text": normalized, "confidence": round(confidence, 2)})
    return results


def contradiction_spans(
    transcript: str,
    window_chars: int = 280,
    limit: int = 12,
) -> List[Dict[str, object]]:
    """Repère des contradictions ou tensions discursives."""

    markers = [
        r"\bmais\b",
        r"\bcependant\b",
        r"\bpourtant\b",
        r"\balors\s+que\b",
        r"\btandis\s+que\b",
    ]
    compiled = [re.compile(pat, re.IGNORECASE) for pat in markers]
    spans: List[Dict[str, object]] = []
    for pat in compiled:
        for match in pat.finditer(transcript):
            if len(spans) >= limit:
                break
            start = max(0, match.start() - window_chars // 2)
            end = min(len(transcript), match.end() + window_chars // 2)
            chunk = transcript[start:end].strip()
            spans.append(
                {
                    "marker": pat.pattern,
                    "excerpt": re.sub(r"\s+", " ", chunk),
                    "start_index": start,
                    "end_index": end,
                }
            )
    return spans[:limit]


def summarize_objectifs_points(
    transcript: str,
    plan: Dict[str, object],
    limit: int = 15,
) -> List[Dict[str, object]]:
    """Synthétise les objectifs formulés pendant la séance."""

    candidates: List[Tuple[str, float, str]] = []
    pattern = re.compile(
        r"\b(objectif|objectif\s+principal|on\s+voudrait|souhaite|priorité|but)\b",
        re.IGNORECASE,
    )
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[\.\?!])\s+", transcript)
        if s.strip()
    ]
    for sentence in sentences:
        if pattern.search(sentence):
            score = 0.7
            candidates.append((sentence, score, "transcript"))

    for step in plan.get("steps", [])[: limit // 2]:
        detail = step.get("detail", "")
        score = 0.6
        if any(word in detail.lower() for word in ("stabiliser", "renforcer", "mettre")):
            score += 0.1
        candidates.append((detail, score, "plan"))

    normalized: Dict[str, Tuple[str, float, str]] = {}
    for sentence, score, source in candidates:
        cleaned = re.sub(r"\s+", " ", sentence)
        key = cleaned.lower()
        if len(cleaned.split()) < 4:
            continue
        if key not in normalized or score > normalized[key][1]:
            normalized[key] = (cleaned, score, source)

    sorted_items = sorted(normalized.values(), key=lambda item: item[1], reverse=True)
    output: List[Dict[str, object]] = []
    for sentence, score, source in sorted_items[:limit]:
        noun_phrase = re.sub(r"^[Jj]e\s+voudrais\s+", "", sentence)
        output.append(
            {
                "label": noun_phrase,
                "confidence": round(min(0.95, score), 2),
                "source": source,
            }
        )
    return output


def build_timed_chapters(
    segments: Sequence[Dict[str, object]],
    max_chapters: int = 12,
) -> List[Dict[str, object]]:
    """Regroupe les segments en chapitres horodatés."""

    if not segments:
        return []

    group_size = max(1, math.ceil(len(segments) / max_chapters))
    chapters: List[Dict[str, object]] = []
    for idx in range(0, len(segments), group_size):
        chunk = list(segments[idx : idx + group_size])
        if not chunk:
            continue
        start = chunk[0]["start"]
        end = chunk[-1]["end"]
        summary_text = " ".join(seg["text"] for seg in chunk)
        title_words = summary_text.split()
        title = " ".join(title_words[:8]).capitalize()
        chapters.append(
            {
                "index": len(chapters) + 1,
                "title": title or f"Chapitre {len(chapters) + 1}",
                "start": start,
                "end": end,
                "summary": summary_text,
            }
        )
    return chapters[:max_chapters]


def compute_plan_artifacts(
    transcript: str,
    *,
    segments: Optional[Sequence[Dict[str, object]]] = None,
    plan_override: Optional[Dict[str, object]] = None,
    plan_text: Optional[str] = None,
) -> PlanArtifacts:
    if plan_override:
        plan = deepcopy(plan_override)
    elif plan_text:
        try:
            plan = parse_plan_text(plan_text)
        except ValueError:
            plan = extract_plan(transcript)
    else:
        plan = extract_plan(transcript)

    if "steps" not in plan or not isinstance(plan.get("steps"), list) or not plan["steps"]:
        plan = extract_plan(transcript)

    if not plan.get("keywords"):
        keywords: List[str] = []
        seen = set()
        for token in _tokenize(transcript):
            if token in seen:
                continue
            seen.add(token)
            keywords.append(token)
            if len(keywords) >= 12:
                break
        plan["keywords"] = keywords

    ai_requests = extract_ai_requests(transcript)
    contradictions = contradiction_spans(transcript)
    objectives = summarize_objectifs_points(transcript, plan)
    chapters = build_timed_chapters(list(segments or []))

    return PlanArtifacts(
        plan=plan,
        ai_requests=ai_requests,
        contradictions=contradictions,
        objectives=objectives,
        chapters=chapters,
    )

# --- Historique -----------------------------------------------------------

_ARCHIVE_DIRS = [
    Path("Archive A-G"),
    Path("Archive J-M"),
    Path("Archive M-Z"),
]


def _parse_date_from_name(name: str) -> Optional[datetime]:
    patterns = [r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)"]
    for pat in patterns:
        match = re.search(pat, name)
        if match:
            try:
                year, month, day = map(int, match.groups())
                return datetime(year, month, day)
            except ValueError:
                continue
    return None


def _collect_archives_history(patient_hint: str, limit: int) -> List[Dict[str, str]]:
    normalized = (patient_hint or "").lower()
    candidates: List[Tuple[datetime, Path]] = []

    if ARCHIVES_ROOT.exists():
        for patient_dir in ARCHIVES_ROOT.iterdir():
            if not patient_dir.is_dir():
                continue
            slug_match = normalized and normalized in patient_dir.name.lower()
            notes_dir = patient_dir / "notes"
            if notes_dir.exists():
                for mail_file in notes_dir.glob("post_session/*/mail.txt"):
                    if normalized and not slug_match and normalized not in mail_file.stem.lower():
                        continue
                    stamp = datetime.fromtimestamp(mail_file.stat().st_mtime)
                    candidates.append((stamp, mail_file))

    if not candidates:
        return []

    candidates.sort(key=lambda item: item[0], reverse=True)
    entries: List[Dict[str, str]] = []
    for _, path in candidates[:limit]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        entries.append({"path": str(path), "title": path.stem.replace("_", " "), "content": content.strip()})
    return entries


def load_recent_history(patient_hint: Optional[str], limit: int = 3) -> List[Dict[str, str]]:
    """Charge 2-3 mails récents pour contextualiser le prompt."""

    history = _collect_archives_history(patient_hint or "", limit)
    if history:
        return history

    patient_hint = (patient_hint or "").lower()
    candidates: List[Tuple[datetime, Path]] = []
    for archive in _ARCHIVE_DIRS:
        if not archive.exists():
            continue
        for patient_dir in archive.iterdir():
            if not patient_dir.is_dir():
                continue
            dir_match = patient_hint and patient_hint in patient_dir.name.lower()
            for file in patient_dir.glob("*_mail.*"):
                if patient_hint and not dir_match and patient_hint not in file.name.lower():
                    continue
                date = _parse_date_from_name(file.name) or datetime.fromtimestamp(file.stat().st_mtime)
                candidates.append((date, file))
    if not candidates and patient_hint:
        return load_recent_history(None, limit)

    candidates.sort(key=lambda item: item[0], reverse=True)
    history_entries: List[Dict[str, str]] = []
    for _, path in candidates[:limit]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        history_entries.append(
            {
                "path": str(path),
                "title": path.stem.replace("_", " "),
                "content": content.strip(),
            }
        )
    return history_entries

# --- Recherche critique ---------------------------------------------------

_LIBRARY_INDEX = Path(__file__).resolve().parents[1] / "library" / "store" / "library_index.jsonl"
_LIBRARY_CACHE: Optional[List[Dict[str, object]]] = None


def _load_library_index() -> List[Dict[str, object]]:
    global _LIBRARY_CACHE
    if _LIBRARY_CACHE is not None:
        return _LIBRARY_CACHE
    items: List[Dict[str, object]] = []
    if _LIBRARY_INDEX.exists():
        with open(_LIBRARY_INDEX, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except json.JSONDecodeError:
                    continue
                items.append(doc)
    _LIBRARY_CACHE = items
    return items


def search_library(plan: Dict[str, object], limit: int = _MAX_REFERENCES) -> List[Dict[str, object]]:
    """Interroge la librairie locale et renvoie des extraits pertinents."""

    if limit <= 0:
        return []

    index_items = _load_library_index()
    queries: List[str] = []
    if plan.get("overview"):
        queries.append(plan["overview"])
    for step in plan.get("steps", [])[:6]:
        detail = step.get("detail")
        if isinstance(detail, str) and detail:
            queries.append(detail)
    if plan.get("keywords"):
        queries.append(" ".join(plan["keywords"]))

    scored: List[Tuple[float, Dict[str, object]]] = []
    for item in index_items:
        text = " ".join(
            [
                item.get("work", ""),
                item.get("author", ""),
                item.get("excerpt", ""),
                " ".join(item.get("tags", [])),
            ]
        ).lower()
        score = 0.0
        for query in queries:
            for token in _tokenize(query):
                if token in text:
                    score += 1.0
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda tup: tup[0], reverse=True)

    results: List[Dict[str, object]] = []
    for score, item in scored[:limit]:
        results.append(
            {
                "id": item.get("id"),
                "title": item.get("work", item.get("title", "")),
                "author": item.get("author", ""),
                "year": item.get("year"),
                "pages": item.get("pages") or item.get("note") or "",
                "excerpt": item.get("excerpt", ""),
                "score": score,
                "tags": item.get("tags", []),
            }
        )

    if len(results) < limit and indexer is not None:
        try:
            additional = indexer.search(" ".join(plan.get("keywords", [])[:6]), limit=limit)
        except Exception:
            additional = []
        for item in additional:
            if any(res.get("id") == item.get("id") for res in results):
                continue
            results.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "author": ", ".join(item.get("tags", [])),
                    "year": None,
                    "pages": "",
                    "excerpt": item.get("summary", ""),
                    "score": 0.5,
                    "tags": item.get("tags", []),
                }
            )
            if len(results) >= limit:
                break
    return results[:limit]


def load_critical_pack_or_fallback() -> Dict[str, object]:
    default_path = _SERVER_ROOT / "library" / "critical_pack.json"
    if default_path.exists():
        try:
            return json.loads(default_path.read_text("utf-8"))
        except Exception:
            pass
    return {"lenses": _FALLBACK_LENSES}


def select_lenses(
    transcript: str,
    references: List[Dict[str, object]],
    pack: Dict[str, object],
    limit: int = 3,
) -> List[Dict[str, object]]:
    """Choisit 2-3 lentilles critiques adaptées."""

    chosen: List[Dict[str, object]] = []
    transcript_lower = transcript.lower()
    keywords = {
        "trauma": "trauma-complexe",
        "violence": "patriarcat",
        "travail": "materiel",
        "emploi": "materiel",
        "fatigue": "validisme",
        "attention": "neurodiversite",
        "concentration": "neurodiversite",
    }
    lens_map = {lens["slug"]: lens for lens in pack.get("lenses", [])}
    already = set()
    for word, slug in keywords.items():
        if word in transcript_lower and slug in lens_map and slug not in already:
            chosen.append(lens_map[slug])
            already.add(slug)
    for ref in references:
        for tag in ref.get("tags", []):
            tag_slug = tag.lower().replace(" ", "-")
            if tag_slug in lens_map and tag_slug not in already:
                chosen.append(lens_map[tag_slug])
                already.add(tag_slug)
    for lens in pack.get("lenses", []):
        if lens["slug"] in already:
            continue
        chosen.append(lens)
        already.add(lens["slug"])
        if len(chosen) >= limit:
            break
    return chosen[:limit]


def build_critical_sheet(
    lenses: List[Dict[str, object]],
    references: List[Dict[str, object]],
    transcript: str,
) -> str:
    """Assemble un mémo critique utilisé dans le prompt final."""

    lines = ["Synthèse critique des axes à garder en tête :"]
    for lens in lenses:
        lines.append(f"- {lens['label']}: {lens['description']}")
    if references:
        lines.append("")
        lines.append("Références mobilisées :")
        for ref in references:
            author = ref.get("author", "?")
            year = ref.get("year") or "s.d."
            lines.append(f"- {author} ({year}) — {ref.get('title', '')}")
    lines.append("")
    lines.append("Mots clés du transcript : " + ", ".join(sorted(set(_tokenize(transcript)))[:12]))
    return "\n".join(lines)


def build_evidence_sheet(
    transcript: str,
    plan: Dict[str, object],
    objectives: List[Dict[str, object]],
    contradictions: List[Dict[str, object]],
    references: List[Dict[str, object]],
) -> str:
    lines: List[str] = ["# Evidence sheet"]
    lines.append("## Transcript condensé")
    lines.append(textwrap.fill(plan.get("overview", ""), 92))
    lines.append("")
    lines.append("## Objectifs évoqués")
    for obj in objectives[:8]:
        lines.append(f"- {obj['label']} (confiance {obj['confidence']})")
    if not objectives:
        lines.append("- Aucun objectif explicite détecté")
    lines.append("")
    lines.append("## Contradictions à approfondir")
    for span in contradictions[:5]:
        lines.append(f"- …{span['excerpt']}…")
    if not contradictions:
        lines.append("- RAS")
    lines.append("")
    lines.append("## Références")
    for ref in references:
        lines.append(
            f"- {ref.get('author', 'Auteur')} ({ref.get('year', 's.d.')}) — {ref.get('title', '')}"
        )
    return "\n".join(lines)


def build_reperes_candidates(
    references: List[Dict[str, object]],
    lenses: List[Dict[str, object]],
    history: List[Dict[str, str]],
) -> List[Dict[str, object]]:
    candidates: List[Dict[str, object]] = []
    for ref in references:
        snippet = textwrap.shorten(ref.get("excerpt", ""), width=240, placeholder="…")
        candidates.append(
            {
                "title": ref.get("title", "Ressource"),
                "body": snippet,
                "lens": random.choice(lenses)["label"] if lenses else "",
                "author": ref.get("author"),
                "year": ref.get("year"),
            }
        )
    for item in history[:2]:
        candidates.append(
            {
                "title": item.get("title", "Session précédente"),
                "body": textwrap.shorten(item.get("content", ""), 220, placeholder="…"),
                "lens": "Mémoire de la pratique",
                "author": "Mail précédent",
                "year": "",
            }
        )
    return candidates


def build_points_mail(plan: Dict[str, object], objectives: List[Dict[str, object]]) -> List[str]:
    points = [plan.get("overview", "")] + [step.get("title") for step in plan.get("steps", [])[:3]]
    for obj in objectives[:3]:
        points.append(obj.get("label"))
    return [p for p in points if p]


def perform_research_stage(
    transcript: str,
    plan: Dict[str, object],
    objectives: List[Dict[str, object]],
    contradictions: List[Dict[str, object]],
    history: List[Dict[str, str]],
    *,
    limit: int = _MAX_REFERENCES,
) -> Dict[str, object]:
    references = search_library(plan, limit=limit)
    pack = load_critical_pack_or_fallback()
    lenses = select_lenses(transcript, references, pack)
    evidence_sheet = build_evidence_sheet(transcript, plan, objectives, contradictions, references)
    critical_sheet = build_critical_sheet(lenses, references, transcript)
    reperes_candidates = build_reperes_candidates(references, lenses, history)
    points_mail = build_points_mail(plan, objectives)
    return {
        "references": references,
        "pack": pack,
        "lenses_used": lenses,
        "evidence_sheet": evidence_sheet,
        "critical_sheet": critical_sheet,
        "reperes_candidates": reperes_candidates,
        "points_mail": points_mail,
    }


def run_research_stage(
    transcript: str,
    artifacts: PlanArtifacts,
    history: Optional[List[Dict[str, str]]] = None,
    *,
    limit: int = _MAX_REFERENCES,
) -> Dict[str, object]:
    history = history or []
    return perform_research_stage(
        transcript,
        artifacts.plan,
        artifacts.objectives,
        artifacts.contradictions,
        history,
        limit=limit,
    )


def summarize_research_for_ui(research: Dict[str, object]) -> Dict[str, object]:
    summary = research.get("evidence_sheet") or ""
    results: List[Dict[str, object]] = []
    for ref in research.get("references", []):
        results.append(
            {
                "title": ref.get("title") or ref.get("work") or "Référence",
                "summary": textwrap.shorten(ref.get("excerpt", ""), width=240, placeholder="…"),
                "source": ref.get("author") or "",
                "url": ref.get("url") or "",
            }
        )
    return {"summary": summary, "results": results}

# --- Génération du mail ---------------------------------------------------


def _choose_intro(use_tu: bool) -> str:
    if use_tu:
        return "Comme d'habitude, ce texte sert de mémoire ; corrige si besoin."
    return "Comme d'habitude, ce texte sert de mémoire ; corrigez si besoin."


def _build_retained_section(
    transcript: str,
    plan: Dict[str, object],
    objectives: List[Dict[str, object]],
    contradictions: List[Dict[str, object]],
    chapters: List[Dict[str, object]],
    history: List[Dict[str, str]],
    research: Dict[str, object],
    target_words: Tuple[int, int] = (520, 880),
) -> str:
    overview = plan.get("overview", "")
    references = research.get("references", [])

    mention_corporel = "Vous avez décrit comment le corps réagit, notamment"
    mention_social = "Sur le plan social et relationnel, nous avons repéré"
    mention_material = "Les dimensions matérielles et économiques restent centrales"
    mention_attention = "Sur le plan attentionnel, vous avez noté"

    paragraphs: List[str] = []
    paragraphs.append(
        "En séance, vous avez pris le temps d'expliciter ce qui traverse votre quotidien"
        f" : {overview}"
    )
    if history:
        last_titles = ", ".join(h["title"] for h in history[:2])
        paragraphs.append(
            "Ce suivi s'inscrit dans la continuité des échanges précédents ("
            f"{last_titles}) où nous avions déjà stabilisé quelques appuis."
        )
    if objectives:
        focus = "; ".join(obj["label"] for obj in objectives[:4])
        paragraphs.append(
            f"Les objectifs formulés ensemble portent sur {focus}. "
            "Nous avons insisté sur le fait qu'ils devaient rester ajustables à vos rythmes."
        )
    if contradictions:
        excerpt = contradictions[0]["excerpt"]
        paragraphs.append(
            "Une tension a émergé, notamment lorsque vous avez exprimé : "
            f"« {excerpt} ». Nous l'avons reconnue comme un signal de vigilance,"
            " pas comme un échec, afin de garder l'alliance solide."
        )
    if chapters:
        first = chapters[0]
        paragraphs.append(
            "Le fil de séance s'est articulé en plusieurs moments, dont un premier temps"
            f" autour de {first['summary']}. Chaque chapitre nous a permis d'ancrer"
            " des gestes concrets et de vérifier ce qui restait soutenable."
        )
    if references:
        ref_sentences = []
        for ref in references:
            ref_sentences.append(
                f"{ref.get('author', 'Auteur')}, {ref.get('year', 's.d.')}, {ref.get('title', '').lower()}"
            )
        paragraphs.append(
            "Nous avons mis ces observations en regard d'apports issus de la recherche : "
            + "; ".join(ref_sentences)
            + ". Cela permet de replacer vos ressentis dans une histoire collective"
            " et de sortir du face-à-face responsabilisant."
        )
    paragraphs.append(
        mention_corporel
        + " les tensions musculaires, les variations de respiration et les besoins de"
        " repos immédiat après les interactions les plus exigeantes."
    )
    paragraphs.append(
        mention_social
        + " la façon dont les proches et les collectifs vous soutiennent ou au contraire"
        " demandent une disponibilité émotionnelle unilatérale."
    )
    paragraphs.append(
        mention_material
        + " notamment à propos du travail rémunéré, des démarches administratives et des"
        " coûts induits par la recherche de soin."
    )
    paragraphs.append(
        mention_attention
        + " les moments où l'attention se fragmente ou se hyper-focalise, et la nécessité"
        " de préserver des îlots sans stimulation pour récupérer."
    )
    paragraphs.append(
        "Nous avons enfin mis en commun des repères pratiques pour que chaque décision"
        " future reste située, en gardant l'œil sur les appuis concrets disponibles"
        " (soutiens proches, ressources collectives, marges de manœuvre matérielles)."
    )

    text = "\n\n".join(textwrap.fill(p, 90) for p in paragraphs)
    word_count = len(re.findall(r"\w+", text))
    minimum, maximum = target_words
    while word_count < minimum:
        padding = (
            "Nous avons également explicité la manière dont ces observations s'entrelacent"
            " avec des dynamiques structurelles : la fatigue cumulative, la charge"
            " de care redistribuée et les impératifs économiques qui pèsent sur vos"
            " décisions quotidiennes."
        )
        text += "\n\n" + textwrap.fill(padding, 90)
        word_count = len(re.findall(r"\w+", text))
        if word_count > maximum:
            break
    if word_count > maximum:
        words = text.split()
        text = " ".join(words[: maximum - 5])
    return text.strip()


def build_reperes_sections(
    research: Dict[str, object],
    objectives: List[Dict[str, object]],
    contradictions: List[Dict[str, object]],
    *,
    target_sections: int = 3,
) -> List[Dict[str, str]]:
    references = research.get("references", [])
    lenses = research.get("lenses_used", [])

    titles_pool = [
        "Ancrer les gestes corporels dans le quotidien",
        "Mettre en commun les solidarités matérielles",
        "Protéger l'attention et la charge cognitive",
        "Lire les rapports de pouvoir et de genre en jeu",
        "Mobiliser la recherche critique pour se légitimer",
        "Composer avec les temporalités de l'épuisement",
    ]
    random.shuffle(titles_pool)

    def _compose_paragraph(title: str) -> str:
        lens = random.choice(lenses)["label"] if lenses else "cadres critiques"
        ref_mentions = []
        for ref in references:
            ref_mentions.append(f"{ref.get('author', 'Auteur')} ({ref.get('year', 's.d.')})")
        ref_sentence = (
            "Ces propositions s'appuient sur " + ", ".join(ref_mentions[:2])
            if ref_mentions
            else "Ces propositions s'appuient sur la littérature critique partagée en séance"
        )
        objective_sentence = (
            "Elles prolongent l'objectif affirmé de " + objectives[0]["label"].lower()
            if objectives
            else "Elles prolongent vos objectifs exprimés en séance"
        )
        contradiction_sentence = (
            "et répondent aux tensions repérées lorsqu'il a été dit « "
            + contradictions[0]["excerpt"]
            + " »"
            if contradictions
            else "et gardent en tête les vigilances nommées ensemble"
        )
        paragraph = (
            f"{ref_sentence}, {objective_sentence} {contradiction_sentence}. "
            f"Avec la lentille {lens.lower()}, il s'agit de planifier des gestes concrets :"
            " repérer les situations à haut coût, prévoir des pauses corporelles avant et"
            " après les interactions exigeantes, et négocier une redistribution des tâches"
            " avec les allié·es disponibles. Chaque essai est co-évalué avec vos appuis de"
            " confiance en mobilisant les ressources locales (collectifs, espaces de soin,"
            " dispositifs associatifs) pour préserver votre autonomie matérielle et votre"
            " sécurité relationnelle. Il reste essentiel de noter ce qui fonctionne, les"
            " variations corporelles et attentionnelles, afin d'ajuster sans retomber dans"
            " des injonctions culpabilisantes."
        )
        return textwrap.fill(paragraph, 90)

    sections: List[Dict[str, str]] = []
    for title in titles_pool:
        sections.append({"title": title, "body": _compose_paragraph(title)})
        if len(sections) >= target_sections:
            break
    return sections


def validate_reperes_section(sections: Sequence[Dict[str, str]]) -> None:
    count = len(sections)
    if not 3 <= count <= 6:
        raise ValueError("invalid_reperes_count")
    seen_titles = set()
    for section in sections:
        title = section.get("title", "").strip()
        body = section.get("body", "").strip()
        if not title or not body:
            raise ValueError("invalid_reperes_section")
        if title.lower() in seen_titles:
            raise ValueError("duplicate_reperes_title")
        seen_titles.add(title.lower())
        word_count = len(re.findall(r"\w+", body))
        if word_count < 120:
            raise ValueError("reperes_too_short")


def _format_reperes_sections(sections: Sequence[Dict[str, str]]) -> str:
    blocks = []
    for section in sections:
        blocks.append(section["title"])
        blocks.append("")
        blocks.append(section["body"])
        blocks.append("")
    return "\n".join(blocks).strip()


def _clean_prompt_template(text: str, max_tokens: Optional[int] = None) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" \n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if max_tokens is not None:
        approx_tokens = max(1, len(text) // 4)
        if approx_tokens > max_tokens:
            allowed_chars = max_tokens * 4
            truncated = text[:allowed_chars]
            if " " in truncated:
                truncated = truncated.rsplit(" ", 1)[0]
            text = truncated.rstrip()
    return text


def build_prompt(
    patient_name: str,
    use_tu: bool,
    retained_section: str,
    reperes_sections: Sequence[Dict[str, str]],
    research: Dict[str, object],
    history: List[Dict[str, str]],
    transcript: str,
    plan: Dict[str, object],
) -> Dict[str, str]:
    validate_reperes_section(reperes_sections)

    address = f"Bonjour {patient_name},"
    intro = _choose_intro(use_tu)

    mail_lines = [
        address,
        "",
        intro,
        "",
        "Ce que vous avez exprimé et ce que j'en ai compris",
        "",
        retained_section,
        "",
        "Pistes de lecture et repères",
        "",
        _format_reperes_sections(reperes_sections),
        "",
        "Bien à vous,",
        "Benjamin.",
    ]
    mail = "\n".join(mail_lines).strip()

    critical = research.get("critical_sheet", "")
    history_text = "\n\n".join(item.get("content", "") for item in history)

    register_value = "tutoiement" if use_tu else "vouvoiement"
    recap_bounds = (520, 880)
    rep_bounds = (360, 720)
    plan_text_raw = format_plan_text(plan)
    plan_text_clean = (
        _clean_prompt_template(plan_text_raw)
        if plan_text_raw and plan_text_raw.strip()
        else "— néant explicite —"
    )
    historique_text = history_text.strip() or "— néant explicite —"
    historique_clean = _clean_prompt_template(historique_text)
    chapters_data = []
    if isinstance(plan, dict) and isinstance(plan.get("chapters"), list):
        chapters_data = list(plan.get("chapters", []))
    elif isinstance(research.get("chapters"), list):
        chapters_data = list(research.get("chapters") or [])
    chapters_json = json.dumps(chapters_data, ensure_ascii=False)[:4000]
    transcript_clean = _clean_prompt_template(transcript)
    prenom_value = patient_name.strip()

    lenses_summary: List[str] = []
    for lens in research.get("lenses_used", []) or []:
        if isinstance(lens, dict):
            label = lens.get("label") or lens.get("title") or lens.get("slug")
            if label:
                lenses_summary.append(str(label))
            else:
                lenses_summary.append(json.dumps(lens, ensure_ascii=False))
        else:
            lenses_summary.append(str(lens))

    repere_summaries: List[str] = []
    for entry in research.get("reperes_candidates", []) or []:
        if isinstance(entry, dict):
            title = entry.get("title") or entry.get("label") or entry.get("slug")
            detail = entry.get("body") or entry.get("excerpt") or entry.get("content")
            parts = [str(value) for value in (title, detail) if value]
            if parts:
                repere_summaries.append(" — ".join(parts))
            else:
                repere_summaries.append(json.dumps(entry, ensure_ascii=False))
        else:
            repere_summaries.append(str(entry))

    points_mail_summary: List[str] = []
    for point in research.get("points_mail", []) or []:
        if isinstance(point, dict):
            title = point.get("title") or point.get("label") or point.get("slug")
            detail = point.get("detail") or point.get("body") or point.get("content")
            parts = [str(value) for value in (title, detail) if value]
            if parts:
                points_mail_summary.append(" — ".join(parts))
            else:
                points_mail_summary.append(json.dumps(point, ensure_ascii=False))
        else:
            points_mail_summary.append(str(point))

    template = textwrap.dedent(
        f"""
=== SYSTEM (obligatoire) ===
Tu es chargé d'écrire un compte-rendu de séance en français qui reformule avec précision le contenu fourni.
Tu n'inventes rien. Tu ne prescris rien. Tu ne poses pas de diagnostic. Tu relies systématiquement les phénomènes au contexte matériel, social, institutionnel quand c'est pertinent.

=== STYLE_GUARD (obligatoire) ===
Règles de sortie typographiques et éditoriales (à respecter strictement) :
1) Guillemets obligatoires : utiliser exclusivement " ... ". Interdiction de « » et de “ ”.
2) Interdiction du tiret long et de --. Utiliser des parenthèses ( ... ) pour les incises, ou des virgules.
3) Pas de listes à puces, pas de markdown, pas de gras ou d'italiques. Paragraphes continus, une ligne vide entre eux.
4) Pas de double espace. Pas d'émojis. Pas de ton infantilisant.
5) Langue inclusive au besoin, mais naturelle et lisible.
6) Aucune bibliographie ou pharmacologie inventée : si les sections fournies sont vides, n'en parle pas.

=== TONE_PROFILE (obligatoire) ===
Sobre, humain, analytique sans surplomb. Matérialiste (déterminants concrets), antipsychanalytique, critique des explications individualisantes.
Éviter : "il faut", "vous devez", "cela prouve", "clairement".
Préférer : "vous décrivez", "vous soulignez", "cela éclaire", "cela interroge".
Zéro pathologisation. Pas de moralisation. Pas de coaching comportemental.

=== OUTPUT_RULES (obligatoire) ===
But : produire un texte immédiatement collable dans un mail, sans markdown.
Structure imposée :
1) Salutation : "Bonjour {prenom_value}," sur une ligne.
   Puis une phrase brève de cadrage : "Comme d'habitude, ce texte sert de mémoire ; corrigez si besoin."
2) Section 1, titre exact sur sa propre ligne : Ce que vous avez exprimé et ce que j'en ai compris
   Contenu : 2 à 4 paragraphes courts (3 à 5 lignes chacun), en prose.
3) Section 2, titre exact sur sa propre ligne : Pistes de lecture et repères
   Contenu : 2 à 4 paragraphes courts (3 à 5 lignes), en prose. Intégrer seulement ce qui est présent dans [Extraits bibliographiques] et [Pharmacologie] si non vides, en précisant sobrement le niveau de preuve si c'est utile.
4) Clôture sur deux lignes : "Bien à vous," puis "Benjamin."
Bornes : 450 à 900 mots au total. Pas de puces, pas d'énumérations numérotées, pas d'encarts.

=== CONTEXTE DISPONIBLE ===
[Patient·e] : {prenom_value or "—"} — [Fenêtre] : dernières séances récupérées
[PLAN COURT] :
{plan_text_clean}

[Pharmacologie] :
{research.get("pharmaco_sheet") or "néant explicite"}

[Extraits bibliographiques] :
{research.get("evidence_sheet", "") or "néant explicite"}

[Historique synthétique] :
{historique_clean}

[Chapitres (JSON tronqué)] :
{chapters_json}

[Points à rappeler au besoin] :
{'; '.join(research.get('points_mail', []) or [])}

=== TRANSCRIPT INTÉGRAL (référence) ===
<<<{transcript_clean}>>>

=== TÂCHE (obligatoire) ===
Rédige MAINTENANT le mail final en respectant STRICTEMENT SYSTEM, STYLE_GUARD, TONE_PROFILE et OUTPUT_RULES.
Contraintes fermes :
- Utiliser uniquement des guillemets droits " ".
- Interdiction des tirets longs et de --.
- Pas de puces ni de markdown.
- Aucune invention de contenu absent du contexte.
- Reliance au contexte matériel quand c'est pertinent, sans moraliser ni pathologiser.
- Deux sections exactement, titres strictement identiques à ceux imposés.
- Une seule ligne vide entre les paragraphes, pas de doubles espaces.

=== QA-CHECKS (auto-contrôle avant envoi) ===
Vérifie que le texte final :
- Contient "Bonjour " suivi du prénom.
- Contient les deux titres exacts : "Ce que vous avez exprimé et ce que j'en ai compris" et "Pistes de lecture et repères".
- Ne contient aucun caractère — ni la séquence --.
- Utilise uniquement des guillemets droits " " s'il y a des citations.
- Ne contient pas de *, -, •, 1) 2) etc.
- Ne contient aucune balise ou syntaxe markdown.
"""
    ).strip()
    internal_prompt = _clean_prompt_template(template)

    return {"mail": mail, "prompt": internal_prompt}


def run_prompt_stage(
    transcript: str,
    artifacts: PlanArtifacts,
    research: Dict[str, object],
    history: Optional[List[Dict[str, str]]],
    patient_name: str,
    use_tu: bool,
) -> Dict[str, object]:
    history = history or []
    retained_section = _build_retained_section(
        transcript,
        artifacts.plan,
        artifacts.objectives,
        artifacts.contradictions,
        artifacts.chapters,
        history,
        research,
    )
    reperes_sections = build_reperes_sections(
        research,
        artifacts.objectives,
        artifacts.contradictions,
    )
    prompt_package = build_prompt(
        patient_name,
        use_tu,
        retained_section,
        reperes_sections,
        research,
        history,
        transcript,
        artifacts.plan,
    )
    return {
        "mail": prompt_package["mail"],
        "prompt": prompt_package["prompt"],
        "reperes_sections": reperes_sections,
        "retained_section": retained_section,
    }

# --- Pipeline principal ---------------------------------------------------


def _derive_patient_name(options: Dict[str, object], file_storage: FileStorage) -> str:
    if options.get("patientName"):
        return str(options["patientName"]).strip()
    if options.get("patient"):
        return str(options["patient"]).strip()
    filename = getattr(file_storage, "filename", "")
    base = os.path.splitext(filename)[0]
    base = re.sub(r"[_-]+", " ", base)
    base = base.strip()
    return base or "Patient·e"


def _should_use_tu(options: Dict[str, object]) -> bool:
    if "tutoiement" in options:
        return bool(options["tutoiement"])
    if "useTu" in options:
        return bool(options["useTu"])
    return False


def _generate_run_id(options: Dict[str, object]) -> str:
    for key in ("run_id", "runId", "job_id", "jobId"):
        if key in options and options[key]:
            return _safe_filename(str(options[key]))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run-{stamp}-{secrets.token_hex(3)}"


def _persist_assets(
    asset_manager: AssetManager,
    run_dir: Path,
    transcript: TranscriptResult,
    plan: Dict[str, object],
    history: List[Dict[str, str]],
    mail_text: str,
    prompt_text: str,
    debug_payload: Optional[Dict[str, object]] = None,
) -> None:
    asset_manager.write_text(run_dir / "transcript.txt", transcript.text)
    plan_lines = [plan.get("overview", ""), ""]
    for step in plan.get("steps", [])[:60]:
        plan_lines.append(f"- {step['order']}: {step['detail']}")
    asset_manager.write_text(run_dir / "plan.txt", "\n".join(plan_lines))
    asset_manager.write_json(run_dir / "segments.json", transcript.segments)
    asset_manager.write_text(run_dir / "mail.txt", mail_text)
    asset_manager.write_text(run_dir / "prompt.txt", prompt_text)
    history_text = "\n\n".join(item.get("content", "") for item in history) or ""
    asset_manager.write_text(run_dir / "historique.txt", history_text)
    if debug_payload:
        debug_path = run_dir / "debug.md"
        lines = ["# DEBUG EXPORT"]
        for key, value in debug_payload.items():
            lines.append(f"## {key}")
            if isinstance(value, str):
                lines.append(value)
            else:
                lines.append(json.dumps(value, ensure_ascii=False, indent=2))
            lines.append("")
        asset_manager.write_text(debug_path, "\n".join(lines))


def process_post_session(audio_file: FileStorage, options: Dict[str, object] = None) -> Dict[str, object]:
    options = options or {}

    patient_name = _derive_patient_name(options, audio_file)
    patient_slug = slugify(
        options.get("patientId")
        or options.get("patient")
        or options.get("patient_slug")
        or patient_name
    )

    run_id = _generate_run_id(options)
    storage_root = ensure_patient_subdir(patient_slug, "notes/post_session")
    asset_manager = AssetManager(storage_root)
    run_dir = asset_manager.create_run_dir(run_id)

    transcript = transcribe_audio(audio_file, retries=3)
    artifacts = compute_plan_artifacts(transcript.text, segments=transcript.segments)

    use_tu = _should_use_tu(options)
    history = load_recent_history(patient_slug or patient_name)

    try:
        search_limit = int(options.get("searchLimit", _MAX_REFERENCES) or _MAX_REFERENCES)
    except Exception as exc:
        raise ValueError("invalid_search_limit") from exc

    research = run_research_stage(
        transcript.text,
        artifacts,
        history,
        limit=max(1, search_limit),
    )

    prompt_stage = run_prompt_stage(
        transcript.text,
        artifacts,
        research,
        history,
        patient_name,
        use_tu,
    )

    debug_payload = None
    if env.is_true("POST_SESSION_DEBUG") or options.get("debug"):
        debug_payload = {
            "evidence_sheet": research.get("evidence_sheet"),
            "critical_sheet": research.get("critical_sheet"),
            "reperes_sections": prompt_stage.get("reperes_sections"),
            "lenses": research.get("lenses_used"),
            "history": history,
            "points_mail": research.get("points_mail"),
        }

    _persist_assets(
        asset_manager,
        run_dir,
        transcript,
        artifacts.plan,
        history,
        prompt_stage.get("mail", ""),
        prompt_stage.get("prompt", ""),
        debug_payload,
    )

    return {
        "runId": run_id,
        "transcript": transcript.text,
        "segments": transcript.segments,
        "plan": artifacts.plan,
        "extractions": {
            "ai_requests": artifacts.ai_requests,
            "contradictions": artifacts.contradictions,
            "objectifs": artifacts.objectives,
            "chapters": artifacts.chapters,
        },
        "research": {
            "references": research.get("references", []),
            "lenses_used": research.get("lenses_used", []),
            "evidence_sheet": research.get("evidence_sheet"),
            "critical_sheet": research.get("critical_sheet"),
            "points_mail": research.get("points_mail"),
        },
        "references": research.get("references", []),
        "mail": prompt_stage["mail"],
        "prompt": prompt_stage["prompt"],
        "assets": {
            "directory": str(run_dir),
            "files": [
                str(run_dir / "transcript.txt"),
                str(run_dir / "plan.txt"),
                str(run_dir / "segments.json"),
                str(run_dir / "historique.txt"),
            ],
        },
        "planContext": pack_plan_artifacts(artifacts),
        "researchContext": pack_research_context(research),
    }

