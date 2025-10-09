"""Routes for the agenda module and Google Calendar integration."""

from __future__ import annotations

import secrets
from typing import Any, Dict

from flask import (
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

try:  # pragma: no cover - import guard for optional dependency
    from googleapiclient.errors import HttpError
except Exception:  # pragma: no cover - executed when library missing
    class HttpError(Exception):
        """Fallback HttpError when googleapiclient is unavailable."""

        status_code: int | None = None

from server.services import gcal_config
from server.services.gcal_service import GCalService
from . import api_bp, public_bp


STATE_SESSION_KEY = "agenda:gcal_state"


def _service() -> GCalService:
    return GCalService()


def _json_success(data: Any, status: int = 200) -> Response:
    response = jsonify({"success": True, "data": data})
    response.status_code = status
    return response


def _json_error(code: str, message: str, http_status: int = 400, details: Dict[str, Any] | None = None) -> Response:
    payload: Dict[str, Any] = {"success": False, "error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    response = jsonify(payload)
    response.status_code = http_status
    return response


def _extract_google_error(error: HttpError) -> Dict[str, Any]:  # pragma: no cover - relies on Google responses
    try:
        return error.error_details if hasattr(error, "error_details") else error.__dict__
    except Exception:
        return {"status": getattr(error, "status_code", None)}


@public_bp.get("/gcal/auth")
def start_auth():
    service = _service()
    if not service.is_configured():
        flash("Google Calendar n'est pas configuré. Consultez la documentation Agenda.", "error")
        current_app.logger.warning("Attempted OAuth without configuration")
        target = url_for("index", agenda_connected="0", _anchor="agenda")
        return redirect(target)

    state_token = secrets.token_urlsafe(32)
    session[STATE_SESSION_KEY] = state_token
    try:
        authorization_url = service.get_auth_url(state_token)
    except FileNotFoundError as exc:
        current_app.logger.error("Google client secret missing: %s", exc)
        flash("Secret OAuth Google introuvable. Vérifiez la configuration.", "error")
        target = url_for("index", agenda_connected="0", _anchor="agenda")
        return redirect(target)
    except gcal_config.GCalConfigError as exc:
        current_app.logger.error(
            "Google OAuth configuration invalid", extra={"reason": exc.reason, "client_type": exc.client_type}
        )
        flash("Configuration OAuth Google invalide. Consultez le diagnostic.", "error")
        target = url_for("index", agenda_connected="0", _anchor="agenda")
        return redirect(target)

    return redirect(authorization_url)


@public_bp.get("/gcal/oauth2callback")
def oauth2callback():
    expected_state = session.pop(STATE_SESSION_KEY, None)
    received_state = request.args.get("state")
    if not expected_state or expected_state != received_state:
        flash("État OAuth invalide. Relancez la connexion.", "error")
        current_app.logger.warning("Invalid OAuth state received", extra={"expected": expected_state, "received": received_state})
        target = url_for("index", agenda_connected="0", _anchor="agenda")
        return redirect(target)

    service = _service()
    try:
        service.handle_oauth2_callback(request.args)
    except ValueError as exc:
        flash("Code d'autorisation manquant dans la réponse Google.", "error")
        current_app.logger.error("Missing code in OAuth callback: %s", exc)
        target = url_for("index", agenda_connected="0", _anchor="agenda")
        return redirect(target)
    except RuntimeError as exc:
        reason = str(exc) or "oauth_exchange_failed"
        flash("Impossible de finaliser la connexion Google Calendar.", "error")
        current_app.logger.error("OAuth exchange failed", extra={"reason": reason})
        target = url_for("index", agenda_connected="0", _anchor="agenda")
        return redirect(target)

    flash("Compte Google connecté avec succès.", "success")
    target = url_for("index", agenda_connected="1", _anchor="agenda")
    return redirect(target)


@public_bp.post("/gcal/disconnect")
def disconnect():
    service = _service()
    service.revoke()
    flash("Compte Google déconnecté.", "info")
    target = url_for("index", agenda_disconnected="1", _anchor="agenda")
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return _json_success({"redirect": target})
    return redirect(target)


@api_bp.get("/ping")
def api_ping():
    return _json_success("agenda-pong")


@api_bp.get("/status")
def api_status():
    service = _service()
    status = service.get_status()
    payload = {
        "configured": status.configured,
        "authenticated": status.authenticated,
        "scopes": status.scopes,
        "redirect_uri": status.redirect_uri,
        "mode": status.mode,
        "connected": status.connected,
        "oauth_config_ok": status.oauth_config_ok,
        "client_type": status.client_type,
        "redirect_uri_ok": status.redirect_uri_ok,
        "reason": status.reason,
        "env_vars_present": status.env_vars_present,
    }
    return _json_success(payload)


@public_bp.get("/gcal/debug")
def oauth_debug():
    service = _service()
    status = service.get_status()
    payload = {
        "configured": status.configured,
        "authenticated": status.authenticated,
        "connected": status.connected,
        "mode": status.mode,
        "client_type": status.client_type,
        "redirect_uri": status.redirect_uri,
        "redirect_uri_ok": status.redirect_uri_ok,
        "oauth_config_ok": status.oauth_config_ok,
        "reason": status.reason,
        "env_vars_present": status.env_vars_present,
    }
    return _json_success(payload)


@api_bp.get("/calendars")
def api_calendars():
    service = _service()
    if not service.is_configured():
        return _json_error("not_configured", "Google Calendar n'est pas configuré sur le serveur.", 400)
    if not service.is_authenticated():
        return _json_error("not_authenticated", "Connectez Google Calendar pour accéder aux agendas.", 401)
    try:
        calendars = service.list_calendars()
    except HttpError as error:  # pragma: no cover - depends on Google API
        current_app.logger.error("Google Calendar API error (calendars): %s", error)
        return _json_error("api_error", "Impossible de récupérer les calendriers Google.", 502, _extract_google_error(error))
    return _json_success(calendars)


@api_bp.get("/events")
def api_events():
    service = _service()
    if not service.is_configured():
        return _json_error("not_configured", "Google Calendar n'est pas configuré sur le serveur.", 400)
    if not service.is_authenticated():
        return _json_error("not_authenticated", "Connectez Google Calendar pour accéder aux événements.", 401)

    calendar_id = request.args.get("calendarId")
    time_min = request.args.get("timeMin")
    time_max = request.args.get("timeMax")
    max_results = request.args.get("maxResults", type=int) or 2500

    missing = [name for name, value in {"calendarId": calendar_id, "timeMin": time_min, "timeMax": time_max}.items() if not value]
    if missing:
        return _json_error(
            "api_error",
            "Paramètres requis manquants.",
            400,
            {"missing": missing},
        )

    try:
        events = service.list_events(calendar_id, time_min, time_max, max_results=max_results)
    except HttpError as error:  # pragma: no cover - depends on Google API
        current_app.logger.error("Google Calendar API error (events): %s", error)
        return _json_error("api_error", "Impossible de récupérer les événements Google.", 502, _extract_google_error(error))

    return _json_success(events)


