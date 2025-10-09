"""Knowledge store for canonical clinical notions."""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Dict, Iterable, List, Mapping, Optional

from .journal import log_event
from .models import Notion
from .vector_db import VectorDB

_STORE_FILENAME = "notions.jsonl"
_STORE_LOCK = threading.RLock()

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


def _store_path() -> str:
    base = os.path.join(os.path.dirname(__file__), "store")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, _STORE_FILENAME)


def _load_all() -> Dict[str, Notion]:
    path = _store_path()
    notions: Dict[str, Notion] = {}
    if not os.path.exists(path):
        return notions
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if not payload:
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            notion = Notion.from_dict(data)
            notions[notion.id] = notion
    return notions


def _persist(notions: Mapping[str, Notion]) -> None:
    path = _store_path()
    with open(path, "w", encoding="utf-8") as handle:
        for notion in notions.values():
            handle.write(json.dumps(notion.to_dict(), ensure_ascii=False) + "\n")


def _coerce_list(values: Iterable[str] | None) -> List[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _validate_definition(definition: str) -> None:
    text = definition.strip()
    if len(text) < 40:
        raise ValueError("definition_too_short")
    sentences = [segment for segment in re.split(r"[.!?]+\s*", text) if segment.strip()]
    if len(sentences) > 3:
        raise ValueError("definition_too_long")


def _validate_sources(notion: Notion, store: VectorDB) -> None:
    if not notion.sources:
        raise ValueError("sources_required")
    for source in notion.sources:
        if not source.doc_id:
            raise ValueError("source_doc_id_missing")
        if not source.chunk_ids:
            raise ValueError("source_chunk_ids_missing")
        if not source.citation.strip():
            raise ValueError("source_citation_missing")
        for chunk_id in source.chunk_ids:
            if not store.has_chunk(source.doc_id, chunk_id):
                raise ValueError(f"unknown_chunk:{chunk_id}")


def save_notion(notion: Notion, *, vector_db: Optional[VectorDB] = None) -> Notion:
    """Persist a notion after strict validation."""

    notion.id = notion.id.strip()
    notion.label = notion.label.strip()
    notion.definition = notion.definition.strip()
    notion.synonyms = _coerce_list(notion.synonyms)
    notion.domains = _coerce_list(notion.domains)
    if not notion.id:
        raise ValueError("id_required")
    if not _SLUG_RE.match(notion.id):
        raise ValueError("id_invalid_slug")
    if not notion.label:
        raise ValueError("label_required")
    _validate_definition(notion.definition)
    store = vector_db or VectorDB()
    _validate_sources(notion, store)
    with _STORE_LOCK:
        notions = _load_all()
        notions[notion.id] = notion
        _persist(notions)
    log_event(
        "save_notion",
        {
            "id": notion.id,
            "label": notion.label,
            "sources": sum(len(source.chunk_ids) for source in notion.sources),
        },
    )
    return notion


def list_notions_for_doc(doc_id: str) -> List[Dict[str, object]]:
    with _STORE_LOCK:
        notions = _load_all()
    results: List[Dict[str, object]] = []
    for notion in notions.values():
        if any(source.doc_id == doc_id for source in notion.sources):
            results.append(notion.to_dict())
    results.sort(key=lambda item: str(item.get("label", "")).lower())
    return results


def search_notions(q: str, limit: int = 20, doc_id: Optional[str] = None) -> List[Notion]:
    query = (q or "").strip().lower()
    with _STORE_LOCK:
        notions = list(_load_all().values())
    results: List[tuple[int, Notion]] = []
    for notion in notions:
        if doc_id and not any(source.doc_id == doc_id for source in notion.sources):
            continue
        if not query:
            results.append((0, notion))
            continue
        haystacks = [
            notion.label,
            notion.definition,
            " ".join(notion.synonyms),
            " ".join(notion.domains),
        ]
        haystacks = [value.lower() for value in haystacks if value]
        score = 0
        if any(value.startswith(query) for value in haystacks):
            score = 3
        elif any(query in value for value in haystacks):
            score = 1
        if score:
            results.append((score, notion))
    if not results and not query:
        return sorted(notions, key=lambda item: item.label.lower())[:limit]
    results.sort(key=lambda item: (-item[0], item[1].label.lower()))
    return [notion for _, notion in results[:limit]]


def list_notions() -> List[Notion]:
    with _STORE_LOCK:
        notions = list(_load_all().values())
    notions.sort(key=lambda item: item.label.lower())
    return notions


def notion_links_count(doc_id: str) -> int:
    total = 0
    for notion in search_notions("", doc_id=doc_id):
        for source in notion.sources:
            if source.doc_id == doc_id:
                total += len(source.chunk_ids)
    return total


__all__ = [
    "save_notion",
    "list_notions_for_doc",
    "search_notions",
    "list_notions",
    "notion_links_count",
]
