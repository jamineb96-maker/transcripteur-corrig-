"""Manual diagnostic script for the Google Calendar integration."""

from __future__ import annotations

import sys
from typing import Sequence

try:  # pragma: no cover - import guard for optional dependency
    from googleapiclient.errors import HttpError
except Exception:  # pragma: no cover - executed when library missing
    class HttpError(Exception):
        """Fallback HttpError when googleapiclient is unavailable."""

        status_code: int | None = None

from server import create_app
from server.services.gcal_service import GCalService


def _format_calendars(calendars: Sequence[dict]) -> str:
    lines = []
    for item in calendars:
        primary = " (principal)" if item.get("primary") else ""
        lines.append(f"- {item.get('summary') or item.get('id')}{primary} — {item.get('id')}")
    return "\n".join(lines) or "(aucun calendrier accessible)"


def main() -> int:
    app = create_app()
    with app.app_context():
        service = GCalService()
        status = service.get_status()
        print(f"configured: {status.configured}")
        print(f"authenticated: {status.authenticated}")
        print(f"mode: {status.mode}")
        print(f"redirect_uri: {status.redirect_uri or '—'}")
        print("scopes:")
        for scope in status.scopes:
            print(f"  - {scope}")

        if not status.configured:
            print("Google Calendar n'est pas configuré.")
            return 1

        if not status.authenticated:
            print("Configuration détectée mais aucune session authentifiée.")
            return 0

        try:
            calendars = service.list_calendars()
        except HttpError as error:
            print(f"Erreur Google API lors du listing des agendas: {error}")
            return 2

        print("Agendas accessibles:")
        print(_format_calendars(calendars))
    return 0


if __name__ == "__main__":
    sys.exit(main())
