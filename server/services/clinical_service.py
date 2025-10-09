"""Services métier pour la mémoire clinique locale."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence

from .clinical_indexer import ClinicalIndexer
from .clinical_repo import ClinicalRepo, ClinicalRepoError, iter_patient_files

LOGGER = logging.getLogger("clinical.service")


class ClinicalServiceError(RuntimeError):
    """Erreur métier pour la mémoire clinique."""


@dataclass
class TopicMatch:
    session: str
    topic: str
    excerpt: str


class ClinicalService:
    """Expose les opérations métier sur la mémoire clinique."""

    def __init__(self, repo: ClinicalRepo | None = None, indexer: ClinicalIndexer | None = None) -> None:
        self.repo = repo or ClinicalRepo()
        self.indexer = indexer or ClinicalIndexer(self.repo)

    # ------------------------------------------------------------------
    def get_patient_overview(self, slug: str) -> Dict[str, object]:
        meta = self.repo.read_patient_meta(slug)
        payload = iter_patient_files(
            self.repo,
            slug,
            [
                "index.json",
                "milestones.json",
                "quotes.json",
                "contexts.json",
                "contradictions.json",
            ],
        )
        index_payload = payload.get("index.json") or {}
        if not index_payload:
            try:
                index_payload = self.indexer.rebuild_index(slug)
            except ClinicalRepoError:
                LOGGER.debug("[clinical] impossible de reconstruire l'index pour %s", slug, exc_info=True)
                index_payload = {}

        recent_plan = self._extract_latest_plan(slug)
        overview = {
            "meta": meta,
            "index": index_payload,
            "milestones": self._ensure_list(payload.get("milestones.json"), "milestones"),
            "quotes": self._ensure_list(payload.get("quotes.json"), "quotes"),
            "contexts": payload.get("contexts.json") or {},
            "contradictions": self._ensure_list(payload.get("contradictions.json"), "contradictions"),
            "latest_plan": recent_plan,
        }
        LOGGER.debug("[clinical] overview généré pour %s", slug)
        return overview

    def get_session_material(self, slug: str, date_or_path: str) -> Dict[str, object]:
        handle = self._resolve_session(slug, date_or_path)
        session_payload = self.repo.read_session(slug, handle.path)
        files = session_payload.get("files", {})
        return {
            "path": handle.path,
            "transcript": files.get("transcript.txt", ""),
            "segments": files.get("segments.json") or {},
            "plan": files.get("plan.txt", ""),
            "summary": files.get("summary.json") or {},
        }

    def find_topics(self, slug: str, query: str) -> Dict[str, object]:
        query = (query or "").strip().lower()
        if not query:
            return {"matches": []}
        matches: List[TopicMatch] = []
        for handle in self.repo.list_sessions(slug):
            session_payload = self.repo.read_session(slug, handle.path)
            segments = session_payload.get("files", {}).get("segments.json")
            if not isinstance(segments, dict):
                continue
            for segment in self._iter_segments(segments):
                topic = str(segment.get("topic") or "")
                text = str(segment.get("text") or "")
                if query in topic.lower() or query in text.lower():
                    matches.append(
                        TopicMatch(
                            session=handle.path,
                            topic=topic,
                            excerpt=self._build_excerpt(text, query),
                        )
                    )
        return {
            "matches": [match.__dict__ for match in matches],
        }

    # ------------------------------------------------------------------
    def update_milestones(self, slug: str, entry: Mapping[str, object]) -> Dict[str, object]:
        milestones = self.repo.read_patient_file(slug, "milestones.json") or {}
        items = self._ensure_list(milestones, "milestones")
        if not isinstance(entry, Mapping) or not entry.get("note"):
            raise ClinicalServiceError("invalid_milestone")
        items.append({"date": entry.get("date"), "note": entry.get("note")})
        milestones["milestones"] = items
        self.repo.write_patient_file(slug, "milestones.json", milestones)
        LOGGER.info("[clinical] milestone ajouté", extra={"slug": slug})
        return milestones

    def append_quote(self, slug: str, entry: Mapping[str, object]) -> Dict[str, object]:
        quotes = self.repo.read_patient_file(slug, "quotes.json") or {}
        items = self._ensure_list(quotes, "quotes")
        if not isinstance(entry, Mapping) or not entry.get("text"):
            raise ClinicalServiceError("invalid_quote")
        items.append({"date": entry.get("date"), "text": entry.get("text")})
        quotes["quotes"] = items
        self.repo.write_patient_file(slug, "quotes.json", quotes)
        LOGGER.info("[clinical] citation ajoutée", extra={"slug": slug})
        return quotes

    def update_somatic(self, slug: str, payload: Mapping[str, object]) -> Dict[str, object]:
        if not isinstance(payload, Mapping):
            raise ClinicalServiceError("invalid_somatic")
        data = {"resources": [], "tensions": [], "patterns": []}
        data.update(payload)
        self.repo.write_patient_file(slug, "somatic.json", data)
        LOGGER.info("[clinical] somatique mis à jour", extra={"slug": slug})
        return data

    def update_contradictions(self, slug: str, payload: Mapping[str, object]) -> Dict[str, object]:
        if not isinstance(payload, Mapping):
            raise ClinicalServiceError("invalid_contradictions")
        data = {"contradictions": self._ensure_list(payload, "contradictions")}
        self.repo.write_patient_file(slug, "contradictions.json", data)
        LOGGER.info("[clinical] contradictions mises à jour", extra={"slug": slug})
        return data

    def update_contexts(self, slug: str, payload: Mapping[str, object]) -> Dict[str, object]:
        if not isinstance(payload, Mapping):
            raise ClinicalServiceError("invalid_contexts")
        data = {
            "typical_situations": self._ensure_list(payload, "typical_situations"),
            "transformations": self._ensure_list(payload, "transformations"),
        }
        self.repo.write_patient_file(slug, "contexts.json", data)
        LOGGER.info("[clinical] contextes mis à jour", extra={"slug": slug})
        return data

    def update_trauma(self, slug: str, payload: Mapping[str, object]) -> Dict[str, object]:
        if not isinstance(payload, Mapping):
            raise ClinicalServiceError("invalid_trauma")
        data = dict(payload)
        self.repo.write_patient_file(slug, "trauma_profile.json", data)
        LOGGER.info("[clinical] trauma profile mis à jour", extra={"slug": slug})
        return data

    # ------------------------------------------------------------------
    def _extract_latest_plan(self, slug: str) -> Dict[str, object] | None:
        sessions = self.repo.list_sessions(slug)
        if not sessions:
            return None
        for handle in reversed(sessions):
            session_payload = self.repo.read_session(slug, handle.path)
            plan_text = session_payload.get("files", {}).get("plan.txt")
            if not plan_text:
                continue
            undone = [
                line.strip()
                for line in str(plan_text).splitlines()
                if line.strip().startswith("- [ ]")
            ]
            return {
                "session": handle.path,
                "raw": plan_text,
                "undone": undone,
            }
        return None

    def _resolve_session(self, slug: str, date_or_path: str):
        date_or_path = (date_or_path or "").strip()
        candidates = self.repo.list_sessions(slug)
        if not date_or_path and candidates:
            return candidates[-1]
        for handle in candidates:
            if handle.path == date_or_path:
                return handle
            if date_or_path and handle.path.startswith(date_or_path):
                return handle
        raise ClinicalServiceError("session_not_found")

    @staticmethod
    def _ensure_list(payload: object, key: str) -> List[Dict[str, object]]:
        if isinstance(payload, dict):
            value = payload.get(key)
        elif isinstance(payload, list):  # pragma: no cover - compat héritée
            value = payload
        else:
            value = None
        if isinstance(value, list):
            return list(value)
        return []

    @staticmethod
    def _iter_segments(payload: Mapping[str, object]) -> Iterable[Mapping[str, object]]:
        segments = payload.get("segments")
        if isinstance(segments, Sequence):
            for segment in segments:
                if isinstance(segment, Mapping):
                    yield segment

    @staticmethod
    def _build_excerpt(text: str, query: str, radius: int = 80) -> str:
        lowered = text.lower()
        pos = lowered.find(query)
        if pos == -1:
            return text[:radius]
        start = max(pos - radius // 2, 0)
        end = min(pos + len(query) + radius // 2, len(text))
        excerpt = text[start:end].strip()
        if start > 0:
            excerpt = "…" + excerpt
        if end < len(text):
            excerpt = excerpt + "…"
        return excerpt


__all__ = ["ClinicalService", "ClinicalServiceError"]

