"""Implémentation locale d'un moteur de recherche clinique basé sur SQLite FTS5."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Sequence as SequenceABC
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

try:  # pragma: no cover - dépendances optionnelles
    from modules.library_index import ensure_index_layout
except Exception:  # pragma: no cover - mode dégradé si dépendances manquantes
    ensure_index_layout = None  # type: ignore[assignment]

LOGGER = logging.getLogger("assist.research.search")


@dataclass(frozen=True)
class SearchResult:
    """Structure simple pour exposer les résultats d'une requête."""

    source: str
    doc_id: str
    title: str
    year: int | None
    type: str | None
    level: str | None
    domain: Sequence[str]
    page: int | None
    score: float
    snippet: str
    page_start: int | None = None
    page_end: int | None = None
    segment_id: str | None = None

    def to_dict(self) -> Dict[str, object]:
        payload = {
            "source": self.source,
            "doc_id": self.doc_id,
            "title": self.title,
            "year": self.year,
            "type": self.type,
            "level": self.level,
            "domain": list(self.domain),
            "page": self.page,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "score": round(self.score, 4),
            "snippet": self.snippet,
        }
        if self.segment_id is not None:
            payload["segment_id"] = self.segment_id
        return payload


class LocalSearchEngine:
    """Moteur de recherche local alimenté par un index SQLite FTS5."""

    def __init__(
        self,
        segments: Iterable[Mapping[str, object]] | None = None,
        *,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._fallback_conn: sqlite3.Connection | None = None

        if segments is not None:
            self._init_fallback(segments)
            return

        resolved_db: Path | None = None
        if db_path is not None:
            resolved_db = Path(db_path)
        else:
            if ensure_index_layout is not None:
                try:
                    layout = ensure_index_layout()
                    resolved_db = layout["db"]
                except Exception:  # pragma: no cover - robustesse
                    LOGGER.warning("Impossible de préparer l'index FTS, bascule en mode dégradé.", exc_info=True)
            else:  # pragma: no cover - dépendance manquante
                LOGGER.warning("Index clinique indisponible : dépendances manquantes, utilisation du mode dégradé.")

        if resolved_db is not None:
            try:
                self._conn = sqlite3.connect(
                    f"file:{resolved_db}?mode=ro",
                    uri=True,
                    check_same_thread=False,
                )
                self._conn.row_factory = sqlite3.Row
                try:
                    self._conn.execute("PRAGMA query_only=ON;")
                except sqlite3.OperationalError:
                    pass
            except sqlite3.Error as exc:
                LOGGER.warning(
                    "Connexion à l'index clinique impossible (%s), utilisation du mode dégradé.",
                    exc,
                )
                self._conn = None

        if self._conn is None:
            fallback_segments = segments or self._load_default_segments()
            self._init_fallback(fallback_segments)

    def _init_fallback(self, segments: Iterable[Mapping[str, object]]) -> None:
        self._fallback_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._fallback_conn.row_factory = sqlite3.Row
        self._create_schema(self._fallback_conn)
        self._populate(self._fallback_conn, segments)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        with conn:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS segments USING fts5(
                    doc_id UNINDEXED,
                    page UNINDEXED,
                    title,
                    year,
                    type,
                    level,
                    domains,
                    text,
                    tokenize='unicode61'
                )
                """
            )

    def _load_default_segments(self) -> List[Mapping[str, object]]:
        index_dir = Path(__file__).resolve().parent.parent / "library" / "store"
        candidates = [index_dir / "library_index.jsonl", index_dir / "library_index_sample.jsonl"]
        segments: List[Mapping[str, object]] = []
        for path in candidates:
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        try:
                            payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        title = str(payload.get("title") or "Document clinique")
                        text = str(payload.get("text") or payload.get("content") or "")
                        domains = payload.get("domains") or []
                        if isinstance(domains, str):
                            domains = [domains]
                        doc_hash = "sha256:" + hashlib.sha256(title.encode("utf-8")).hexdigest()
                        segments.append(
                            {
                                "doc_id": doc_hash,
                                "page": 1,
                                "title": title,
                                "year": payload.get("year"),
                                "type": payload.get("type", "Article"),
                                "level": payload.get("level", "Modéré"),
                                "domain": domains,
                                "text": text,
                            }
                        )
            except OSError:
                LOGGER.warning("Impossible de lire %s", path, exc_info=True)
        return segments

    def _populate(self, conn: sqlite3.Connection, segments: Iterable[Mapping[str, object]]) -> None:
        to_insert = []
        for item in segments:
            if not item.get("text"):
                continue
            domains = item.get("domain") or item.get("domains") or []
            if isinstance(domains, str):
                domains = [domains]
            domain_payload = json.dumps(domains, ensure_ascii=False)
            to_insert.append(
                (
                    str(item.get("doc_id")),
                    str(item.get("page", "")),
                    str(item.get("title", "")),
                    str(item.get("year", "")),
                    str(item.get("type", "")),
                    str(item.get("level", "")),
                    domain_payload,
                    str(item.get("text", "")),
                )
            )
        if not to_insert:
            return
        with conn:
            conn.executemany(
                "INSERT INTO segments(doc_id, page, title, year, type, level, domains, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                to_insert,
            )

    def search(self, queries: Sequence[str], *, top_k: int = 5) -> List[Dict[str, object]]:
        if not queries:
            return []
        if self._conn is not None:
            return self._search_persistent(queries, top_k=top_k)
        if self._fallback_conn is not None:
            return self._search_fallback(queries, top_k=top_k)
        return []

    def _search_persistent(self, queries: Sequence[str], *, top_k: int) -> List[Dict[str, object]]:
        limit = max(top_k * 2, top_k)
        aggregated: Dict[str, SearchResult] = {}
        with self._lock:
            for query in queries:
                query = (query or "").strip()
                if not query:
                    continue
                try:
                    cursor = self._conn.execute(
                        """
                        SELECT s.segment_id,
                               s.doc_id,
                               s.page_start,
                               s.page_end,
                               s.text,
                               s.metadata,
                               bm25(segments_fts) AS rank,
                               snippet(segments_fts, 2, '<mark>', '</mark>', '…', 48) AS preview
                        FROM segments_fts
                        JOIN segments s USING (segment_id)
                        WHERE segments_fts MATCH ?
                        ORDER BY rank ASC
                        LIMIT ?
                        """,
                        (query, limit),
                    )
                except sqlite3.OperationalError as exc:
                    LOGGER.warning("Recherche FTS impossible : %s", exc, exc_info=True)
                    continue
                for row in cursor:
                    candidate = self._row_to_result(row)
                    key = candidate.segment_id or f"{candidate.doc_id}:{candidate.page}"
                    previous = aggregated.get(key)
                    if previous is None or candidate.score > previous.score:
                        aggregated[key] = candidate
        results = sorted(aggregated.values(), key=lambda item: (-item.score, item.title))
        return [result.to_dict() for result in results[:top_k]]

    def _search_fallback(self, queries: Sequence[str], *, top_k: int) -> List[Dict[str, object]]:
        limit = max(top_k * 2, top_k)
        aggregated: Dict[str, SearchResult] = {}
        with self._lock:
            for query in queries:
                if not query:
                    continue
                try:
                    cursor = self._fallback_conn.execute(
                        """
                        SELECT doc_id, page, title, year, type, level, domains, text,
                               bm25(segments) AS score,
                               snippet(segments, 7, '<mark>', '</mark>', '…', 48) AS preview
                        FROM segments
                        WHERE segments MATCH ?
                        ORDER BY score LIMIT ?
                        """,
                        (query, limit),
                    )
                except sqlite3.OperationalError as exc:
                    if "bm25" not in str(exc).lower():
                        raise
                    cursor = self._fallback_conn.execute(
                        """
                        SELECT doc_id, page, title, year, type, level, domains, text,
                               rank AS score,
                               snippet(segments, 7, '<mark>', '</mark>', '…', 48) AS preview
                        FROM segments
                        WHERE segments MATCH ?
                        ORDER BY rank LIMIT ?
                        """,
                        (query, limit),
                    )
                for row in cursor:
                    try:
                        year_value = int(row["year"])
                    except (TypeError, ValueError):
                        year_value = None
                    try:
                        page_value = int(row["page"])
                    except (TypeError, ValueError):
                        page_value = None
                    try:
                        domains = json.loads(row["domains"]) if row["domains"] else []
                    except json.JSONDecodeError:
                        domains = []
                    score = float(row["score"]) if row["score"] is not None else 0.0
                    snippet = row["preview"] or row["text"][:160]
                    candidate = SearchResult(
                        source="local",
                        doc_id=str(row["doc_id"]),
                        title=str(row["title"] or "Document clinique"),
                        year=year_value,
                        type=str(row["type"] or ""),
                        level=str(row["level"] or ""),
                        domain=domains,
                        page=page_value,
                        page_start=page_value,
                        page_end=page_value,
                        segment_id=None,
                        score=score,
                        snippet=snippet,
                    )
                    key = f"{candidate.doc_id}:{candidate.page}"
                    previous = aggregated.get(key)
                    if previous is None or candidate.score > previous.score:
                        aggregated[key] = candidate
        results = sorted(aggregated.values(), key=lambda item: (-item.score, item.title))
        return [result.to_dict() for result in results[:top_k]]

    def _row_to_result(self, row: sqlite3.Row) -> SearchResult:
        metadata_raw = row["metadata"]
        metadata: Mapping[str, object] | object
        if metadata_raw:
            try:
                metadata = json.loads(metadata_raw)
            except json.JSONDecodeError:
                metadata = {}
        else:
            metadata = {}
        if not isinstance(metadata, Mapping):
            metadata = {}

        def _first(keys: Sequence[str]) -> object | None:
            for key in keys:
                if key not in metadata:
                    continue
                value = metadata[key]
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                return value
            return None

        title = _first(["title", "document_title", "name"]) or "Document clinique"
        doc_type = _first(["type", "document_type", "kind"]) or ""
        level = _first(["level", "evidence_level"]) or ""
        domains = _first(["domain", "domains", "tags"]) or []
        if isinstance(domains, str):
            domains = [domains]
        elif not isinstance(domains, SequenceABC):
            domains = []

        year_value = _first(["year", "publication_year", "date"])
        try:
            year_int = int(year_value) if year_value not in {None, ""} else None
        except (TypeError, ValueError):
            year_int = None

        page_start = row["page_start"]
        page_end = row["page_end"]
        try:
            page_start_int = int(page_start) if page_start not in {None, ""} else None
        except (TypeError, ValueError):
            page_start_int = None
        try:
            page_end_int = int(page_end) if page_end not in {None, ""} else None
        except (TypeError, ValueError):
            page_end_int = None

        raw_rank = row["rank"]
        try:
            rank_value = float(raw_rank) if raw_rank is not None else None
        except (TypeError, ValueError):
            rank_value = None
        score = 1.0 / (1.0 + rank_value) if rank_value is not None else 0.0

        snippet = row["preview"] or row["text"][:160]

        return SearchResult(
            source="local",
            doc_id=str(row["doc_id"]),
            title=str(title),
            year=year_int,
            type=str(doc_type),
            level=str(level),
            domain=list(domains),
            page=page_start_int,
            page_start=page_start_int,
            page_end=page_end_int,
            segment_id=str(row["segment_id"]),
            score=score,
            snippet=str(snippet),
        )


__all__ = ["LocalSearchEngine", "SearchResult"]

