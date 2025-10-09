"""Accès disque pour la mémoire clinique locale.

Ce module encapsule les opérations d'E/S sur ``instance/records`` sans
introduire de logique métier.  Il fournit un dépôt minimaliste capable de
lister les patients, leurs séances et de lire/écrire les fichiers JSON ou
texte attendus par les autres services.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping

from server.util.slug import slugify

LOGGER = logging.getLogger("clinical.repo")


PATIENT_FILES = {
    "patient_meta.json",
    "index.json",
    "milestones.json",
    "quotes.json",
    "somatic.json",
    "contradictions.json",
    "contexts.json",
    "trauma_profile.json",
}

SESSION_FILES = {
    "transcript.txt",
    "segments.json",
    "plan.txt",
    "summary.json",
}


class ClinicalRepoError(RuntimeError):
    """Erreur générique pour le dépôt clinique."""


@dataclass(frozen=True)
class SessionHandle:
    """Représentation légère d'une séance disponible."""

    slug: str
    path: str
    directory: Path


def _as_path(base: Path | str | None) -> Path:
    if base is None:
        root = Path(__file__).resolve().parents[2] / "instance"
    else:
        root = Path(base)
    return root


class ClinicalRepo:
    """Stockage local des données cliniques."""

    def __init__(self, instance_root: Path | str | None = None) -> None:
        base = _as_path(instance_root)
        self.instance_root = base
        self.records_root = (base / "records").resolve()
        self.records_root.mkdir(parents=True, exist_ok=True)
        LOGGER.debug("[clinical] dépôt initialisé dans %s", self.records_root)

    # ------------------------------------------------------------------
    # Points d'extension pour un chiffrement ultérieur
    def read_bytes(self, path: Path) -> bytes:
        """Lit un fichier binaire.

        Cette méthode constitue un point d'extension si un chiffrement doit
        être implémenté par la suite.
        """

        return path.read_bytes()

    def write_bytes(self, path: Path, payload: bytes) -> None:
        """Écrit un fichier binaire (point d'extension)."""

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    # ------------------------------------------------------------------
    def _patient_dir(self, slug: str) -> Path:
        safe_slug = slugify(slug or "")
        if not safe_slug:
            raise ClinicalRepoError("invalid_patient_slug")
        patient_dir = (self.records_root / safe_slug).resolve()
        try:
            patient_dir.relative_to(self.records_root)
        except ValueError as exc:  # pragma: no cover - garde supplémentaire
            raise ClinicalRepoError("patient_dir_out_of_bounds") from exc
        patient_dir.mkdir(parents=True, exist_ok=True)
        return patient_dir

    def _session_dir(self, slug: str, session_path: str) -> Path:
        candidate = Path(session_path)
        safe_parts = []
        for part in candidate.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise ClinicalRepoError("invalid_session_path")
            safe_parts.append(part)
        if not safe_parts:
            raise ClinicalRepoError("invalid_session_path")
        directory = self._patient_dir(slug) / Path(*safe_parts)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # ------------------------------------------------------------------
    def list_patients(self) -> List[Dict[str, object]]:
        """Retourne une liste minimale des patients disponibles."""

        patients: List[Dict[str, object]] = []
        if not self.records_root.exists():
            return patients
        for child in sorted(self.records_root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            slug = child.name
            meta = self.read_patient_meta(slug)
            display_name = meta.get("display_name") or meta.get("displayName") or slug
            patients.append({"slug": slug, "display_name": display_name})
        return patients

    def read_patient_meta(self, slug: str) -> Dict[str, object]:
        return self._read_patient_json(slug, "patient_meta.json")

    def write_patient_meta(self, slug: str, payload: Mapping[str, object]) -> None:
        self._write_patient_json(slug, "patient_meta.json", payload)

    def list_sessions(self, slug: str) -> List[SessionHandle]:
        directory = self._patient_dir(slug)
        sessions: List[SessionHandle] = []
        for child in sorted(directory.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            relative = child.relative_to(directory)
            sessions.append(SessionHandle(slug=slug, path=str(relative).replace("\\", "/"), directory=child))
        return sessions

    def read_session(self, slug: str, session_path: str) -> Dict[str, object]:
        directory = self._session_dir(slug, session_path)
        data: Dict[str, object] = {"path": session_path, "files": {}}
        files: MutableMapping[str, object] = {}
        for name in SESSION_FILES:
            file_path = directory / name
            if not file_path.exists():
                continue
            if name.endswith(".json"):
                files[name] = self._read_json_file(file_path)
            else:
                files[name] = self._read_text_file(file_path)
        data["files"] = files
        return data

    def write_session_files(self, slug: str, session_path: str, payload: Mapping[str, object]) -> None:
        directory = self._session_dir(slug, session_path)
        for name, content in payload.items():
            if name not in SESSION_FILES:
                raise ClinicalRepoError(f"unsupported_session_file:{name}")
            file_path = directory / name
            if name.endswith(".json"):
                self._write_json_file(file_path, content)
            else:
                self._write_text_file(file_path, content)
        LOGGER.info("[clinical] fichiers séance mis à jour", extra={"slug": slug, "session": session_path})

    # ------------------------------------------------------------------
    def _read_patient_json(self, slug: str, filename: str) -> Dict[str, object]:
        if filename not in PATIENT_FILES:
            raise ClinicalRepoError(f"unsupported_patient_file:{filename}")
        path = self._patient_dir(slug) / filename
        if not path.exists():
            return {}
        return self._read_json_file(path)

    def _write_patient_json(self, slug: str, filename: str, payload: Mapping[str, object]) -> None:
        if filename not in PATIENT_FILES:
            raise ClinicalRepoError(f"unsupported_patient_file:{filename}")
        path = self._patient_dir(slug) / filename
        self._write_json_file(path, payload)
        LOGGER.info("[clinical] fichier patient mis à jour", extra={"slug": slug, "file": filename})

    def read_patient_file(self, slug: str, filename: str) -> Dict[str, object] | str | None:
        if filename in PATIENT_FILES:
            return self._read_patient_json(slug, filename)
        raise ClinicalRepoError(f"unsupported_patient_file:{filename}")

    def write_patient_file(self, slug: str, filename: str, payload: object) -> None:
        if filename not in PATIENT_FILES:
            raise ClinicalRepoError(f"unsupported_patient_file:{filename}")
        path = self._patient_dir(slug) / filename
        self._write_json_file(path, payload)

    # ------------------------------------------------------------------
    def _read_json_file(self, path: Path) -> Dict[str, object]:
        try:
            data = json.loads(self.read_bytes(path).decode("utf-8"))
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as exc:
            LOGGER.warning("[clinical] JSON invalide: %s", path, exc_info=True)
            raise ClinicalRepoError("invalid_json") from exc
        if isinstance(data, dict):
            return data
        return {}

    def _write_json_file(self, path: Path, payload: object) -> None:
        try:
            serialised = json.dumps(payload, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as exc:
            raise ClinicalRepoError("unserialisable_payload") from exc
        self.write_bytes(path, serialised.encode("utf-8"))

    def _read_text_file(self, path: Path) -> str:
        try:
            return self.read_bytes(path).decode("utf-8")
        except FileNotFoundError:
            return ""

    def _write_text_file(self, path: Path, payload: object) -> None:
        text = "" if payload is None else str(payload)
        self.write_bytes(path, text.encode("utf-8"))


def iter_patient_files(repo: ClinicalRepo, slug: str, filenames: Iterable[str]) -> Dict[str, object]:
    """Lecture utilitaire de plusieurs fichiers patient en une fois."""

    output: Dict[str, object] = {}
    for filename in filenames:
        try:
            output[filename] = repo.read_patient_file(slug, filename)
        except ClinicalRepoError:
            LOGGER.debug("[clinical] lecture ignorée pour %s/%s", slug, filename, exc_info=True)
    return output


__all__ = [
    "ClinicalRepo",
    "ClinicalRepoError",
    "PATIENT_FILES",
    "SESSION_FILES",
    "SessionHandle",
    "iter_patient_files",
]

