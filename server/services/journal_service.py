"""Persistence layer for the « journal critique » feature."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import uuid4


LOGGER = logging.getLogger("assist.journal.service")


def _utc_now_iso() -> str:
    """Return the current timestamp in ISO8601 format with a ``Z`` suffix."""

    value = datetime.now(timezone.utc)
    return value.replace(microsecond=value.microsecond // 1000 * 1000).isoformat().replace(
        "+00:00", "Z"
    )


def _normalise_terms(values: Iterable[str]) -> List[str]:
    """Return normalised terms used for lightweight deduplication."""

    results: List[str] = []
    for raw in values or []:
        if not isinstance(raw, str):
            continue
        text = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"\s+", " ", text).strip().lower()
        if text and text not in results:
            results.append(text)
    return results


def _excerpt(body_md: str, limit: int = 240) -> str:
    """Build a short excerpt from the body Markdown."""

    if not isinstance(body_md, str):
        return ""
    text = re.sub(r"\s+", " ", body_md).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}…"


def _ensure_directory(path: Path) -> None:
    """Create ``path`` if it does not already exist."""

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - defensive logging only
        LOGGER.error("Impossible de créer le dossier %s: %s", path, exc)
        raise


def _atomic_write(path: Path, content: str) -> None:
    """Atomically write ``content`` (UTF-8) into ``path``."""

    _ensure_directory(path.parent)
    tmp_handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=str(path.parent), newline="\n"
    )
    try:
        with tmp_handle as handle:
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_handle.name, path)
    finally:
        try:
            os.unlink(tmp_handle.name)
        except FileNotFoundError:
            pass


def _dump_json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False)


def _dump_index(items: Iterable[Dict[str, object]]) -> str:
    return "\n".join(_dump_json(item) for item in items if item) + "\n"


@dataclass
class JournalEntry:
    id: str
    title: str
    body_md: str
    created_at: str
    updated_at: str
    tags: List[str] = field(default_factory=list)
    concepts: List[str] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)
    patients: List[Dict[str, str]] = field(default_factory=list)
    meta: Dict[str, object] = field(default_factory=dict)


class JournalService:
    """High level API used by the Flask blueprint to persist entries."""

    JOURNAL_DIRNAME = "journal_critique"

    def __init__(self, instance_path: Path) -> None:
        base = Path(instance_path)
        self.base_dir = base / self.JOURNAL_DIRNAME
        self.entries_dir = self.base_dir / "entries"
        self.index_path = self.base_dir / "index.jsonl"
        self.trash_dir = self.base_dir / ".trash"
        self.mirror_dir = base / "search_indexes"
        self.mirror_path = self.mirror_dir / "journal_critique.jsonl"
        self._lock = threading.RLock()
        self._index: Dict[str, Dict[str, object]] = {}

        for folder in (self.entries_dir, self.trash_dir, self.mirror_dir):
            _ensure_directory(folder)

        self._load_index()
        # Ensure both index and mirror exist on disk for downstream consumers.
        try:
            self._write_index()
        except OSError as exc:
            LOGGER.warning("Initialisation de l'index journal impossible: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load_index(self) -> None:
        """Load the JSONL index into memory."""

        records: Dict[str, Dict[str, object]] = {}
        if self.index_path.exists():
            try:
                with self.index_path.open("r", encoding="utf-8") as handle:
                    for line_no, line in enumerate(handle, start=1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError as exc:
                            LOGGER.warning(
                                "Index journal corrompu (ligne %d): %s", line_no, exc
                            )
                            continue
                        if not isinstance(data, dict):
                            continue
                        entry_id = str(data.get("id") or "")
                        if not entry_id:
                            continue
                        records[entry_id] = data
            except OSError as exc:
                LOGGER.warning("Lecture de l'index journal impossible: %s", exc)
        self._index = records

    def _write_index(self) -> None:
        serialized = _dump_index(self._iter_index())
        _atomic_write(self.index_path, serialized)
        _atomic_write(self.mirror_path, serialized)

    def _iter_index(self) -> Iterable[Dict[str, object]]:
        return sorted(
            self._index.values(),
            key=lambda item: item.get("updated_at", ""),
            reverse=True,
        )

    def _entry_path(self, entry_id: str) -> Path:
        safe_id = entry_id.strip()
        return self.entries_dir / f"{safe_id}.json"

    def _compose_index_record(self, entry: JournalEntry) -> Dict[str, object]:
        return {
            "id": entry.id,
            "title": entry.title,
            "tags": list(entry.tags or []),
            "concepts_norm": _normalise_terms(entry.concepts),
            "patients": [item for item in entry.patients if isinstance(item, dict)],
            "excerpt": _excerpt(entry.body_md),
            "updated_at": entry.updated_at,
        }

    def _coerce_entry(self, payload: Dict[str, object]) -> JournalEntry:
        return JournalEntry(
            id=str(payload.get("id", "")),
            title=str(payload.get("title", "")).strip(),
            body_md=str(payload.get("body_md", "")),
            created_at=str(payload.get("created_at", "")),
            updated_at=str(payload.get("updated_at", "")),
            tags=[str(tag) for tag in payload.get("tags", []) if isinstance(tag, str)],
            concepts=[
                str(concept)
                for concept in payload.get("concepts", [])
                if isinstance(concept, str)
            ],
            sources=[
                {"label": str(item.get("label", "")), "url": str(item.get("url", ""))}
                for item in payload.get("sources", [])
                if isinstance(item, dict)
            ],
            patients=[
                {"id": str(item.get("id", "")), "name": str(item.get("name", ""))}
                for item in payload.get("patients", [])
                if isinstance(item, dict)
            ],
            meta={**payload.get("meta", {})} if isinstance(payload.get("meta"), dict) else {},
        )

    def _write_entry(self, entry: JournalEntry) -> None:
        payload = {
            "id": entry.id,
            "title": entry.title,
            "body_md": entry.body_md,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "tags": entry.tags,
            "concepts": entry.concepts,
            "sources": entry.sources,
            "patients": entry.patients,
            "meta": entry.meta,
        }
        serialized = _dump_json(payload)
        _atomic_write(self._entry_path(entry.id), serialized)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_entries(
        self,
        *,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        concepts: Optional[List[str]] = None,
        patient: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, object]], int]:
        with self._lock:
            records = list(self._iter_index())

        tags = [tag.lower() for tag in tags or [] if tag]
        concepts_norm = _normalise_terms(concepts or [])
        patient_token = (patient or "").strip().lower()
        query_terms = [token.lower() for token in (query or "").split() if token]

        filtered: List[Dict[str, object]] = []
        for record in records:
            if query_terms:
                haystack = " ".join(
                    [
                        str(record.get("title", "")),
                        str(record.get("excerpt", "")),
                        " ".join(record.get("tags", [])),
                        " ".join(record.get("concepts_norm", [])),
                    ]
                ).lower()
                if not all(term in haystack for term in query_terms):
                    continue

            if tags and not all(tag in [t.lower() for t in record.get("tags", [])] for tag in tags):
                continue

            if concepts_norm and not any(
                concept in record.get("concepts_norm", []) for concept in concepts_norm
            ):
                continue

            if patient_token:
                patients = record.get("patients", []) or []
                if not any(
                    patient_token in str(item.get("id", "")).lower()
                    or patient_token in str(item.get("name", "")).lower()
                    for item in patients
                ):
                    continue

            if date_from or date_to:
                updated_at = record.get("updated_at")
                try:
                    updated_dt = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if date_from and updated_dt < date_from:
                    continue
                if date_to and updated_dt > date_to:
                    continue

            filtered.append(record)

        total = len(filtered)
        start = max(offset, 0)
        end = start + max(limit, 0)
        return filtered[start:end], total

    def get_entry(self, entry_id: str) -> Optional[Dict[str, object]]:
        path = self._entry_path(entry_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOGGER.error("Lecture de l'entrée %s impossible: %s", entry_id, exc)
            raise
        if isinstance(data, dict):
            return data
        return None

    def save_entry(self, payload: Dict[str, object]) -> Dict[str, object]:
        entry_id = str(payload.get("id") or "").strip()
        now_iso = _utc_now_iso()
        created_at = now_iso
        existing_entry: Optional[Dict[str, object]] = None

        if entry_id:
            try:
                existing_entry = self.get_entry(entry_id)
            except OSError as exc:
                raise RuntimeError("io_error") from exc
            if not existing_entry:
                raise FileNotFoundError(entry_id)
            created_at = str(existing_entry.get("created_at") or now_iso)
        else:
            prefix = os.getenv("JOURNAL_ID_PREFIX", "")
            entry_id = f"{prefix}{uuid4().hex}"
        base_meta: Dict[str, object] = {}
        if existing_entry and isinstance(existing_entry.get("meta"), dict):
            base_meta.update(existing_entry["meta"])  # type: ignore[arg-type]
        if isinstance(payload.get("meta"), dict):
            base_meta.update(payload["meta"])  # type: ignore[arg-type]
        base_meta.setdefault("author", "system")
        base_meta.setdefault("version", 1)

        entry_payload = {
            "id": entry_id,
            "title": payload.get("title", ""),
            "body_md": payload.get("body_md", ""),
            "tags": payload.get("tags", []),
            "concepts": payload.get("concepts", []),
            "sources": payload.get("sources", []),
            "patients": payload.get("patients", []),
            "meta": base_meta,
            "created_at": created_at,
            "updated_at": now_iso,
        }
        entry = self._coerce_entry(entry_payload)
        if not entry.title:
            raise ValueError("title_required")

        with self._lock:
            self._write_entry(entry)
            index_record = self._compose_index_record(entry)
            self._index[entry.id] = index_record
            self._write_index()

        LOGGER.info("Journal enregistré", extra={"journal_id": entry.id})
        return {
            "id": entry.id,
            "title": entry.title,
            "body_md": entry.body_md,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "tags": entry.tags,
            "concepts": entry.concepts,
            "sources": entry.sources,
            "patients": entry.patients,
            "meta": entry.meta,
        }

    def delete_entry(self, entry_id: str) -> None:
        path = self._entry_path(entry_id)
        if not path.exists():
            raise FileNotFoundError(entry_id)
        trash_path = self.trash_dir / f"{entry_id}.json"
        with self._lock:
            try:
                os.replace(path, trash_path)
            except OSError as exc:
                LOGGER.error("Impossible de déplacer %s vers la corbeille: %s", path, exc)
                raise
            self._index.pop(entry_id, None)
            self._write_index()
        LOGGER.info("Journal déplacé en corbeille", extra={"journal_id": entry_id})

    def reindex(self) -> int:
        entries: Dict[str, Dict[str, object]] = {}
        for candidate in sorted(self.entries_dir.glob("*.json")):
            if candidate.suffix.lower() != ".json":
                LOGGER.warning("Fichier ignoré lors de la réindexation: %s", candidate)
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                LOGGER.warning("Entrée illisible %s: %s", candidate, exc)
                continue
            if not isinstance(data, dict):
                continue
            entry_id = str(data.get("id") or "").strip()
            if not entry_id:
                LOGGER.warning("Entrée sans identifiant ignorée: %s", candidate)
                continue
            data.setdefault("created_at", data.get("updated_at") or _utc_now_iso())
            data.setdefault("updated_at", data.get("created_at"))
            entry = self._coerce_entry(data)
            entries[entry.id] = self._compose_index_record(entry)

        with self._lock:
            self._index = entries
            self._write_index()

        LOGGER.info("Réindexation journal critique", extra={"count": len(entries)})
        return len(entries)

    def get_index_snapshot(self) -> List[Dict[str, object]]:
        with self._lock:
            return list(self._iter_index())


__all__ = ["JournalService", "JournalEntry"]

