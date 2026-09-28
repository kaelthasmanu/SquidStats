"""Admin routes for the captive-portal feature: settings and active sessions."""

from urllib.parse import urlsplit

from flask import flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from loguru import logger

from services.auth.auth_service import admin_required
from services.captive_portal import config_service, session_service
from services.squid.captive_portal_config_service import (
    disable_captive_portal,
    enable_captive_portal,
    render_block,
)
from services.system import system_service

from .helpers import flash_and_redirect, get_config_manager, get_int_form_field

_SESSION_TTL_UNITS = {
    "minutes": 1,
    "hours": 60,
    "days": 1440,
}


def _session_ttl_parts(total_minutes: int) -> tuple[int, str]:
    """Return a readable value and unit for the stored minute value."""
    for unit, multiplier in (("days", 1440), ("hours", 60), ("minutes", 1)):
        if total_minutes % multiplier == 0:
            return total_minutes // multiplier, unit
    return total_minutes, "minutes"


def _apply_squid_state(settings: dict) -> tuple[bool, str]:
    """(Re)apply the captive-portal directives to squid.conf per current settings."""
    cm = get_config_manager()
    if not settings["enabled"]:
        return disable_captive_portal(cm)

    login_url = f"{settings['portal_public_url'].rstrip('/')}/portal/login"
    return enable_captive_portal(
        cm,
        login_url=login_url,
        portal_public_url=settings["portal_public_url"],
        acl_ttl_seconds=settings["acl_ttl_seconds"],
        acl_negative_ttl_seconds=settings["acl_negative_ttl_seconds"],
    )


def register_routes(bp):
    @bp.route("/captive-portal", methods=["GET"])
    @admin_required
    def captive_portal_config():
        settings = config_service.get_config()
        settings["session_ttl_value"], settings["session_ttl_unit"] = (
            _session_ttl_parts(settings["session_ttl_minutes"])
        )
        sessions = session_service.list_active_sessions()
        login_url = (
            f"{settings['portal_public_url'].rstrip('/')}/portal/login?redirect=%s"
            if settings["portal_public_url"]
            else "<PORTAL_PUBLIC_URL>/portal/login?redirect=%s"
        )
        config_preview = render_block(
            login_url=login_url,
            portal_public_url=settings["portal_public_url"],
            acl_ttl_seconds=settings["acl_ttl_seconds"],
            acl_negative_ttl_seconds=settings["acl_negative_ttl_seconds"],
        )
        return render_template(
            "admin/captive_portal.html",
            settings=settings,
            sessions=sessions,
            config_preview=config_preview,
        )

    @bp.route("/captive-portal/save", methods=["POST"])
    @admin_required
    def captive_portal_save():
        portal_public_url = request.form.get("portal_public_url", "").strip()
        if portal_public_url:
            try:
                parsed_url = urlsplit(portal_public_url)
                valid_url = (
                    parsed_url.scheme in {"http", "https"}
                    and parsed_url.hostname
                    and parsed_url.username is None
                    and parsed_url.password is None
                    and not parsed_url.query
                    and not parsed_url.fragment
                    and not any(
                        char.isspace() or ord(char) < 32 for char in portal_public_url
                    )
                    and len(portal_public_url) <= 512
                )
                parsed_port = parsed_url.port
                valid_url = valid_url and (
                    parsed_port is None or 0 <= parsed_port <= 65535
                )
            except ValueError:
                valid_url = False
            if not valid_url:
                flash(
                    _(
                        "La URL pública debe ser una URL HTTP o HTTPS válida sin credenciales."
                    ),
                    "error",
                )
                return redirect(url_for("admin.captive_portal_config"))

        session_ttl_value = get_int_form_field("session_ttl_value")
        session_ttl_unit = request.form.get("session_ttl_unit", "").strip()
        if session_ttl_value is None and request.form.get("session_ttl_minutes"):
            session_ttl = get_int_form_field("session_ttl_minutes")
        elif session_ttl_unit in _SESSION_TTL_UNITS and session_ttl_value is not None:
            session_ttl = session_ttl_value * _SESSION_TTL_UNITS[session_ttl_unit]
        else:
            session_ttl = None
        acl_ttl = get_int_form_field("acl_ttl_seconds")
        acl_negative_ttl = get_int_form_field("acl_negative_ttl_seconds")
        if session_ttl is None or not 1 <= session_ttl <= 525600:
            flash(
                _(
                    "La duración de la sesión debe ser un valor positivo y una unidad válida"
                ),
                "error",
            )
            return redirect(url_for("admin.captive_portal_config"))
        if (
            acl_ttl is None
            or not 0 <= acl_ttl <= 86400
            or acl_negative_ttl is None
            or not 0 <= acl_negative_ttl <= 86400
        ):
            flash(
                _("Los valores de TTL de la ACL deben ser enteros no negativos"),
                "error",
            )
            return redirect(url_for("admin.captive_portal_config"))

        settings = config_service.update_config(
            enabled=1 if request.form.get("enabled") == "on" else 0,
            portal_title=request.form.get("portal_title", "SquidStats Portal").strip(),
            portal_public_url=portal_public_url,
            session_ttl_minutes=session_ttl,
            acl_ttl_seconds=acl_ttl,
            acl_negative_ttl_seconds=acl_negative_ttl,
        )

        if settings["enabled"] and not settings["portal_public_url"]:
            flash(
                _("Debes definir la URL pública del portal antes de habilitarlo"),
                "error",
            )
            config_service.update_config(enabled=0)
            return redirect(url_for("admin.captive_portal_config"))

        ok, message = _apply_squid_state(settings)
        if not ok:
            logger.error("Error applying captive portal configuration: %s", message)
            config_service.update_config(enabled=0)
            return flash_and_redirect(False, message, "admin.captive_portal_config")

        reloaded, reload_message, _details = system_service.reload_squid()
        if not reloaded:
            logger.warning(
                "Squid reload after captive portal update failed: %s", reload_message
            )
            message = (
                _("Configuración guardada, pero Squid no pudo recargarse: %s")
                % reload_message
            )
            return flash_and_redirect(False, message, "admin.captive_portal_config")
        return flash_and_redirect(True, message, "admin.captive_portal_config")

    @bp.route("/captive-portal/sessions/revoke", methods=["POST"])
    @admin_required
    def captive_portal_revoke_session():
        ip = request.form.get("ip", "").strip()
        ok, message = session_service.revoke_session(ip)
        return flash_and_redirect(ok, message, "admin.captive_portal_config")
