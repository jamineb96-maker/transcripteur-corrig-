"""Web RAG pipeline with allowlist and provider support."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests

from .schemas import EvidenceItemWeb, SessionFacts


@dataclass
class _WebResult:
    title: str
    url: str
    snippet: str
    source: str
    author: str | None
    date: str | None


def _log_event(event: str, payload: Dict[str, object]) -> None:
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
    record.update(payload)
    try:
        journal_path = Path(__file__).resolve().parents[1] / "library" / "store" / "journal.log"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with open(journal_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # pragma: no cover
        pass


_ALLOWLIST_CACHE: Optional[List[str]] = None


def _load_allowlist() -> List[str]:
    global _ALLOWLIST_CACHE
    if _ALLOWLIST_CACHE is not None:
        return _ALLOWLIST_CACHE
    path = os.getenv("RAG_WEB_ALLOWLIST") or str(
        Path(__file__).resolve().parents[1] / "research" / "allowlist.txt"
    )
    entries: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                domain = line.strip()
                if domain and not domain.startswith("#"):
                    entries.append(domain.lower())
    except FileNotFoundError:
        entries = []
    _ALLOWLIST_CACHE = entries
    return entries


def _is_allowed(url: str) -> bool:
    domain = urlparse(url).netloc.lower()
    allowlist = _load_allowlist()
    return any(domain == allowed or domain.endswith("." + allowed) for allowed in allowlist)


def _parse_date(raw_date: Optional[str]) -> Optional[datetime]:
    if not raw_date:
        return None
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw_date[: len(fmt)], fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except Exception:
        return None


def _within_recency(raw_date: Optional[str]) -> bool:
    days_limit = int(os.getenv("RAG_WEB_RECENCY_DAYS", "1095") or 1095)
    if days_limit <= 0:
        return True
    parsed = _parse_date(raw_date)
    if parsed is None:
        return True
    return parsed >= datetime.utcnow() - timedelta(days=days_limit)


def _reliability_tag(domain: str, outlet: str) -> str:
    domain = domain.lower()
    outlet = (outlet or "").lower()
    strong_domains = {
        "nejm.org",
        "thelancet.com",
        "nature.com",
        "inserm.fr",
        "who.int",
        "has-sante.fr",
        "santepubliquefrance.fr",
    }
    professional_domains = {"gouv.fr", "ansm.sante.fr", "ap-hm.fr", "chuv.ch", "chu-lyon.fr"}
    low_signals = {"blog", "wordpress", "medium.com", "substack", "reddit", "forum"}
    if any(domain.endswith(sd) for sd in strong_domains) or "revue" in outlet:
        return "fort"
    if any(domain.endswith(pd) for pd in professional_domains) or "universit" in outlet:
        return "moyen"
    if any(token in domain for token in low_signals):
        return "faible"
    return "moyen"


def _build_queries(facts: SessionFacts) -> List[str]:
    queries: List[str] = []
    for theme in facts.themes[:4]:
        queries.append(f"{theme} evidence clinique")
    for med in facts.meds[:3]:
        name = med.get("name") if isinstance(med, dict) else None
        if name:
            queries.append(f"{name} effets et études")
    for ask in facts.asks[:2]:
        queries.append(ask)
    if not queries:
        queries.append("santé mentale cliniciens evidence")
    while len(queries) < 4:
        queries.append(f"analyse situated care {facts.patient}")
    return queries[:8]


def _request_serpapi(query: str, max_results: int) -> List[_WebResult]:
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return []
    params = {
        "engine": "google",
        "q": query,
        "num": max_results,
        "api_key": api_key,
    }
    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    hits = []
    for item in data.get("organic_results", []):
        url = item.get("link") or ""
        if not url:
            continue
        hits.append(
            _WebResult(
                title=item.get("title", ""),
                url=url,
                snippet=item.get("snippet", ""),
                source=item.get("source", ""),
                author=item.get("rich_snippet", {}).get("top", {}).get("name")
                if isinstance(item.get("rich_snippet"), dict)
                else None,
                date=item.get("date"),
            )
        )
    return hits


def _request_bing(query: str, max_results: int) -> List[_WebResult]:
    api_key = os.getenv("BING_API_KEY")
    if not api_key:
        return []
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "count": max_results, "mkt": "fr-FR"}
    try:
        response = requests.get(
            "https://api.bing.microsoft.com/v7.0/search", params=params, headers=headers, timeout=15
        )
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    hits = []
    for item in data.get("webPages", {}).get("value", []):
        url = item.get("url") or ""
        if not url:
            continue
        hits.append(
            _WebResult(
                title=item.get("name", ""),
                url=url,
                snippet=item.get("snippet", ""),
                source=item.get("displayUrl", ""),
                author=None,
                date=item.get("dateLastCrawled"),
            )
        )
    return hits


def _request_google_cse(query: str, max_results: int) -> List[_WebResult]:
    api_key = os.getenv("GOOGLE_CSE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_ID")
    if not api_key or not cx:
        return []
    params = {"key": api_key, "cx": cx, "q": query, "num": max_results}
    try:
        response = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    hits = []
    for item in data.get("items", []):
        url = item.get("link") or ""
        if not url:
            continue
        pagemap = item.get("pagemap", {}) if isinstance(item.get("pagemap"), dict) else {}
        metadata = pagemap.get("metatags", [{}])[0] if pagemap else {}
        hits.append(
            _WebResult(
                title=item.get("title", ""),
                url=url,
                snippet=item.get("snippet", ""),
                source=item.get("displayLink", ""),
                author=metadata.get("author"),
                date=metadata.get("article:published_time") or metadata.get("date"),
            )
        )
    return hits


def _fetch(provider: str, query: str, max_results: int) -> List[_WebResult]:
    provider = provider.lower()
    if provider == "serpapi":
        return _request_serpapi(query, max_results)
    if provider == "bing":
        return _request_bing(query, max_results)
    if provider == "google_cse":
        return _request_google_cse(query, max_results)
    return []


def _short_quote(snippet: str) -> str:
    text = (snippet or "").strip()
    if len(text) <= 280:
        return text
    return text[:277].rstrip() + "…"


def _make_evidence(raw: _WebResult) -> Optional[EvidenceItemWeb]:
    if not raw.url:
        return None
    if not _is_allowed(raw.url):
        return None
    if not _within_recency(raw.date):
        return None
    domain = urlparse(raw.url).netloc
    outlet = raw.source or domain
    quote = _short_quote(raw.snippet)
    if not quote:
        quote = "Citation non fournie"
    reliability = _reliability_tag(domain, outlet)
    author = raw.author or ""
    date = raw.date or ""
    claim = quote if len(quote) <= 200 else quote[:197] + "…"
    return EvidenceItemWeb(
        title=raw.title or outlet,
        author=author,
        outlet=outlet,
        date=date,
        url=raw.url,
        quote=quote,
        claim=claim,
        reliability_tag=reliability,
    )


def search_web_evidence(session_facts: SessionFacts, max_results: int = 6) -> List[EvidenceItemWeb]:
    provider = (os.getenv("RAG_WEB_PROVIDER", "none") or "none").lower()
    allowlist = _load_allowlist()
    if provider == "none" or not allowlist:
        _log_event(
            "post_v2_rag_web",
            {
                "provider": provider,
                "returned": 0,
                "filtered_out": 0,
                "ms": 0,
                "warning": "disabled" if provider == "none" else "allowlist_empty",
            },
        )
        return []
    queries = _build_queries(session_facts)
    if not queries:
        _log_event(
            "post_v2_rag_web",
            {
                "provider": provider,
                "returned": 0,
                "filtered_out": 0,
                "ms": 0,
                "warning": "no_queries",
            },
        )
        return []
    start = time.perf_counter()
    items: List[EvidenceItemWeb] = []
    filtered_out = 0
    seen_urls: set[str] = set()
    for query in queries:
        for raw in _fetch(provider, query, max_results):
            entry = _make_evidence(raw)
            if entry is None:
                filtered_out += 1
                continue
            if entry.url in seen_urls:
                continue
            seen_urls.add(entry.url)
            items.append(entry)
            if len(items) >= max_results:
                break
        if len(items) >= max_results:
            break
    duration_ms = int((time.perf_counter() - start) * 1000)
    _log_event(
        "post_v2_rag_web",
        {
            "provider": provider,
            "returned": len(items),
            "filtered_out": filtered_out,
            "ms": duration_ms,
        },
    )
    return items[:max(3, min(max_results, len(items)))]


__all__ = ["search_web_evidence"]
