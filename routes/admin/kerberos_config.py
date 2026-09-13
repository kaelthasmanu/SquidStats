"""Admin routes for managed Squid Kerberos / SPNEGO configuration."""

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from loguru import logger

from services.auth.auth_service import admin_required, api_admin_required
from services.squid.kerberos_config_service import (
    KerberosConfigurationError,
    apply_configuration,
    get_preflight,
    get_status,
    normalise_settings,
    render_preview,
)

from .helpers import get_config_manager

_FORM_SETTING_FIELDS = frozenset(
    {
        "enabled",
        "helper_path",
        "keytab_path",
        "service_principal",
        "children",
        "startup",
        "idle",
        "keep_alive",
        "strip_realm",
        "acl_name",
        "enforce_auth",
        "replace_existing_negotiate",
        "reload_squid",
    }
)
_BOOLEAN_SETTING_FIELDS = frozenset(
    {
        "enabled",
        "keep_alive",
        "strip_realm",
        "enforce_auth",
        "replace_existing_negotiate",
        "reload_squid",
    }
)


def _private_json(payload: dict, status_code: int = 200):
    """Return admin-only configuration data with the app's private cache policy."""
    response = jsonify(payload)
    response.status_code = status_code
    response.headers["Cache-Control"] = "private, no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _form_values() -> dict[str, str]:
    """Return the final value for fields backed by a hidden checkbox input."""
    return {
        field: values[-1]
        for field, values in request.form.lists()
        if field != "csrf_token" and values
    }


def _as_form_bool(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on", "si", "sí"}


def _settings_for_failed_form(
    saved_settings: dict, form_data: dict[str, str]
) -> dict:
    """Preserve a submitted draft without accepting arbitrary template data."""
    settings = dict(saved_settings)
    for field in _FORM_SETTING_FIELDS:
        if field not in form_data:
            continue
        settings[field] = (
            _as_form_bool(form_data[field])
            if field in _BOOLEAN_SETTING_FIELDS
            else form_data[field]
        )
    return settings


def _render_failed_form(config_manager, form_data: dict[str, str], message: str, status: int):
    """Render validation failures in place so an admin does not lose a draft."""
    kerberos = get_status(config_manager)
    kerberos["settings"] = _settings_for_failed_form(
        kerberos["settings"], form_data
    )
    kerberos["form_error"] = message
    try:
        settings = normalise_settings(form_data)
        kerberos["preview"] = render_preview(settings)
        kerberos["preflight"] = get_preflight(config_manager, settings)
    except KerberosConfigurationError:
        kerberos["preview"] = (
            "# La configuración enviada tiene valores inválidos; corrígelos antes de aplicar.\n"
        )

    preflight = kerberos["preflight"]
    preflight["ready"] = False
    if message not in preflight["errors"]:
        preflight["errors"].insert(0, message)
    return render_template("admin/kerberos_config.html", kerberos=kerberos), status


def register_routes(bp):
    @bp.route("/kerberos-config", methods=["GET", "POST"], endpoint="kerberos_config")
    @admin_required
    def kerberos_config_view():
        """Show and safely apply the server-side Kerberos configuration."""
        config_manager = get_config_manager()

        if request.method == "POST":
            form_data = _form_values()
            if form_data.get("action") == "disable":
                form_data["enabled"] = "false"
            try:
                result = apply_configuration(form_data, config_manager)
            except KerberosConfigurationError as exc:
                return _render_failed_form(config_manager, form_data, str(exc), 400)
            except Exception:
                logger.exception("Unexpected Kerberos configuration failure")
                return _render_failed_form(
                    config_manager,
                    form_data,
                    _(
                        "No se pudo aplicar la configuración Kerberos. Revisa el registro del servidor."
                    ),
                    500,
                )
            else:
                flash(
                    result["message"],
                    "warning" if result["status"] == "warning" else "success",
                )
            return redirect(url_for("admin.kerberos_config"))

        return render_template(
            "admin/kerberos_config.html",
            kerberos=get_status(config_manager),
        )

    @bp.route("/api/kerberos/status", methods=["GET"], endpoint="kerberos_status")
    @api_admin_required
    def kerberos_status():
        """Expose non-secret form/status data to the administration frontend."""
        try:
            return _private_json(
                {"status": "success", "kerberos": get_status(get_config_manager())}
            )
        except Exception:
            logger.exception("Unable to load Kerberos configuration status")
            return _private_json(
                {
                    "status": "error",
                    "message": _("No se pudo obtener el estado de Kerberos."),
                },
                500,
            )

    @bp.route("/api/kerberos/preview", methods=["POST"], endpoint="kerberos_preview")
    @api_admin_required
    def kerberos_preview():
        """Render a validated preview without writing Squid configuration files."""
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _private_json(
                {
                    "status": "error",
                    "message": _("Envía los valores de configuración en formato JSON."),
                },
                400,
            )
        try:
            settings = normalise_settings(data)
            preflight = get_preflight(get_config_manager(), settings)
            return _private_json(
                {
                    "status": "success",
                    "preview": render_preview(settings),
                    "settings": settings.to_dict(),
                    "preflight": preflight,
                }
            )
        except KerberosConfigurationError as exc:
            return _private_json(
                {"status": "error", "message": str(exc)}, 400
            )
        except Exception:
            logger.exception("Unable to generate Kerberos configuration preview")
            return _private_json(
                {
                    "status": "error",
                    "message": _(
                        "No se pudo generar la vista previa de Kerberos. Revisa el registro del servidor."
                    ),
                },
                500,
            )
