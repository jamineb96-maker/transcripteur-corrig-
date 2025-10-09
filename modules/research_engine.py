# [pipeline-v3 begin]
"""Moteur de recherche pré-séance v3 (librairie locale + OpenAI web)."""

from __future__ import annotations

import json
import logging
import os
import pathlib
from typing import Any, Dict, List, Optional, Tuple

from server.services.openai_client import DEFAULT_TEXT_MODEL, get_openai_client

from .research_v2 import ResearchOptions, run_research_v2

LIBRARY_DIR = os.environ.get("LIBRARY_DIR", "./library")
OPENAI_MODEL_WEB = os.environ.get("OPENAI_MODEL_WEB", DEFAULT_TEXT_MODEL)
ALLOW_INTERNET_DEFAULT = os.environ.get("ALLOW_INTERNET_DEFAULT", "true").lower() == "true"

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTANCE_DIR = pathlib.Path(os.environ.get("ASSIST_INSTANCE_PATH", PROJECT_ROOT / "instance"))
JOURNAL_INDEX_PATH = INSTANCE_DIR / "journal_critique" / "index.jsonl"
JOURNAL_INDEX_MIRROR = INSTANCE_DIR / "search_indexes" / "journal_critique.jsonl"

LOGGER = logging.getLogger("assist.research")

_JOURNAL_CACHE: Optional[List[Dict[str, Any]]] = None


def _read_jsonl(path: pathlib.Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not path.exists():
        return items
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, raw in enumerate(handle, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    LOGGER.warning("Index JSONL invalide (%s:%d): %s", path, line_no, exc)
                    continue
                if isinstance(data, dict):
                    items.append(data)
    except OSError as exc:  # pragma: no cover - robustesse
        LOGGER.warning("Lecture impossible %s: %s", path, exc)
    return items


def _load_journal_index() -> List[Dict[str, Any]]:
    global _JOURNAL_CACHE
    if _JOURNAL_CACHE is not None:
        return _JOURNAL_CACHE
    primary = _read_jsonl(JOURNAL_INDEX_PATH)
    if primary:
        _JOURNAL_CACHE = primary
    else:
        _JOURNAL_CACHE = _read_jsonl(JOURNAL_INDEX_MIRROR)
    return _JOURNAL_CACHE or []


def invalidate_journal_cache() -> None:
    global _JOURNAL_CACHE
    _JOURNAL_CACHE = None


def search_journal(query: str, k: int = 4) -> List[Dict[str, Any]]:
    """Search inside the journal index."""

    items = _load_journal_index()
    if not items:
        return []
    query_terms = [token.lower() for token in query.split() if token]
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for item in items:
        haystack = " ".join(
            [
                str(item.get("title", "")),
                str(item.get("excerpt", "")),
                " ".join(item.get("tags", []) or []),
                " ".join(item.get("concepts_norm", []) or []),
            ]
        ).lower()
        score = 0.0
        if query_terms:
            for term in query_terms:
                if term in haystack:
                    score += 1.0
        else:
            score = 1.0
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda entry: (entry[0], str(entry[1].get("updated_at", ""))), reverse=True)
    return [
        {
            "id": result.get("id"),
            "title": result.get("title"),
            "excerpt": result.get("excerpt"),
            "tags": result.get("tags", []),
            "updated_at": result.get("updated_at"),
            "source": "journal_critique",
        }
        for _, result in scored[:k]
    ]


def search_local_library(query: str, k: int = 6) -> List[Dict[str, str]]:
    """Parcourt la librairie locale et renvoie des extraits pertinents."""

    results: List[Dict[str, str]] = []
    if os.environ.get("RESEARCH_V2", "").strip().lower() in {"1", "true", "yes"}:
        try:
            from server.tabs.pre_session.research_engine_v2 import search_evidence as search_evidence_v2  # type: ignore

            LOGGER.info("[research] v2=True query='%s'", query)
            hits = search_evidence_v2(query, k=k)
        except Exception:  # pragma: no cover - robustesse
            LOGGER.warning("library_v2_search_failed", exc_info=True)
        else:
            for hit in hits:
                pages = ""
                start_page = hit.get("page_start")
                end_page = hit.get("page_end")
                if isinstance(start_page, int) and isinstance(end_page, int) and start_page and end_page:
                    pages = f"p. {start_page}" if start_page == end_page else f"p. {start_page}-{end_page}"
                context = f"{hit.get('title', '')} {pages}".strip() or "Bibliothèque clinique"
                results.append(
                    {
                        "source": hit.get("doc_id") or hit.get("title", ""),
                        "extrait": hit.get("extract", ""),
                        "contexte": context,
                        "score": hit.get("score"),
                        "notions": hit.get("notions", []),
                    }
                )
            if results:
                return results
    try:  # import local pour garder la dépendance optionnelle
        from pdfminer.high_level import extract_text as pdf_extract_text
    except Exception:  # pragma: no cover - dépendance optionnelle absente
        pdf_extract_text = None

    base_path = pathlib.Path(LIBRARY_DIR)
    if not base_path.exists():
        return results

    for path in base_path.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in {".md", ".txt", ".pdf"}:
            continue
        try:
            if ext == ".pdf" and pdf_extract_text is not None:
                text = pdf_extract_text(str(path)) or ""
            else:
                text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # pragma: no cover - robustesse
            continue
        text = " ".join(text.split())
        if not text:
            continue
        if query:
            pass  # filtrage minimal, conservé volontairement neutre
        excerpt = text[:900]
        results.append(
            {
                "source": str(path.relative_to(base_path)),
                "extrait": excerpt,
                "contexte": "Librairie locale",
            }
        )
        if len(results) >= k:
            break
    return results

def search_web_openai(query: str, k: int = 3, recency_days: int = 5 * 365) -> List[Dict[str, str]]:
    """Utilise l'API OpenAI (outil web) pour obtenir des synthèses sans URL."""

    if not query:
        return []
    try:
        client = get_openai_client()
        if client is None:
            return []
        messages = [
            {
                "role": "system",
                "content": "Tu es un assistant de recherche. Réponds de manière concise.",
            },
            {
                "role": "user",
                "content": (
                    f"Question: {query}\nFenêtre: {recency_days} jours\nRenvoie {k} items."
                ),
            },
        ]
        response = client.chat.completions.create(
            model=OPENAI_MODEL_WEB,
            messages=messages,
            temperature=0.2,
        )
        text = response.choices[0].message.content or ""
        return [{"title": "Synthèse", "url": "", "snippet": text}]
    except Exception:
        return []


def _adapt_v2_to_legacy(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Transforme la sortie v2 vers la structure héritée."""

    internet: List[Dict[str, str]] = []
    for facet in payload.get("facets", []):
        for citation in facet.get("citations", []):
            internet.append(
                {
                    "title": citation.get("title", ""),
                    "url": citation.get("url", ""),
                    "snippet": citation.get("comment", ""),
                    "facet": facet.get("name"),
                    "status": facet.get("status"),
                }
            )

    notes = (
        "Résultat issu du moteur v2. Utiliser le bloc research_v2 pour le suivi complet. "
        "Les facettes marquées 'insuffisant' ne sont pas encore prêtes pour affichage."
    )

    return {
        "local_library": [],
        "internet": internet,
        "notes_integration": notes,
        "research_v2": payload,
    }


def run_research(
    plan: Dict[str, Any],
    raw_context: Dict[str, str],
    allow_internet: bool = ALLOW_INTERNET_DEFAULT,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Orchestre la recherche locale puis web si nécessaire."""

    feature_flag = os.environ.get("PRESESSION_RESEARCH_V2", "false").lower() == "true"
    options = options or {}
    if feature_flag or options.get("use_v2"):
        research_options = ResearchOptions(
            location=options.get("location", "France"),
            sensitivity=options.get("sensitivity", "standard"),
            enable_v2=True,
        )
        payload = run_research_v2(plan=plan, raw_context=raw_context, options=research_options)
        return _adapt_v2_to_legacy(payload)

    query = " ".join(
        [
            plan.get("orientation", ""),
            plan.get("objectif_prioritaire", ""),
            plan.get("synthese", {}).get("tensions_principales", ""),
        ]
    ).strip()

    local_results = search_local_library(query, k=6)
    journal_results = search_journal(query, k=4)
    internet_results: List[Dict[str, str]] = []
    if allow_internet and len(local_results) < 2:
        internet_results = search_web_openai(query, k=3)

    notes = (
        "Ces éléments sont destinés à nourrir le prompt final. "
        "Ils doivent rester strictement reliés à l'orientation et à l'objectif prioritaire, "
        "centrés sur une lecture matérialiste/critique (conditions de vie, travail, droits, institutions), "
        "et éviter toute prescription TCC (devoirs, hiérarchies d'exposition, échelles chiffrées)."
    )

    return {
        "local_library": [
            {"source": item["source"], "extrait": item["extrait"], "contexte": item["contexte"]}
            for item in local_results
        ],
        "internet": internet_results,
        "journal_critique": journal_results,
        "notes_integration": notes,
    }


__all__ = [
    "search_local_library",
    "search_web_openai",
    "run_research",
    "search_journal",
    "invalidate_journal_cache",
]
# [pipeline-v3 end]
