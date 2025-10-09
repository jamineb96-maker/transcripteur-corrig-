"""Centralized loader for Google Calendar OAuth configuration.

Ce module regroupe la détection des identifiants OAuth Google Calendar afin
que l'application puisse fournir des diagnostics homogènes. Il sait lire les
variables d'environnement, un JSON fourni directement, ainsi que les fichiers
placés dans le répertoire ``instance``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from flask import current_app

__all__ = [
    "ResolvedGCalConfig",
    "GCalConfigError",
    "MissingClientSecrets",
    "InvalidClientConfiguration",
    "RedirectUriNotRegistered",
    "ClientTypeMismatch",
    "resolve_client_config",
    "build_env_presence",
]

DEFAULT_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_REDIRECT = "http://127.0.0.1:1421/agenda/gcal/oauth2callback"


@dataclass(frozen=True)
class ResolvedGCalConfig:
    """Resolved configuration ready to be given to ``Flow``."""

    client_config: Dict[str, Any]
    client_type: str
    redirect_uri: str
    redirect_uri_ok: bool
    source: str
    env_vars_present: Dict[str, bool]


class GCalConfigError(RuntimeError):
    """Base class for configuration errors providing structured metadata."""

    def __init__(self, reason: str, message: str, *, client_type: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.client_type = client_type


class MissingClientSecrets(GCalConfigError):
    def __init__(self) -> None:
        super().__init__("missing_client_secret", "Google OAuth client secret is missing")


class InvalidClientConfiguration(GCalConfigError):
    def __init__(self, message: str, *, client_type: str | None = None) -> None:
        super().__init__("invalid_client_configuration", message, client_type=client_type)


class RedirectUriNotRegistered(GCalConfigError):
    def __init__(self, redirect: str, *, client_type: str | None = None) -> None:
        message = (
            "La redirection OAuth demandée n'est pas enregistrée dans la configuration "
            f"Google (redirect={redirect})."
        )
        super().__init__("redirect_uri_not_registered", message, client_type=client_type)
        self.redirect = redirect


class ClientTypeMismatch(GCalConfigError):
    def __init__(self, *, client_type: str | None = None) -> None:
        super().__init__(
            "client_type_installed_not_supported_for_this_redirect",
            "Les identifiants de type 'installed' ne prennent pas en charge cette redirection. "
            "Générez des identifiants de type 'Application Web'.",
            client_type=client_type,
        )


def build_env_presence() -> Dict[str, bool]:
    """Return a snapshot of the environment variables used for diagnostics."""

    return {
        "GOOGLE_CLIENT_ID": bool(os.getenv("GOOGLE_CLIENT_ID")),
        "GOOGLE_CLIENT_SECRET": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
        "GOOGLE_OAUTH_CLIENT_JSON": bool(os.getenv("GOOGLE_OAUTH_CLIENT_JSON")),
        "GOOGLE_CLIENT_SECRET_FILE": bool(os.getenv("GOOGLE_CLIENT_SECRET_FILE")),
        "GOOGLE_CLIENT_SECRET_FILES": bool(os.getenv("GOOGLE_CLIENT_SECRET_FILES")),
        "GOOGLE_CLIENT_SECRET_FALLBACKS": bool(os.getenv("GOOGLE_CLIENT_SECRET_FALLBACKS")),
    }


def _load_json_payload(raw: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise InvalidClientConfiguration(f"JSON OAuth invalide : {exc}") from exc
    if not isinstance(payload, dict):  # pragma: no cover - defensive
        raise InvalidClientConfiguration("Le JSON OAuth doit contenir un objet racine.")
    return payload


def _load_file_payload(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return _load_json_payload(path.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - dépend du FS
        raise InvalidClientConfiguration(f"Impossible de lire {path}: {exc}") from exc


def _derive_redirect(redirect_uri: Optional[str]) -> str:
    if redirect_uri:
        return redirect_uri
    explicit = os.getenv("GOOGLE_REDIRECT_URI")
    if explicit:
        return explicit
    return DEFAULT_REDIRECT


def _split_candidates(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    normalized = raw.replace("\n", os.pathsep)
    normalized = normalized.replace(";", os.pathsep)
    normalized = normalized.replace(",", os.pathsep)
    parts = [segment.strip() for segment in normalized.split(os.pathsep)]
    return [segment for segment in parts if segment]


def _deduplicate_paths(paths: Iterable[Path]) -> List[Path]:
    seen: set[str] = set()
    unique: List[Path] = []
    for path in paths:
        try:
            key = str(path.resolve(strict=False))
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _candidate_secret_files(app_obj) -> List[Path]:
    root_path = Path(getattr(app_obj, "root_path", Path.cwd()))
    instance_dir = Path(getattr(app_obj, "instance_path", root_path / "instance"))

    env_values: List[str] = []
    env_values.extend(_split_candidates(os.getenv("GOOGLE_CLIENT_SECRET_FILE")))
    env_values.extend(_split_candidates(os.getenv("GOOGLE_CLIENT_SECRET_FILES")))

    candidates: List[Path] = []
    for raw in env_values:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (root_path / candidate).resolve()
        else:
            candidate = candidate.resolve()
        candidates.append(candidate)

    candidates.extend(
        [
            instance_dir / "google_oauth_client.json",
            instance_dir / "gcal_client_secret.json",
        ]
    )

    try:
        extra = sorted(instance_dir.glob("client_secret*.json"))
    except OSError:  # pragma: no cover - depends on filesystem
        extra = []
    candidates.extend(extra)

    return _deduplicate_paths(candidates)


def _build_env_secret_configs(redirect: str) -> List[tuple[str, Dict[str, Any]]]:
    client_id_values = _split_candidates(os.getenv("GOOGLE_CLIENT_ID"))
    client_id = client_id_values[0] if client_id_values else os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        return []

    raw_secrets = []
    raw_secrets.extend(_split_candidates(os.getenv("GOOGLE_CLIENT_SECRET")))
    fallbacks_raw = os.getenv("GOOGLE_CLIENT_SECRET_FALLBACKS") or os.getenv(
        "GOOGLE_CLIENT_SECRET_FALLBACK"
    )
    raw_secrets.extend(_split_candidates(fallbacks_raw))

    configs: List[tuple[str, Dict[str, Any]]] = []
    for idx, secret in enumerate(raw_secrets, start=1):
        if not secret:
            continue
        source = "env" if idx == 1 else f"env#{idx}"
        configs.append(
            (
                source,
                {
                    "web": {
                        "client_id": client_id,
                        "client_secret": secret,
                        "auth_uri": DEFAULT_AUTH_URI,
                        "token_uri": DEFAULT_TOKEN_URI,
                        "redirect_uris": [redirect],
                    }
                },
            )
        )
    return configs


def _finalize_config(
    client_config: Dict[str, Any],
    *,
    source: str,
    redirect: str,
    env_presence: Dict[str, bool],
) -> ResolvedGCalConfig:
    if "web" in client_config:
        client_type = "web"
    elif "installed" in client_config:
        client_type = "installed"
    else:
        raise InvalidClientConfiguration("Le JSON OAuth doit contenir une clé 'web' ou 'installed'.")

    section = client_config.get(client_type)
    if section is None:
        raise InvalidClientConfiguration(
            "Configuration OAuth incomplète : section manquante pour le type détecté.",
            client_type=client_type,
        )

    redirect_uris = set()
    declared_redirect = section.get("redirect_uri")
    if isinstance(declared_redirect, str) and declared_redirect:
        redirect_uris.add(declared_redirect)
    extra_redirects = section.get("redirect_uris")
    if isinstance(extra_redirects, (list, tuple)):
        redirect_uris.update(str(item) for item in extra_redirects if item)

    redirect_ok = True
    if client_type == "web":
        if redirect_uris and redirect not in redirect_uris:
            raise RedirectUriNotRegistered(redirect, client_type=client_type)
        if not redirect_uris:
            section["redirect_uris"] = [redirect]
        else:
            section["redirect_uris"] = list(redirect_uris)
        section["redirect_uri"] = redirect
    else:  # installed
        loopback_hosts = {"127.0.0.1", "localhost"}
        try:  # pragma: no cover - defensive
            from urllib.parse import urlparse

            parsed = urlparse(redirect)
            redirect_ok = parsed.hostname in loopback_hosts
        except Exception:  # pragma: no cover - defensive
            redirect_ok = False
        if not redirect_ok:
            raise ClientTypeMismatch(client_type=client_type)
        if redirect_uris and redirect not in redirect_uris:
            raise RedirectUriNotRegistered(redirect, client_type=client_type)
        section["redirect_uri"] = redirect
        raise ClientTypeMismatch(client_type=client_type)

    return ResolvedGCalConfig(
        client_config=client_config,
        client_type=client_type,
        redirect_uri=redirect,
        redirect_uri_ok=redirect_ok,
        source=source,
        env_vars_present=env_presence,
    )


def resolve_client_config(
    *,
    app=None,
    redirect_uri: Optional[str] = None,
    skip_sources: Optional[Sequence[str]] = None,
) -> ResolvedGCalConfig:
    """Resolve Google OAuth configuration and validate redirect URI."""

    app_obj = app or current_app._get_current_object()
    env_presence = build_env_presence()
    redirect = _derive_redirect(redirect_uri)
    skip = {str(source) for source in (skip_sources or []) if source}

    errors: List[GCalConfigError] = []

    def _try_candidate(source: str, loader: Callable[[], Optional[Dict[str, Any]]]):
        if source and source in skip:
            return None
        try:
            payload = loader()
        except GCalConfigError as exc:
            errors.append(exc)
            return None
        if payload is None:
            return None
        try:
            return _finalize_config(payload, source=source, redirect=redirect, env_presence=env_presence)
        except GCalConfigError as exc:
            errors.append(exc)
            return None

    client_json_env = os.getenv("GOOGLE_OAUTH_CLIENT_JSON")
    if client_json_env:
        resolved = _try_candidate("env_json", lambda: _load_json_payload(client_json_env))
        if resolved is not None:
            return resolved

    for path in _candidate_secret_files(app_obj):
        source = str(path)
        resolved = _try_candidate(source, lambda path=path: _load_file_payload(path))
        if resolved is not None:
            return resolved

    for source, payload in _build_env_secret_configs(redirect):
        resolved = _try_candidate(source, lambda payload=payload: payload)
        if resolved is not None:
            return resolved

    if errors:
        raise errors[0]
    raise MissingClientSecrets()
