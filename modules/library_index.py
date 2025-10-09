"""Indexation hybride pour la Bibliothèque clinique."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

try:  # pragma: no cover - dépendance optionnelle
    import faiss  # type: ignore
except Exception:  # pragma: no cover - fallback
    faiss = None  # type: ignore

try:  # pragma: no cover - dépendance optionnelle
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - fallback
    np = None  # type: ignore

from modules.library_llm import LibraryLLMError, embed_texts


LOGGER = logging.getLogger(__name__)


class LibraryIndexError(RuntimeError):
    """Exception de base pour l'index de la bibliothèque."""


INDEX_ROOT = Path("library/index")
LOGS_DIR = Path("library/logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)
INDEX_LOG_PATH = LOGS_DIR / "index.log"

_FAISS_AVAILABLE = faiss is not None
_WARNED_FAISS = False


def _append_log(event: str, **payload: object) -> None:
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **payload}
    with INDEX_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False))
        handle.write("\n")


def ensure_index_layout(root: Path | str = INDEX_ROOT) -> Dict[str, Path]:
    """Garantit la présence des dossiers et de la base FTS."""

    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    vectors_dir = root_path / "vectors"
    vectors_dir.mkdir(parents=True, exist_ok=True)
    db_path = root_path / "fts.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS segments (
                segment_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                text TEXT NOT NULL,
                metadata TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
                segment_id UNINDEXED,
                doc_id UNINDEXED,
                text,
                tokenize='unicode61'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notions (
                notion_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                priority REAL DEFAULT 0,
                autosuggest_pre INTEGER DEFAULT 0,
                autosuggest_post INTEGER DEFAULT 0,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS notions_fts USING fts5(
                notion_id UNINDEXED,
                content,
                tokenize='unicode61'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contributions (
                contribution_id TEXT PRIMARY KEY,
                notion_id TEXT,
                doc_id TEXT,
                payload TEXT NOT NULL
            )
            """
        )

    return {"root": root_path, "vectors": vectors_dir, "db": db_path}


def _warn_once(message: str) -> None:
    global _WARNED_FAISS
    if not _WARNED_FAISS:
        LOGGER.warning(message)
        _append_log("warning", message=message)
        _WARNED_FAISS = True


@dataclass
class NumpyVectorStore:
    path: Path
    ids: List[str]
    vectors: "np.ndarray | None"
    loaded: bool = False

    def _ensure_loaded(self) -> None:
        if self.loaded:
            return
        if np is None:
            self.ids = []
            self.vectors = None
            self.loaded = True
            return
        if self.path.exists():
            data = np.load(self.path, allow_pickle=True)
            self.ids = list(data["ids"].tolist())
            self.vectors = data["vectors"].astype("float32")
        else:
            self.ids = []
            self.vectors = None
        self.loaded = True

    def _save(self) -> None:
        if np is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ids_array = np.array(self.ids, dtype=object)
        vectors = self.vectors if self.vectors is not None else np.zeros((0, 0), dtype="float32")
        np.savez(self.path, ids=ids_array, vectors=vectors)

    def upsert(self, items: Sequence[Tuple[str, Sequence[float]]]) -> None:
        if np is None or not items:
            if np is None:
                _warn_once("numpy indisponible : l'index vectoriel fonctionne en mode dégradé.")
            return
        self._ensure_loaded()
        vectors_list = [] if self.vectors is None else [vec for vec in self.vectors]
        ids = list(self.ids)
        for identifier, vector in items:
            vec = np.asarray(vector, dtype="float32")
            if vec.size == 0:
                continue
            if self.vectors is not None and vec.shape[0] != self.vectors.shape[1]:
                LOGGER.warning("Dimension de vecteur incohérente pour %s", identifier)
                continue
            if identifier in ids:
                idx = ids.index(identifier)
                vectors_list[idx] = vec
            else:
                ids.append(identifier)
                vectors_list.append(vec)
        if not vectors_list:
            return
        self.ids = ids
        self.vectors = np.vstack(vectors_list)
        self._save()

    def search(self, vector: Sequence[float], top_k: int = 5) -> List[Tuple[str, float]]:
        if np is None:
            return []
        self._ensure_loaded()
        if self.vectors is None or not self.ids:
            return []
        query = np.asarray(vector, dtype="float32")
        if query.size == 0:
            return []
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []
        norms = np.linalg.norm(self.vectors, axis=1) * query_norm
        norms[norms == 0] = 1.0
        scores = (self.vectors @ query) / norms
        top_indices = scores.argsort()[::-1][:top_k]
        return [(self.ids[idx], float(scores[idx])) for idx in top_indices if idx < len(self.ids)]


_VECTOR_STORES: Dict[str, NumpyVectorStore] = {}


def _get_vector_store(name: str) -> NumpyVectorStore:
    layout = ensure_index_layout()
    path = layout["vectors"] / f"{name}.npz"
    if not _FAISS_AVAILABLE:
        _warn_once("FAISS indisponible : utilisation du fallback numpy pour l'indexation vectorielle.")
    store = _VECTOR_STORES.get(name)
    if store is None:
        store = NumpyVectorStore(path=path, ids=[], vectors=None)
        _VECTOR_STORES[name] = store
    return store


def _normalize_text_block(record: dict) -> str:
    tags = " ".join(record.get("canonical_tags", []) or record.get("tags", []))
    consensus = record.get("consensus_summary") or record.get("summary") or ""
    practice = record.get("practice_guidance", {})
    opening = " ".join(practice.get("opening_questions_core", []))
    psycho = practice.get("psychoeducation_core", "")
    return " \n".join([record.get("title", ""), consensus, opening, psycho, tags]).strip()


def index_segments(doc_id: str, segments: Iterable[dict]) -> None:
    """Indexe les segments extraits dans SQLite et l'index vectoriel."""

    layout = ensure_index_layout()
    db_path = layout["db"]
    records = [segment for segment in segments if isinstance(segment, dict) and segment.get("segment_id")]
    if not records:
        return

    with sqlite3.connect(db_path) as conn:
        conn.execute("BEGIN")
        for segment in records:
            segment_id = str(segment.get("segment_id"))
            pages = segment.get("pages", []) or []
            page_start = int(pages[0]) if pages else None
            page_end = int(pages[-1]) if pages else None
            text = str(segment.get("text", ""))
            metadata = json.dumps({k: v for k, v in segment.items() if k not in {"segment_id", "pages", "text"}}, ensure_ascii=False)
            conn.execute(
                """
                INSERT OR REPLACE INTO segments(segment_id, doc_id, page_start, page_end, text, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (segment_id, doc_id, page_start, page_end, text, metadata),
            )
            conn.execute("DELETE FROM segments_fts WHERE segment_id = ?", (segment_id,))
            conn.execute(
                "INSERT INTO segments_fts(segment_id, doc_id, text) VALUES (?, ?, ?)",
                (segment_id, doc_id, text),
            )
        conn.commit()

    try:
        vectors = embed_texts([str(segment.get("text", "")) for segment in records])
    except LibraryLLMError as exc:  # pragma: no cover - dépendance API
        LOGGER.warning("Impossible de calculer les embeddings des segments : %s", exc)
        _append_log("embed_segments_failed", doc_id=doc_id, error=str(exc))
        vectors = []

    if vectors:
        store = _get_vector_store("segments")
        store.upsert(list(zip([str(s.get("segment_id")) for s in records], vectors)))
    _append_log("index_segments", doc_id=doc_id, count=len(records))


def index_notion(notion_record: Dict[str, object]) -> None:
    """Indexe une notion canonique dans la base FTS et l'index vectoriel."""

    layout = ensure_index_layout()
    db_path = layout["db"]

    notion_id = str(notion_record.get("notion_id")) if notion_record.get("notion_id") else None
    if not notion_id:
        raise LibraryIndexError("notion_id manquant pour l'indexation")

    title = str(notion_record.get("title", notion_id))
    summary = str(notion_record.get("consensus_summary") or notion_record.get("summary") or "").strip()
    priority = float(notion_record.get("priority", 0.0) or 0.0)
    autosuggest_pre = 1 if notion_record.get("allowed_for_autosuggest_pre", False) else 0
    autosuggest_post = 1 if notion_record.get("allowed_for_autosuggest_post", False) else 0
    payload = json.dumps(notion_record, ensure_ascii=False)

    text_block = _normalize_text_block(notion_record)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO notions(notion_id, title, summary, priority, autosuggest_pre, autosuggest_post, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (notion_id, title, summary or text_block, priority, autosuggest_pre, autosuggest_post, payload),
        )
        conn.execute("DELETE FROM notions_fts WHERE notion_id = ?", (notion_id,))
        conn.execute(
            "INSERT INTO notions_fts(notion_id, content) VALUES (?, ?)",
            (notion_id, text_block),
        )

    try:
        vectors = embed_texts([text_block])
    except LibraryLLMError as exc:  # pragma: no cover - dépendance API
        LOGGER.warning("Impossible de calculer l'embedding de la notion %s : %s", notion_id, exc)
        _append_log("embed_notion_failed", notion_id=notion_id, error=str(exc))
        vectors = []

    if vectors:
        store = _get_vector_store("notions")
        store.upsert([(notion_id, vectors[0])])

    _append_log("index_notion", notion_id=notion_id, title=title)


def _load_notion_payload(row: sqlite3.Row) -> Dict[str, object]:
    try:
        payload = json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError):
        payload = {"title": row["title"], "consensus_summary": row["summary"], "priority": row["priority"]}
    return payload


def _filter_notion(payload: Dict[str, object], mode: str, filters: Dict[str, object] | None) -> bool:
    if filters is None:
        filters = {}
    tags_filter = set(filters.get("tags") or [])
    evidence_filter = set(filters.get("evidence") or [])
    years_filter = set(filters.get("year") or filters.get("years") or [])

    if tags_filter:
        notion_tags = set(payload.get("canonical_tags") or payload.get("tags") or [])
        if not notion_tags.intersection(tags_filter):
            return False
    if evidence_filter:
        evidence = payload.get("evidence_level") or payload.get("evidence", {}).get("type")
        if evidence and evidence not in evidence_filter:
            pass
        elif evidence_filter:
            return False
    if years_filter:
        year = payload.get("year") or payload.get("source_year")
        if year and str(year) not in {str(y) for y in years_filter}:
            return False
    if mode == "pre" and not payload.get("allowed_for_autosuggest_pre", payload.get("autosuggest_pre")):
        return False
    if mode == "post" and not payload.get("allowed_for_autosuggest_post", payload.get("autosuggest_post")):
        return False
    return True


def _format_result(payload: Dict[str, object], score: float, row: sqlite3.Row) -> Dict[str, object]:
    practice = payload.get("practice_guidance", {}) if isinstance(payload.get("practice_guidance"), dict) else {}
    psycho = practice.get("psychoeducation_core")
    opening = practice.get("opening_questions_core") or []
    return {
        "notion_id": payload.get("notion_id", row["notion_id"]),
        "title": payload.get("title", row["title"]),
        "summary": payload.get("consensus_summary") or payload.get("summary") or row["summary"],
        "priority": float(payload.get("priority", row["priority"])),
        "autosuggest_pre": bool(payload.get("allowed_for_autosuggest_pre", row["autosuggest_pre"])),
        "autosuggest_post": bool(payload.get("allowed_for_autosuggest_post", row["autosuggest_post"])),
        "score": score,
        "psychoeducation": psycho,
        "opening_questions": opening,
        "source_contributions": payload.get("source_contributions", []),
        "payload": payload,
    }


def hybrid_search(query: str, mode: str = "pre", filters: Dict[str, object] | None = None, limit: int = 10) -> List[dict]:
    """Recherche hybride combinant FTS et similarité vectorielle."""

    layout = ensure_index_layout()
    db_path = layout["db"]
    filters = filters or {}
    limit = max(1, min(int(limit or 10), 50))
    results: Dict[str, Dict[str, object]] = {}

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if query:
            cursor = conn.execute(
                """
                SELECT n.*, bm25(notions_fts) AS rank
                FROM notions_fts
                JOIN notions n ON n.notion_id = notions_fts.notion_id
                WHERE notions_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (query, limit * 3),
            )
        else:
            cursor = conn.execute(
                """
                SELECT n.*, 1.0 AS rank
                FROM notions n
                ORDER BY priority DESC
                LIMIT ?
                """,
                (limit * 3,),
            )
        for row in cursor:
            payload = _load_notion_payload(row)
            if not _filter_notion(payload, mode, filters):
                continue
            lexical_score = 1.0 / (1.0 + float(row["rank"]))
            results[row["notion_id"]] = {
                "row": row,
                "payload": payload,
                "lexical": lexical_score,
                "vector": 0.0,
            }

    if query:
        try:
            embedding = embed_texts([query])
        except LibraryLLMError as exc:  # pragma: no cover - dépendance API
            LOGGER.warning("Embedding de requête impossible : %s", exc)
            _append_log("embed_query_failed", query=query, error=str(exc))
            embedding = []
        if embedding:
            store = _get_vector_store("notions")
            for notion_id, score in store.search(embedding[0], top_k=limit * 3):
                if notion_id not in results:
                    with sqlite3.connect(db_path) as conn:
                        conn.row_factory = sqlite3.Row
                        row = conn.execute(
                            "SELECT * FROM notions WHERE notion_id = ?", (notion_id,)
                        ).fetchone()
                    if row is None:
                        continue
                    payload = _load_notion_payload(row)
                    if not _filter_notion(payload, mode, filters):
                        continue
                    results[notion_id] = {"row": row, "payload": payload, "lexical": 0.0, "vector": float(score)}
                else:
                    results[notion_id]["vector"] = max(results[notion_id]["vector"], float(score))

    scored: List[Tuple[str, float, Dict[str, object]]] = []
    for notion_id, info in results.items():
        row = info["row"]
        payload = info["payload"]
        priority = float(payload.get("priority", row["priority"]))
        score = info["lexical"] * 0.6 + info["vector"] * 0.3 + priority * 0.1
        scored.append((notion_id, score, _format_result(payload, score, row)))

    scored.sort(key=lambda item: item[1], reverse=True)
    return [item[2] for item in scored[:limit]]


__all__ = [
    "LibraryIndexError",
    "ensure_index_layout",
    "index_segments",
    "index_notion",
    "hybrid_search",
]
