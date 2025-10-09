"""Construction des index pour la mémoire clinique."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from typing import Dict, List, Sequence

from .clinical_repo import ClinicalRepo, ClinicalRepoError

LOGGER = logging.getLogger("clinical.indexer")


class ClinicalIndexer:
    """Construit l'index agrégé d'un patient."""

    def __init__(self, repo: ClinicalRepo) -> None:
        self.repo = repo

    def rebuild_index(self, slug: str) -> Dict[str, object]:
        sessions = self.repo.list_sessions(slug)
        aggregated_sessions: List[Dict[str, object]] = []
        for handle in sessions:
            session_payload = self.repo.read_session(slug, handle.path)
            segments_payload = session_payload.get("files", {}).get("segments.json")
            topics = self._extract_topics(segments_payload)
            aggregated_sessions.append(
                {
                    "date": self._guess_date(handle.path, segments_payload),
                    "path": handle.path,
                    "topics": topics,
                }
            )

        index_payload = {
            "patient": slug,
            "sessions": aggregated_sessions,
            "last_updated": dt.date.today().isoformat(),
        }
        self.repo.write_patient_file(slug, "index.json", index_payload)
        LOGGER.info("[clinical] index reconstruit", extra={"slug": slug, "sessions": len(aggregated_sessions)})
        return index_payload

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_topics(segments_payload: object) -> List[str]:
        topics: List[str] = []
        seen: set[str] = set()
        if isinstance(segments_payload, dict):
            items = segments_payload.get("segments")
            if isinstance(items, Sequence):
                for item in items:
                    if isinstance(item, dict):
                        topic = str(item.get("topic") or "").strip()
                        if topic and topic not in seen:
                            topics.append(topic)
                            seen.add(topic)
        return topics

    @staticmethod
    def _guess_date(path: str, segments_payload: object) -> str:
        if isinstance(segments_payload, dict):
            session_date = segments_payload.get("session_date")
            if isinstance(session_date, str) and session_date:
                return session_date
        try:
            return path.split("_")[0]
        except Exception:  # pragma: no cover - ultra défensif
            return ""


def _build_repo(instance_root: str | None = None) -> ClinicalRepo:
    return ClinicalRepo(instance_root=instance_root)


def _handle_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Reconstruit les index cliniques")
    parser.add_argument("slug", nargs="?", help="Patient à traiter")
    parser.add_argument("--all", action="store_true", dest="all_patients", help="Indexer tous les patients")
    parser.add_argument("--instance", dest="instance", help="Chemin vers instance/", default=None)
    args = parser.parse_args(argv)

    repo = _build_repo(args.instance)
    indexer = ClinicalIndexer(repo)

    if args.all_patients:
        patients = repo.list_patients()
        for patient in patients:
            slug = str(patient.get("slug") or "").strip()
            if not slug:
                continue
            try:
                indexer.rebuild_index(slug)
            except ClinicalRepoError as exc:
                LOGGER.error("[clinical] indexation impossible pour %s", slug, exc_info=True)
                return 1
        return 0

    if not args.slug:
        parser.error("slug requis si --all est absent")
    indexer.rebuild_index(args.slug)
    return 0


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - point d'entrée CLI
    try:
        return _handle_cli(argv or sys.argv[1:])
    except ClinicalRepoError as exc:  # pragma: no cover - rendu CLI
        LOGGER.error("[clinical] échec indexation", exc_info=True)
        return 1


if __name__ == "__main__":  # pragma: no cover - exécution directe
    raise SystemExit(main())


__all__ = ["ClinicalIndexer", "main"]

