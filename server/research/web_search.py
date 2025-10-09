"""Simple web search helpers for the post‑session API.

This module provides a small abstraction over multiple providers
for performing web searches in a synchronous manner.  It
supports DuckDuckGo (HTML scraping by default), SerpAPI and
Microsoft Bing if the appropriate API keys are present.  The
default implementation uses the lightweight HTML interface of
DuckDuckGo, which does not require an API key.  When the
provider is ``ddg`` and no results are returned, a fallback to
Wikipedia is attempted using the public MediaWiki API for the
requested language.

Functions in this module are pure and do not depend on Flask.
They should be imported by the API blueprint in
``server/blueprints/research_web.py``.

Environment variables
---------------------

``SEARCH_PROVIDER``
    Controls which provider is used.  Accepted values are
    ``ddg`` (default), ``serpapi`` and ``bing``.  Any other
    value falls back to ``ddg``.

``SERPAPI_KEY``
    API key for the SerpAPI search endpoint.  Required when
    ``SEARCH_PROVIDER=serpapi``.

``BING_KEY``
    API key for Microsoft Bing's search API.  Required when
    ``SEARCH_PROVIDER=bing``.

``REQUEST_TIMEOUT_SECONDS``
    Timeout applied to all outgoing HTTP requests.  Defaults to
    8 seconds.

The result format is a list of dictionaries with the keys
``title`` (string), ``url`` (string), ``snippet`` (string) and
``source`` (string indicating the provider).
"""

from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
from typing import List, Dict, Optional

import requests

try:  # pragma: no cover - only used on Windows to avoid SSL failures
    import certifi  # type: ignore
except Exception:  # pragma: no cover
    certifi = None  # type: ignore


def _get_timeout() -> float:
    """Resolve the request timeout from the environment or use a sane default."""
    raw = os.getenv("REQUEST_TIMEOUT_SECONDS", "8")
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):  # pragma: no cover
        return 8.0


def _request_session() -> requests.Session:
    """Create a requests session with a sensible user‑agent and TLS settings."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/99.0.4844.84 Safari/537.36"
            ),
            "Accept-Language": os.getenv("SEARCH_LANG", "en"),
        }
    )
    return session


def _parse_ddg_results(html_text: str, max_results: int) -> List[Dict[str, str]]:
    """Extract search results from DuckDuckGo HTML.

    The HTML interface of DuckDuckGo returns results in a list of
    ``result__a`` links.  We extract the URL and text of the link
    for the title and then attempt to find a nearby snippet.
    """
    results: List[Dict[str, str]] = []
    # Find all result links
    link_pattern = re.compile(
        r'<a[^>]*class="[^\"]*result__a[^\"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.S,
    )
    snippet_pattern = re.compile(
        r'<a[^>]*class="[^\"]*result__snippet[^\"]*"[^>]*>(.*?)</a>',
        re.S,
    )
    links = link_pattern.findall(html_text)
    snippets = snippet_pattern.findall(html_text)
    for idx, (href, title_html) in enumerate(links[: max_results]):
        title = html.unescape(re.sub("<.*?>", "", title_html)).strip()
        url = html.unescape(href)
        snippet = ""
        if idx < len(snippets):
            snippet_raw = snippets[idx]
            snippet = html.unescape(re.sub("<.*?>", "", snippet_raw)).strip()
        results.append({"title": title, "url": url, "snippet": snippet, "source": "ddg"})
    return results


def _search_ddg(query: str, lang: str, max_results: int) -> List[Dict[str, str]]:
    """Perform a search using DuckDuckGo's HTML interface."""
    session = _request_session()
    timeout = _get_timeout()
    # Use the lite HTML interface.  Sending the language via the 'kl' parameter
    # sets the region and language; e.g. 'fr-fr' for French results.
    region = f"{lang.lower()}-{lang.lower()}" if len(lang) == 2 else lang.lower()
    params = {"q": query, "kl": region}
    url = "https://html.duckduckgo.com/html/"
    try:
        resp = session.get(url, params=params, timeout=timeout, verify=certifi.where() if certifi else True)
        if resp.status_code != 200:  # pragma: no cover - network
            return []
        return _parse_ddg_results(resp.text, max_results)
    except Exception:  # pragma: no cover - network
        return []


def _search_serpapi(query: str, lang: str, max_results: int) -> List[Dict[str, str]]:
    """Perform a search using SerpAPI if configured."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        return []
    timeout = _get_timeout()
    params = {
        "q": query,
        "num": max_results,
        "hl": lang,
        "api_key": api_key,
    }
    url = "https://serpapi.com/search.json"
    try:
        resp = requests.get(url, params=params, timeout=timeout, verify=certifi.where() if certifi else True)
        data = resp.json()
        results: List[Dict[str, str]] = []
        for item in data.get("organic_results", [])[:max_results]:
            title = item.get("title") or ""
            url_result = item.get("link") or item.get("url") or ""
            snippet = item.get("snippet") or item.get("snippet_highlighted_words", [""])[0] if isinstance(item.get("snippet_highlighted_words"), list) else ""
            results.append({"title": title, "url": url_result, "snippet": snippet, "source": "serpapi"})
        return results
    except Exception:  # pragma: no cover - network
        return []


def _search_bing(query: str, lang: str, max_results: int) -> List[Dict[str, str]]:
    """Perform a search using the Bing Web Search API if configured."""
    api_key = os.getenv("BING_KEY")
    if not api_key:
        return []
    timeout = _get_timeout()
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    params = {"q": query, "mkt": f"{lang}-{lang}", "count": max_results}
    url = "https://api.bing.microsoft.com/v7.0/search"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout, verify=certifi.where() if certifi else True)
        data = resp.json()
        results: List[Dict[str, str]] = []
        for item in data.get("webPages", {}).get("value", [])[:max_results]:
            title = item.get("name") or ""
            url_result = item.get("url") or ""
            snippet = item.get("snippet") or ""
            results.append({"title": title, "url": url_result, "snippet": snippet, "source": "bing"})
        return results
    except Exception:  # pragma: no cover - network
        return []


def _search_wikipedia(query: str, lang: str, max_results: int) -> List[Dict[str, str]]:
    """Fallback search using the MediaWiki API if no web results are found.

    This will search the given language of Wikipedia and return page
    titles and snippets.  It is a last resort and should not be
    considered authoritative.
    """
    timeout = _get_timeout()
    endpoint = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "opensearch",
        "search": query,
        "limit": max_results,
        "namespace": "0",
        "format": "json",
    }
    try:
        resp = requests.get(endpoint, params=params, timeout=timeout, verify=certifi.where() if certifi else True)
        data = resp.json()
        titles = data[1] if isinstance(data, list) and len(data) > 1 else []
        descriptions = data[2] if isinstance(data, list) and len(data) > 2 else []
        urls = data[3] if isinstance(data, list) and len(data) > 3 else []
        results: List[Dict[str, str]] = []
        for title, desc, url in zip(titles, descriptions, urls):
            results.append({"title": title or query, "url": url or "", "snippet": desc or "", "source": "wikipedia"})
        return results
    except Exception:  # pragma: no cover - network
        return []


def search(query: str, lang: str = "fr", max_results: int = 5) -> List[Dict[str, str]]:
    """Search the web using the configured provider.

    Parameters
    ----------
    query: str
        The search query.  If empty or blank, an empty list is returned.
    lang: str, optional
        A language code (e.g. ``fr`` or ``en``) used where supported by
        the provider.  Defaults to ``fr``.
    max_results: int, optional
        Maximum number of results to return.  Defaults to 5 and must be
        greater than zero.

    Returns
    -------
    List[Dict[str, str]]
        A list of dictionaries each containing ``title``, ``url``,
        ``snippet`` and ``source`` keys.
    """
    query = (query or "").strip()
    if not query:
        return []
    try:
        max_results = max(1, int(max_results))
    except (TypeError, ValueError):  # pragma: no cover
        max_results = 5
    provider = (os.getenv("SEARCH_PROVIDER") or "ddg").strip().lower()
    results: List[Dict[str, str]] = []
    if provider == "serpapi":
        results = _search_serpapi(query, lang, max_results)
    elif provider == "bing":
        results = _search_bing(query, lang, max_results)
    else:
        # default: ddg
        results = _search_ddg(query, lang, max_results)
    # Fallback to Wikipedia if no results found
    if not results:
        results = _search_wikipedia(query, lang, max_results)
    return results


__all__ = ["search"]