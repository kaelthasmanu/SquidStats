"""Public captive-portal routes: the login page users are redirected to by Squid."""

from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from loguru import logger

from services.auth.auth_service import AuthService
from services.captive_portal import config_service, portal_auth_service, session_service

captive_portal_bp = Blueprint("captive_portal", __name__, url_prefix="/portal")


def _client_ip() -> str:
    return request.remote_addr or ""


@captive_portal_bp.route("/login", methods=["GET", "POST"])
def login():
    """Show and process the captive-portal login form."""
    settings = config_service.get_config()
    if not settings["enabled"]:
        abort(404)
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        client_ip = _client_ip()

        is_allowed, remaining = AuthService.check_rate_limit(f"portal:{client_ip}")
        if not is_allowed:
            error = (
                _("Demasiados intentos fallidos. Intenta de nuevo en %s minutos.")
                % remaining
            )
        elif not username or not password:
            error = _("Por favor, ingresa usuario y contraseña.")
        else:
            ok, result = portal_auth_service.authenticate(username, password)
            if ok:
                AuthService.clear_failed_attempts(f"portal:{client_ip}")
                created, message = session_service.create_session(
                    client_ip, result, settings["session_ttl_minutes"]
                )
                if created:
                    logger.info(
                        f"Captive portal session created for {result} ({client_ip})"
                    )
                    flash(_("Acceso concedido. Ya puedes navegar."), "success")
                    return redirect(url_for("captive_portal.success"))
                error = message
            else:
                AuthService.record_failed_attempt(f"portal:{client_ip}")
                error = result

    return render_template(
        "captive_portal/login.html",
        settings=settings,
        error=error,
    )


@captive_portal_bp.route("/success")
def success():
    active_session = session_service.get_active_session(_client_ip())
    if active_session is None:
        return redirect(url_for("captive_portal.login"))

    remaining_seconds = max(
        0, int((active_session["expires_at"] - datetime.now()).total_seconds())
    )
    session_seconds = max(
        0,
        int(
            (
                active_session["expires_at"] - active_session["created_at"]
            ).total_seconds()
        ),
    )
    return render_template(
        "captive_portal/success.html",
        active_session=active_session,
        remaining_seconds=remaining_seconds,
        session_seconds=session_seconds,
    )


@captive_portal_bp.route("/logout", methods=["POST"])
def logout():
    """Revoke the captive-portal session for the requesting IP."""
    client_ip = _client_ip()
    session_service.revoke_session(client_ip)
    flash(_("Sesión cerrada."), "success")
    return redirect(url_for("captive_portal.login"))
