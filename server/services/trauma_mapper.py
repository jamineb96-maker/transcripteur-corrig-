"""Service de cartographie traumatique."""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Mapping

from .clinical_repo import ClinicalRepo

LOGGER = logging.getLogger("trauma.mapper")


class TraumaMapperError(RuntimeError):
    """Erreur pour le module de cartographie traumatique."""


class TraumaMapper:
    """Expose les opérations liées aux profils traumatiques."""

    def __init__(self, repo: ClinicalRepo | None = None) -> None:
        self.repo = repo or ClinicalRepo()

    def get_trauma_profile(self, slug: str) -> Dict[str, object]:
        profile = self.repo.read_patient_file(slug, "trauma_profile.json") or {}
        somatic = self.repo.read_patient_file(slug, "somatic.json") or {}
        payload = {"profile": profile, "somatic": somatic}
        LOGGER.debug("[trauma] profil chargé pour %s", slug)
        return payload

    def suggest_interpretations(self, slug: str, signals: Iterable[str]) -> Dict[str, object]:
        profile = self.repo.read_patient_file(slug, "trauma_profile.json") or {}
        somatic = self.repo.read_patient_file(slug, "somatic.json") or {}
        patterns = profile.get("core_patterns") if isinstance(profile, dict) else []
        if not isinstance(patterns, list):
            patterns = []

        normalised_signals = {self._normalise_signal(signal) for signal in signals if signal}
        interpretations: List[Dict[str, object]] = []

        for pattern in patterns:
            if not isinstance(pattern, Mapping):
                continue
            matches = self._match_pattern(pattern, normalised_signals)
            if not matches:
                continue
            confidence = "modérée" if len(matches) > 1 else "faible"
            summary = self._build_summary(pattern, matches, somatic)
            interpretations.append(
                {
                    "pattern": pattern.get("name"),
                    "confidence": confidence,
                    "matching_signals": sorted(matches),
                    "summary": summary,
                }
            )

        LOGGER.debug(
            "[trauma] %d interprétations proposées pour %s",
            len(interpretations),
            slug,
        )
        return {"interpretations": interpretations, "somatic": somatic}

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_signal(value: str) -> str:
        return str(value or "").strip().lower()

    def _match_pattern(self, pattern: Mapping[str, object], signals: Iterable[str]) -> List[str]:
        candidate_sets = []
        for key in ("triggers", "bodily_signals"):
            raw = pattern.get(key)
            if isinstance(raw, list):
                candidate_sets.extend(self._normalise_signal(entry) for entry in raw if entry)
        matches = sorted({signal for signal in signals if signal and signal in candidate_sets})
        return matches

    def _build_summary(self, pattern: Mapping[str, object], matches: List[str], somatic: Mapping[str, object]) -> str:
        base = pattern.get("description") or pattern.get("name") or ""
        window = pattern.get("windows_of_feasibility")
        resources = somatic.get("resources") if isinstance(somatic, Mapping) else None
        parts: List[str] = []
        if base:
            parts.append(str(base))
        if matches:
            parts.append("Signaux associés : " + ", ".join(matches))
        if isinstance(window, list) and window:
            parts.append("Fenêtres de faisabilité : " + ", ".join(str(item) for item in window))
        if isinstance(resources, list) and resources:
            parts.append("Ressources corporelles mobilisables : " + ", ".join(str(item) for item in resources))
        if not parts:
            return "Interprétation à préciser avec la clinique."
        return " ".join(parts)


__all__ = ["TraumaMapper", "TraumaMapperError"]

