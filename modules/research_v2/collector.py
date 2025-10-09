"""Collecte des résultats externes avec cache et règles de politesse."""

from __future__ import annotations

import inspect
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from .faceting import Facet
from .sources import SourceRegistry

LOGGER = logging.getLogger("presession.research")
CACHE_PATH = Path(os.environ.get("RESEARCH_V2_CACHE_PATH", "logs/research/cache.json"))
CACHE_TTL = int(os.environ.get("RESEARCH_V2_CACHE_TTL_SECONDS", "86400"))
USER_AGENT = os.environ.get("RESEARCH_V2_USER_AGENT", "pre-session-research-bot/2.0")
REQUEST_DELAY = float(os.environ.get("RESEARCH_V2_REQUEST_DELAY", "0.5"))
REQUEST_TIMEOUT = float(os.environ.get("RESEARCH_V2_REQUEST_TIMEOUT", "8.0"))
MAX_RETRIES = int(os.environ.get("RESEARCH_V2_MAX_RETRIES", "2"))


@dataclass
class CandidateDocument:
    url: str
    title: str
    snippet: str
    content: str
    published_at: Optional[datetime]
    domain: str
    source_type: str
    evidence_level: str
    jurisdiction: str
    raw: Dict[str, str] = field(default_factory=dict)
    angle: str = "clinical"


FetchResponse = Iterable[Dict[str, str]]
Fetcher = Callable[[str, Facet], FetchResponse]


class LocalCache:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        self.path = path
        self.ttl = ttl_seconds
        self._data: Dict[str, Dict[str, object]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._data = json.load(handle)
        except Exception:
            self._data = {}

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)

    def get(self, key: str) -> Optional[List[Dict[str, str]]]:
        entry = self._data.get(key)
        if not entry:
            return None
        if time.time() - float(entry.get("timestamp", 0.0)) > self.ttl:
            self._data.pop(key, None)
            return None
        return entry.get("payload")

    def set(self, key: str, payload: List[Dict[str, str]]) -> None:
        self._data[key] = {"timestamp": time.time(), "payload": payload}
        self._persist()


class Collector:
    """Collecteur de pages web polit et cache."""

    def __init__(self, fetcher: Optional[Fetcher] = None, cache: Optional[LocalCache] = None) -> None:
        self.fetcher = fetcher or self._noop_fetcher
        self.cache = cache or LocalCache(CACHE_PATH, CACHE_TTL)

    @staticmethod
    def _noop_fetcher(query: str, facet: Facet) -> List[Dict[str, str]]:  # pragma: no cover - fonction de secours
        LOGGER.debug("Aucun fetcher fourni, retour vide pour %s", query)
        return []

    def _call_fetcher(self, query: str, facet: Facet) -> List[Dict[str, str]]:
        """Appelle le fetcher avec gestion des paramètres optionnels."""

        kwargs = {
            "timeout": REQUEST_TIMEOUT,
            "user_agent": USER_AGENT,
        }
        signature = inspect.signature(self.fetcher)
        try:
            if len(signature.parameters) > 2:
                return list(self.fetcher(query, facet, **kwargs))
        except (TypeError, ValueError):
            pass
        return list(self.fetcher(query, facet))

    def collect(
        self,
        facet: Facet,
        queries: Dict[str, List[str]],
        registry: SourceRegistry,
    ) -> List[CandidateDocument]:
        documents: List[CandidateDocument] = []
        for angle, q_list in queries.items():
            for query in q_list:
                cached = self.cache.get(query)
                if cached is None:
                    payload: List[Dict[str, str]] = []
                    for attempt in range(MAX_RETRIES + 1):
                        try:
                            payload = self._call_fetcher(query, facet)
                            break
                        except Exception as error:  # pragma: no cover - dépend de l'implémentation réseau
                            LOGGER.warning("Échec collecte (%s) tentative %s/%s", error, attempt + 1, MAX_RETRIES + 1)
                            if attempt >= MAX_RETRIES:
                                payload = []
                            else:
                                time.sleep(min(REQUEST_DELAY, 1.0))
                    self.cache.set(query, list(payload))
                    if REQUEST_DELAY:
                        time.sleep(REQUEST_DELAY)
                else:
                    payload = cached
                for raw in payload:
                    url = raw.get("url", "")
                    if not url or registry.is_blocked(url):
                        LOGGER.debug("URL rejetée car bloquée: %s", url)
                        continue
                    domain = SourceRegistry.extract_domain(url)
                    published_at = raw.get("published_at")
                    try:
                        published_dt = (
                            datetime.fromisoformat(published_at) if isinstance(published_at, str) and published_at else None
                        )
                    except ValueError:
                        published_dt = None
                    documents.append(
                        CandidateDocument(
                            url=url,
                            title=raw.get("title", ""),
                            snippet=raw.get("snippet", ""),
                            content=raw.get("content", raw.get("snippet", "")),
                            published_at=published_dt,
                            domain=domain,
                            source_type=raw.get("source_type", "unknown"),
                            evidence_level=raw.get("evidence_level", "unknown"),
                            jurisdiction=raw.get("jurisdiction", "INT"),
                            raw=dict(raw),
                            angle=angle,
                        )
                    )
        return documents


__all__ = ["CandidateDocument", "Collector", "LocalCache"]
