"""Patients helpers bridging the repository and Flask blueprints."""

from __future__ import annotations

import logging
import unicodedata
from typing import Dict, List, Tuple

from .patients_repo import (
    cache_diagnostics as repo_cache_diagnostics,
    create_patient as repo_create_patient,
    invalidate_cache as repo_invalidate_cache,
    list_patients as repo_list_patients,
    resolve_patient_archive as repo_resolve_patient_archive,
)


LOGGER = logging.getLogger("assist.patients")



_FIRSTNAME_BOUNDARY = {" ", "\xa0"}


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _normalize(value: str) -> str:
    return _strip_accents(value).casefold().strip()


def _firstname_prefix(value: str) -> str:
    normalized = _normalize(value)
    if not normalized:
        return ""
    for idx, char in enumerate(normalized):
        if char in _FIRSTNAME_BOUNDARY:
            return normalized[:idx]
    return normalized


def _levenshtein(a: str, b: str, *, limit: int = 1) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        best = limit + 1
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + cost
            value = min(insert_cost, delete_cost, replace_cost)
            current.append(value)
            if value < best:
                best = value
        previous = current
        if best > limit:
            return limit + 1
    return previous[-1]


def _list_patient_items() -> List[Dict[str, object]]:
    snapshot = list_patients(refresh=False)
    items = snapshot.get("items")
    if isinstance(items, list):
        return items
    return []


def _match_payload(entry: Dict[str, object]) -> Dict[str, str]:
    raw_display = entry.get("displayName") or entry.get("display_name") or entry.get("name")
    display = str(raw_display or "").strip()
    identifier = (
        entry.get("id")
        or entry.get("patientId")
        or entry.get("patient_id")
        or entry.get("slug")
    )
    identifier = str(identifier or "").strip()
    email = str(entry.get("email") or entry.get("mail") or entry.get("emailAddress") or "").strip()
    payload = {"id": identifier, "display": display}
    if email:
        payload["email"] = email
    return payload


def find_patients_by_firstname(firstname: str) -> List[Dict[str, str]]:
    candidate = _firstname_prefix(firstname)
    if not candidate:
        return []

    exact_matches: List[Tuple[str, Dict[str, str]]] = []
    fuzzy_matches: List[Tuple[int, Dict[str, str]]] = []

    seen_ids: set[str] = set()
    for entry in _list_patient_items():
        if not isinstance(entry, dict):
            continue
        display = str(entry.get("displayName") or entry.get("display_name") or entry.get("name") or "").strip()
        if not display:
            continue
        identifier = (
            entry.get("id")
            or entry.get("patientId")
            or entry.get("patient_id")
            or entry.get("slug")
        )
        identifier = str(identifier or "").strip()
        if not identifier or identifier in seen_ids:
            continue
        normalized_first = _firstname_prefix(display)
        if not normalized_first:
            continue
        if normalized_first == candidate:
            exact_matches.append((normalized_first, _match_payload(entry)))
            seen_ids.add(identifier)
            continue
        distance = _levenshtein(normalized_first, candidate, limit=1)
        if distance <= 1:
            fuzzy_matches.append((distance, _match_payload(entry)))
            seen_ids.add(identifier)

    if exact_matches:
        ranked = sorted(exact_matches, key=lambda item: _normalize(item[1].get("display", "")))
    else:
        ranked = sorted(
            fuzzy_matches,
            key=lambda item: (item[0], _normalize(item[1].get("display", ""))),
        )

    results = [payload for _score, payload in ranked[:5]]
    return results


_SOURCE = ""
_DIR_ABS = ""


def _remember_snapshot(snapshot: Dict[str, object]) -> None:
    global _SOURCE, _DIR_ABS
    source = str(snapshot.get("source") or "") if isinstance(snapshot, dict) else ""
    dir_abs = str(snapshot.get("dir_abs") or "") if isinstance(snapshot, dict) else ""
    _SOURCE = source or dir_abs or _SOURCE
    _DIR_ABS = dir_abs or _DIR_ABS


def _augment_snapshot(snapshot: Dict[str, object]) -> Dict[str, object]:
    data = dict(snapshot)
    items = list(data.get("items", [])) if isinstance(data.get("items"), list) else []
    data.setdefault("patients", items)
    if _DIR_ABS:
        data.setdefault("dir_abs", _DIR_ABS)
    if data.get("dir_abs"):
        data.setdefault("roots", [data["dir_abs"]])
    else:
        data.setdefault("roots", [])
    data.setdefault("count", len(items))
    data.setdefault("ok", True)
    return data


def list_patients(refresh: bool = False) -> Dict[str, object]:
    snapshot = repo_list_patients(force_refresh=refresh)
    _remember_snapshot(snapshot)
    return _augment_snapshot(snapshot)


def list_patients_with_roots(refresh: bool = False) -> Tuple[List[Dict[str, object]], List[str]]:
    snapshot = list_patients(refresh=refresh)
    items = list(snapshot.get("items", []))
    roots = list(snapshot.get("roots", []))
    return items, roots


def get_patients_source() -> str:
    return _SOURCE


def reload_patients() -> Dict[str, object]:
    repo_invalidate_cache()
    snapshot = list_patients(refresh=True)
    items = list(snapshot.get("items", []))
    return {
        "patients": list(snapshot.get("patients", [])),
        "items": items,
        "source": snapshot.get("source", _SOURCE),
        "dir_abs": snapshot.get("dir_abs", _DIR_ABS),
        "count": snapshot.get("count", len(items)),
        "roots": list(snapshot.get("roots", [])),
    }


def refresh_cache() -> Tuple[List[Dict[str, object]], List[str]]:
    repo_invalidate_cache()
    snapshot = list_patients(refresh=True)
    diagnostics = repo_cache_diagnostics()
    items = list(snapshot.get("items", []))
    roots = list(snapshot.get("roots", []))
    count = snapshot.get("count") if isinstance(snapshot.get("count"), int) else len(items)
    dir_abs = (
        diagnostics.get("dir_abs")
        if isinstance(diagnostics, dict)
        else snapshot.get("dir_abs")
    )
    if not dir_abs:
        dir_abs = snapshot.get("dir_abs")
    dropped = diagnostics.get("dropped") if isinstance(diagnostics, dict) else None
    dropped_count = len(dropped) if isinstance(dropped, list) else 0
    dir_abs_value = str(dir_abs or "aucune source")
    LOGGER.info(
        "Patients détectés (rafraîchissement): %d (dir=%s, ignorés=%d)",
        count,
        dir_abs_value,
        dropped_count,
    )
    return items, roots


def get_diagnostics() -> Dict[str, object]:
    snapshot = repo_cache_diagnostics()
    _remember_snapshot(snapshot)
    payload = dict(snapshot)
    payload.setdefault("ok", True)
    payload.setdefault("dir_abs", _DIR_ABS)
    payload.setdefault("source", _SOURCE)
    if not isinstance(payload.get("roots"), list):
        payload["roots"] = [payload["dir_abs"]] if payload["dir_abs"] else []
    if not isinstance(payload.get("count"), int):
        try:
            payload["count"] = int(payload.get("kept", 0))
        except (TypeError, ValueError):
            payload["count"] = 0
    return payload


def resolve_patient_archive(slug: str):  # pragma: no cover - proxy
    return repo_resolve_patient_archive(slug)


def create_patient(display_name: str, slug: str | None = None, email: str | None = None) -> Dict[str, object]:
    created = repo_create_patient(display_name=display_name, slug=slug, email=email)
    return created


__all__ = [
    "create_patient",
    "get_patients_source",
    "list_patients",
    "list_patients_with_roots",
    "refresh_cache",
    "reload_patients",
    "get_diagnostics",
    "resolve_patient_archive",
    "find_patients_by_firstname",
]
