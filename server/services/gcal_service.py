"""Google Calendar service handling OAuth and API calls.

Ce module délègue désormais le chargement des identifiants OAuth à
``gcal_config`` afin de disposer d'un socle commun pour les diagnostics.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from flask import current_app, url_for
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

try:  # pragma: no cover - import guard for optional dependency
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except Exception:  # pragma: no cover - executed when library missing
    build = None  # type: ignore[assignment]

    class HttpError(Exception):
        """Fallback HttpError when googleapiclient is unavailable."""

        status_code: int | None = None
from oauthlib.oauth2.rfc6749.errors import InvalidClientError

from . import gcal_config


LOGGER = logging.getLogger("assist.server.gcal")


DEFAULT_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
CLIENT_SECRET_FILENAME = "gcal_client_secret.json"
TOKEN_FILENAME = "gcal_token.json"


@dataclass(frozen=True)
class GCalStatus:
    configured: bool
    authenticated: bool
    scopes: List[str]
    redirect_uri: str
    mode: str
    client_type: str
    redirect_uri_ok: bool
    oauth_config_ok: bool
    reason: Optional[str]
    env_vars_present: Dict[str, bool]
    connected: bool


_LAST_DIAGNOSTICS: Dict[str, Any] = {}


class GCalService:
    """Facade around Google Calendar authentication and API access."""

    def __init__(self, app=None) -> None:
        self._app = app
        self._last_state: Optional[str] = None
        self._last_resolved: Optional[gcal_config.ResolvedGCalConfig] = None

    @property
    def app(self):
        return self._app or current_app._get_current_object()

    @property
    def instance_dir(self) -> Path:
        path = Path(self.app.instance_path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def token_path(self) -> Path:
        return self.instance_dir / TOKEN_FILENAME

    @property
    def secret_path(self) -> Path:
        return self.instance_dir / CLIENT_SECRET_FILENAME

    @property
    def scopes(self) -> List[str]:
        raw = os.getenv("GOOGLE_SCOPES")
        if not raw:
            return list(DEFAULT_SCOPES)
        parts: Iterable[str] = []
        if "," in raw:
            parts = (segment.strip() for segment in raw.split(","))
        else:
            parts = (segment.strip() for segment in raw.split(" "))
        scopes = [scope for scope in parts if scope]
        return scopes or list(DEFAULT_SCOPES)

    def is_configured(self) -> bool:
        try:
            self._resolve_config()
            return True
        except gcal_config.MissingClientSecrets:
            return False
        except gcal_config.GCalConfigError:
            return True

    def is_authenticated(self) -> bool:
        creds = self._load_credentials()
        return bool(creds and creds.valid)

    def get_status(self) -> GCalStatus:
        configured = self.is_configured()
        authenticated = self.is_authenticated()
        redirect_uri = ""
        client_type = "unknown"
        redirect_ok = False
        oauth_config_ok = False
        reason: Optional[str] = None
        env_presence = gcal_config.build_env_presence()
        resolved = None
        try:
            resolved = self._resolve_config()
        except gcal_config.GCalConfigError as exc:
            client_type = exc.client_type or client_type
            reason = exc.reason
            redirect_uri = self._build_redirect_uri()
            redirect_ok = False
        else:
            if resolved:
                redirect_uri = resolved.redirect_uri
                client_type = resolved.client_type
                redirect_ok = resolved.redirect_uri_ok
                oauth_config_ok = resolved.redirect_uri_ok
                env_presence = resolved.env_vars_present

        if _LAST_DIAGNOSTICS:
            reason = reason or _LAST_DIAGNOSTICS.get("reason")
            client_type = _LAST_DIAGNOSTICS.get("client_type", client_type)
            redirect_ok = bool(_LAST_DIAGNOSTICS.get("redirect_uri_ok", redirect_ok))
            oauth_config_ok = oauth_config_ok and not _LAST_DIAGNOSTICS.get("oauth_config_error")

        mode = self._detect_mode(resolved)

        return GCalStatus(
            configured=configured,
            authenticated=authenticated,
            scopes=self.scopes,
            redirect_uri=redirect_uri,
            mode=mode,
            client_type=client_type,
            redirect_uri_ok=redirect_ok,
            oauth_config_ok=oauth_config_ok,
            reason=reason,
            env_vars_present=env_presence,
            connected=authenticated,
        )

    def get_auth_url(self, state_token: Optional[str] = None) -> str:
        flow, resolved, mode = self._build_flow()
        kwargs: Dict[str, Any] = {
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        }
        if state_token:
            kwargs["state"] = state_token
        authorization_url, state = flow.authorization_url(**kwargs)
        self._last_state = state
        LOGGER.info(
            "Generated Google OAuth URL (mode=%s, redirect=%s, client_type=%s)",
            mode,
            flow.redirect_uri,
            resolved.client_type,
        )
        return authorization_url

    @property
    def last_state(self) -> Optional[str]:
        return self._last_state

    def handle_oauth2_callback(self, request_args: Dict[str, Any]) -> Credentials:
        code = request_args.get("code")
        if not code:
            raise ValueError("Missing authorization code in callback")

        attempted_sources: List[str] = []
        last_invalid: Optional[tuple[InvalidClientError, gcal_config.ResolvedGCalConfig]] = None

        while True:
            try:
                flow, resolved, _mode = self._build_flow(skip_sources=attempted_sources)
            except gcal_config.MissingClientSecrets as exc:
                if last_invalid is not None:
                    invalid_exc, invalid_resolved = last_invalid
                    self._set_last_error(
                        reason="invalid_client",
                        client_type=invalid_resolved.client_type,
                        redirect_ok=invalid_resolved.redirect_uri_ok,
                        oauth_error=True,
                    )
                    raise RuntimeError("invalid_client") from invalid_exc
                self._set_last_error(
                    reason=exc.reason,
                    client_type=exc.client_type,
                    redirect_ok=False,
                    oauth_error=True,
                )
                raise RuntimeError(exc.reason) from exc
            except gcal_config.GCalConfigError as exc:
                self._set_last_error(
                    reason=exc.reason,
                    client_type=exc.client_type,
                    redirect_ok=False,
                    oauth_error=True,
                )
                raise RuntimeError(exc.reason) from exc

            try:
                flow.fetch_token(code=code)
            except InvalidClientError as exc:
                LOGGER.error(
                    "OAuth token exchange failed: invalid_client (source=%s)",
                    resolved.source,
                    exc_info=True,
                )
                last_invalid = (exc, resolved)
                marker = resolved.source or f"candidate#{len(attempted_sources) + 1}"
                if marker not in attempted_sources:
                    attempted_sources.append(marker)
                continue
            except Exception as exc:  # pragma: no cover - network / google specific
                LOGGER.exception("OAuth token exchange failed")
                self._set_last_error(
                    reason="oauth_exchange_failed",
                    client_type=resolved.client_type,
                    redirect_ok=resolved.redirect_uri_ok,
                    oauth_error=True,
                )
                raise RuntimeError("oauth_exchange_failed") from exc

            credentials = flow.credentials
            self._store_credentials(credentials)
            self._last_resolved = resolved
            self._clear_last_error()
            LOGGER.info("Google Calendar credentials stored at %s", self.token_path)
            return credentials

    def list_calendars(self) -> List[Dict[str, Any]]:
        creds = self._require_credentials()
        if build is None:
            raise RuntimeError("googleapiclient indisponible (dev/test).")
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        response = service.calendarList().list(showDeleted=False, minAccessRole="reader").execute()
        items = response.get("items", [])
        return [
            {
                "id": item.get("id"),
                "summary": item.get("summary") or item.get("id"),
                "primary": bool(item.get("primary")),
            }
            for item in items
        ]

    def list_events(
        self,
        calendar_id: str,
        time_min: str,
        time_max: str,
        max_results: int = 2500,
    ) -> List[Dict[str, Any]]:
        creds = self._require_credentials()
        if build is None:
            raise RuntimeError("googleapiclient indisponible (dev/test).")
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        request = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
        )
        response = request.execute()
        return [
            {
                "id": item.get("id"),
                "summary": item.get("summary"),
                "start": item.get("start", {}),
                "end": item.get("end", {}),
                "attendees": self._simplify_attendees(item.get("attendees", [])),
            }
            for item in response.get("items", [])
        ]

    def revoke(self) -> None:
        creds = self._load_credentials()
        if not creds:
            self._delete_credentials()
            return
        try:
            creds.revoke(GoogleRequest())
        except Exception:  # pragma: no cover - depends on Google endpoint
            LOGGER.warning("Failed to revoke Google credentials", exc_info=True)
        self._delete_credentials()

    # Internal helpers -------------------------------------------------

    def _detect_mode(self, resolved: Optional[gcal_config.ResolvedGCalConfig]) -> str:
        if resolved is not None:
            source = (resolved.source or "").lower()
            if source.startswith("env"):
                return "env"
            if source.endswith(".json"):
                return "file"
            if source:
                return source
        if self.secret_path.exists():
            return "file"
        env_presence = gcal_config.build_env_presence()
        if env_presence.get("GOOGLE_CLIENT_ID") or env_presence.get("GOOGLE_OAUTH_CLIENT_JSON"):
            return "env"
        return "none"

    def _resolve_config(
        self, *, skip_sources: Iterable[str] = ()
    ) -> gcal_config.ResolvedGCalConfig:
        redirect_uri = self._build_redirect_uri()
        resolved = gcal_config.resolve_client_config(
            app=self.app, redirect_uri=redirect_uri, skip_sources=tuple(skip_sources)
        )
        self._last_resolved = resolved
        return resolved

    def _build_flow(self, *, skip_sources: Iterable[str] = ()): 
        resolved = self._resolve_config(skip_sources=skip_sources)
        scopes = self.scopes
        flow = Flow.from_client_config(resolved.client_config, scopes=scopes)
        flow.redirect_uri = resolved.redirect_uri
        return flow, resolved, self._detect_mode(resolved)

    def _set_last_error(
        self,
        *,
        reason: str,
        client_type: Optional[str],
        redirect_ok: bool,
        oauth_error: bool,
    ) -> None:
        _LAST_DIAGNOSTICS.update(
            {
                "reason": reason,
                "client_type": client_type or "unknown",
                "redirect_uri_ok": bool(redirect_ok),
                "oauth_config_error": oauth_error,
            }
        )

    @staticmethod
    def _clear_last_error() -> None:
        _LAST_DIAGNOSTICS.clear()

    def _build_redirect_uri(self) -> str:
        explicit = os.getenv("GOOGLE_REDIRECT_URI")
        if explicit:
            return explicit
        base_override = os.getenv("GOOGLE_REDIRECT_BASE")
        if base_override:
            base_override = base_override.rstrip("/")
            relative = url_for("agenda_public.oauth2callback", _external=False)
            return f"{base_override}{relative}"
        return url_for("agenda_public.oauth2callback", _external=True)

    def _load_credentials(self) -> Optional[Credentials]:
        if not self.token_path.exists():
            return None
        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            LOGGER.warning("Invalid Google token file, removing it: %s", self.token_path)
            self._delete_credentials()
            return None
        creds = Credentials.from_authorized_user_info(data, scopes=self.scopes)
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleRequest())
                self._store_credentials(creds)
                LOGGER.info("Google Calendar token refreshed")
            except RefreshError:
                LOGGER.warning("Unable to refresh Google token, clearing it.")
                self._delete_credentials()
                return None
        if creds and not creds.valid:
            return None
        return creds

    def _store_credentials(self, credentials: Credentials) -> None:
        payload = json.loads(credentials.to_json())
        self.token_path.write_text(json.dumps(payload), encoding="utf-8")

    def _delete_credentials(self) -> None:
        try:
            if self.token_path.exists():
                self.token_path.unlink()
        except OSError:
            LOGGER.warning("Unable to delete Google token file %s", self.token_path, exc_info=True)

    def _require_credentials(self) -> Credentials:
        creds = self._load_credentials()
        if not creds or not creds.valid:
            raise RuntimeError("not_authenticated")
        return creds

    @staticmethod
    def _simplify_attendees(attendees: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
        simplified: List[Dict[str, str]] = []
        for attendee in attendees or []:
            if not attendee:
                continue
            email = attendee.get("email")
            name = attendee.get("displayName") or email or ""
            simplified.append({"email": email or "", "displayName": name})
        return simplified


__all__ = ["GCalService", "GCalStatus", "DEFAULT_SCOPES"]

