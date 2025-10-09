"""Filesystem-backed patient repository with caching and diagnostics."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from server.util.slug import slugify

LOGGER = logging.getLogger("assist.patients.repo")

_CACHE: Dict[str, object] = {
    "ts": 0.0,
    "payload": None,
    "diagnostics": None,
}
_CACHE_TTL = 60.0  # seconds

IGNORE_PREFIXES = (".", "_")
IGNORE_NAMES = {".DS_Store", "desktop.ini"}

_BASE_DIR = Path(__file__).resolve().parents[2]


def _split_paths(value: str | None) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(os.pathsep) if part.strip()]


def _normalise_path(raw_value: str) -> Optional[Path]:
    candidate = Path(raw_value).expanduser()
    if not candidate.is_absolute():
        candidate = _BASE_DIR / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        LOGGER.warning("Impossible de résoudre le chemin patient: %s", candidate, exc_info=True)
        return None
    if resolved.exists() and not resolved.is_dir():
        LOGGER.warning("Le chemin patient n'est pas un dossier: %s", resolved)
        return None
    if not resolved.exists():
        try:
            resolved.mkdir(parents=True, exist_ok=True)
        except OSError:
            LOGGER.warning("Impossible d'accéder au dossier patient: %s", resolved, exc_info=True)
            return None
    return resolved


def _resolve_roots() -> List[Path]:
    env_candidates: List[str] = []
    env_candidates.extend(_split_paths(os.getenv("PATIENTS_DIR")))
    env_candidates.extend(_split_paths(os.getenv("PATIENTS_ARCHIVES_DIRS")))

    roots: List[Path] = []
    seen: set[Path] = set()
    for candidate in env_candidates:
        if not candidate:
            continue
        normalised = _normalise_path(candidate)
        if normalised is None:
            continue
        if normalised in seen:
            continue
        seen.add(normalised)
        roots.append(normalised)

    if roots:
        return roots

    fallback = (_BASE_DIR / "instance" / "archives").resolve()
    fallback.mkdir(parents=True, exist_ok=True)
    return [fallback]


def _resolve_root() -> Path:
    return _resolve_roots()[0]


ARCHIVES_ROOT = _resolve_root()


@dataclass
class PatientEntry:
    id: str
    slug: str
    name: str
    display_name: str
    folder: Path
    meta: Dict[str, object]

    def as_item(self) -> Dict[str, object]:
        payload = {
            "id": self.id,
            "slug": self.slug,
            "name": self.display_name,
            "displayName": self.display_name,
            "path": str(self.folder),
            "archive_path": str(self.folder),
        }
        payload.update(self.meta)
        return payload


def _load_profile(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:  # pragma: no cover - defensive
        LOGGER.debug("Profil patient illisible: %s", path, exc_info=True)
    return {}


def _write_default_profile(path: Path, slug: str, display: str) -> Dict[str, object]:
    payload = {
        "id": slug,
        "slug": slug,
        "display_name": display,
        "displayName": display,
        "name": display,
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        LOGGER.warning("Impossible de créer le profil patient: %s", path, exc_info=True)
    return payload


def _looks_like_container(folder: Path) -> bool:
    try:
        children = list(folder.iterdir())
    except OSError:
        return False
    has_candidate = False
    for child in children:
        if child.is_dir():
            name = child.name.strip()
            if name.startswith(IGNORE_PREFIXES) or name in IGNORE_NAMES:
                continue
            has_candidate = True
        else:
            return False
    return has_candidate


def _scan_root(root: Path) -> Tuple[List[PatientEntry], Dict[str, object]]:
    entries: List[PatientEntry] = []
    kept = 0
    dropped: List[Dict[str, str]] = []
    dropped_dir_count = 0
    if not root.exists():
        return entries, {
            "dir_abs": str(root),
            "total_entries": 0,
            "kept": kept,
            "dropped": dropped,
            "sample": [],
        }
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        LOGGER.warning("Impossible de lister le répertoire patients: %s", root, exc_info=True)
        return entries, {
            "dir_abs": str(root),
            "total_entries": 0,
            "kept": kept,
            "dropped": dropped,
            "sample": [],
        }

    candidates: List[Path] = []
    for child in children:
        if not child.is_dir():
            dropped.append({"name": child.name, "reason": "not_directory"})
            continue
        name = child.name.strip()
        if name.startswith(IGNORE_PREFIXES):
            dropped.append({"name": child.name, "reason": "ignored_prefix"})
            dropped_dir_count += 1
            continue
        if name in IGNORE_NAMES:
            dropped.append({"name": child.name, "reason": "ignored_name"})
            dropped_dir_count += 1
            continue
        candidates.append(child)

    if candidates and all(_looks_like_container(folder) for folder in candidates):
        expanded: List[Path] = []
        for container in candidates:
            try:
                sub_children = sorted(container.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                LOGGER.warning(
                    "Impossible de lister le répertoire patient: %s", container, exc_info=True
                )
                continue
            for sub in sub_children:
                name = sub.name.strip()
                if not sub.is_dir():
                    dropped.append({"name": f"{container.name}/{sub.name}", "reason": "not_directory"})
                    continue
                if name.startswith(IGNORE_PREFIXES):
                    dropped.append(
                        {"name": f"{container.name}/{sub.name}", "reason": "ignored_prefix"}
                    )
                    dropped_dir_count += 1
                    continue
                if name in IGNORE_NAMES:
                    dropped.append(
                        {"name": f"{container.name}/{sub.name}", "reason": "ignored_name"}
                    )
                    dropped_dir_count += 1
                    continue
                expanded.append(sub)
        candidates = expanded

    total_dirs = len(candidates) + dropped_dir_count

    for child in candidates:
        name = child.name.strip()
        slug = slugify(name)
        profile = child / "meta.json"
        if profile.exists():
            meta = _load_profile(profile)
        else:
            meta = _write_default_profile(profile, slug, name)
        display = (
            str(meta.get("display_name") or meta.get("displayName") or meta.get("name") or name)
            .strip()
            or name
        )
        slug = slugify(str(meta.get("slug") or meta.get("id") or display or slug))
        if not slug:
            dropped.append({"name": child.name, "reason": "missing_slug"})
            dropped_dir_count += 1
            continue
        entry = PatientEntry(
            id=slug,
            slug=slug,
            name=display,
            display_name=display,
            folder=child,
            meta=meta,
        )
        entries.append(entry)
        kept += 1

    total_dirs = len(entries) + dropped_dir_count
    sample = [entry.display_name for entry in entries[:10]]
    return entries, {
        "dir_abs": str(root),
        "total_entries": total_dirs,
        "kept": kept,
        "dropped": dropped,
        "sample": sample,
    }


def _merge_entries(entries: Iterable[PatientEntry]) -> List[PatientEntry]:
    by_slug: Dict[str, PatientEntry] = {}
    for entry in entries:
        slug_key = entry.slug.lower()
        existing = by_slug.get(slug_key)
        if existing is None:
            by_slug[slug_key] = entry
            continue
        # Merge metadata while preferring explicit values
        merged_meta = dict(existing.meta)
        for key, value in entry.meta.items():
            if value in (None, ""):
                continue
            merged_meta[key] = value
        best_name = entry.display_name.strip() or existing.display_name
        by_slug[slug_key] = PatientEntry(
            id=entry.id,
            slug=entry.slug,
            name=best_name,
            display_name=best_name,
            folder=entry.folder,
            meta=merged_meta,
        )
    ordered = list(by_slug.values())
    ordered.sort(key=lambda item: item.display_name.lower())
    return ordered


def _serialise(entries: List[PatientEntry]) -> List[Dict[str, object]]:
    return [entry.as_item() for entry in entries]


def _compute_cache() -> Dict[str, object]:
    roots = _resolve_roots()
    all_entries: List[PatientEntry] = []
    total_entries = 0
    total_kept = 0
    all_dropped: List[Dict[str, str]] = []
    samples: List[str] = []

    for root in roots:
        entries, diagnostics = _scan_root(root)
        all_entries.extend(entries)
        try:
            total_entries += int(diagnostics.get("total_entries", len(entries)))
        except (TypeError, ValueError):
            total_entries += len(entries)
        try:
            total_kept += int(diagnostics.get("kept", len(entries)))
        except (TypeError, ValueError):
            total_kept += len(entries)
        dropped = diagnostics.get("dropped")
        if isinstance(dropped, list):
            all_dropped.extend(dropped)
        sample = diagnostics.get("sample")
        if isinstance(sample, list):
            samples.extend(str(item) for item in sample)

    merged = _merge_entries(all_entries)
    items = _serialise(merged)
    roots_payload = [str(root) for root in roots]
    dir_abs = roots_payload[0] if roots_payload else ""
    payload = {
        "ok": True,
        "source": "archives",
        "dir_abs": dir_abs,
        "count": len(items),
        "items": items,
        "roots": roots_payload,
    }
    diagnostics_items = [
        {"slug": entry.slug, "name": entry.display_name}
        for entry in merged
    ]
    diagnostics_payload = {
        "ok": True,
        "dir_abs": dir_abs,
        "total_entries": total_entries,
        "kept": total_kept,
        "dropped": all_dropped,
        "sample": samples[:10],
        "count": payload["count"],
        "source": payload["source"],
        "roots": roots_payload,
        "items": diagnostics_items,
    }
    _CACHE["ts"] = time.time()
    _CACHE["payload"] = payload
    _CACHE["diagnostics"] = diagnostics_payload
    LOGGER.debug("Patients diagnostics: %s", diagnostics_payload)
    dropped_count = len(diagnostics_payload.get("dropped") or [])
    LOGGER.info(
        "Patients détectés: %d (dir=%s, ignorés=%d)",
        payload["count"],
        diagnostics_payload.get("dir_abs") or "aucune source",
        dropped_count,
    )
    return payload


def list_patients(force_refresh: bool = False) -> Dict[str, object]:
    now = time.time()
    cached = _CACHE.get("payload")
    if not force_refresh and cached and now - float(_CACHE.get("ts", 0.0)) < _CACHE_TTL:
        return dict(cached)
    return _compute_cache()


def cache_diagnostics() -> Dict[str, object]:
    diagnostics = _CACHE.get("diagnostics")
    if diagnostics is None:
        _compute_cache()
        diagnostics = _CACHE.get("diagnostics")
    return dict(diagnostics or {})


def invalidate_cache() -> None:
    _CACHE["ts"] = 0.0
    _CACHE["payload"] = None
    _CACHE["diagnostics"] = None


def _primary_root() -> Path:
    root = _resolve_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def create_patient(display_name: str, slug: str | None = None, email: str | None = None) -> Dict[str, object]:
    clean_name = (display_name or "").strip()
    if not clean_name:
        raise ValueError("display_name requis")
    base_slug = slugify(slug or clean_name)
    snapshot = list_patients(force_refresh=True)
    patients = snapshot.get("items", []) if isinstance(snapshot, dict) else []
    existing = {str(item.get("slug") or item.get("id")) for item in patients}
    candidate = base_slug
    suffix = 2
    while candidate in existing:
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    root = _primary_root()
    folder = root / clean_name
    if folder.exists():
        folder = root / candidate
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / "meta.json"
    payload: Dict[str, object] = {
        "id": candidate,
        "slug": candidate,
        "display_name": clean_name,
    }
    if email:
        payload["email"] = email
    try:
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        LOGGER.warning("Impossible d'écrire le profil patient: %s", meta_path, exc_info=True)
    invalidate_cache()
    snapshot = list_patients(force_refresh=True)
    patients = snapshot.get("items", []) if isinstance(snapshot, dict) else []
    created = next((item for item in patients if str(item.get("slug")) == candidate), payload)
    return created


def resolve_patient_archive(slug: str) -> Optional[Path]:
    if not slug:
        return None
    snapshot = list_patients()
    patients = snapshot.get("items", []) if isinstance(snapshot, dict) else []
    for item in patients:
        if str(item.get("slug")) == slug:
            archive = item.get("archive_path") or item.get("path")
            if archive:
                path = Path(str(archive))
                if not path.is_absolute():
                    path = (_BASE_DIR / path).resolve()
                return path
    return None


__all__ = [
    "list_patients",
    "invalidate_cache",
    "create_patient",
    "cache_diagnostics",
    "resolve_patient_archive",
    "ARCHIVES_ROOT",
]
