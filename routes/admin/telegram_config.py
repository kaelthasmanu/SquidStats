"""Admin Telegram configuration routes."""

from flask import jsonify, render_template, request
from flask_babel import gettext as _
from loguru import logger

from routes.auth_routes import csrf
from services.auth.auth_service import admin_required, api_auth_required
from services.notifications.telegram_config_service import load_config, save_config


def register_routes(bp):

    # ------------------------------------------------------------------ #
    # View                                                                 #
    # ------------------------------------------------------------------ #

    @bp.route("/telegram-config", endpoint="telegram_config")
    @admin_required
    def telegram_config_view():
        cfg = load_config()
        # Keep secrets out of the rendered HTML; use flags to indicate existing values.
        cfg["has_api_hash"] = bool(cfg.get("api_hash"))
        cfg["has_bot_token"] = bool(cfg.get("bot_token"))
        cfg["api_hash"] = ""
        cfg["bot_token"] = ""
        return render_template("admin/telegram_config_page.html", cfg=cfg)

    # ------------------------------------------------------------------ #
    # Load config (API)                                                    #
    # ------------------------------------------------------------------ #

    @bp.route("/api/telegram/config", methods=["GET"])
    @api_auth_required
    def telegram_get_config():
        cfg = load_config()
        cfg["has_api_hash"] = bool(cfg.get("api_hash"))
        cfg["has_bot_token"] = bool(cfg.get("bot_token"))
        cfg["api_hash"] = ""
        cfg["bot_token"] = ""
        return jsonify({"status": "success", "config": cfg})

    # ------------------------------------------------------------------ #
    # Save config                                                          #
    # ------------------------------------------------------------------ #

    @bp.route("/api/telegram/save-config", methods=["POST"])
    @csrf.exempt
    @api_auth_required
    def telegram_save_config():
        data = request.get_json(silent=True) or {}
        try:
            save_config(data)
            # Reinitialize the running service so the new credentials take effect
            # immediately without restarting the application.
            try:
                from services.notifications.telegram_integration import (
                    initialize_telegram_service,
                )

                initialize_telegram_service()
            except Exception as reinit_err:
                logger.warning(f"Could not reinitialize Telegram service: {reinit_err}")

            return jsonify(
                {"status": "success", "message": _("Configuración Telegram guardada.")}
            )
        except Exception as exc:
            logger.error(f"Error al guardar configuración Telegram: {exc}")
            return jsonify(
                {"status": "error", "message": _("Error al guardar la configuración.")}
            ), 500

    # ------------------------------------------------------------------ #
    # Test connection                                                       #
    # ------------------------------------------------------------------ #

    @bp.route("/api/telegram/test", methods=["POST"])
    @csrf.exempt
    @api_auth_required
    def telegram_test():
        try:
            from services.notifications.telegram_integration import (
                _telegram_service,
                initialize_telegram_service,
                run_async,
            )

            # Ensure service is running with the latest config.
            if _telegram_service is None:
                if not initialize_telegram_service():
                    cfg = load_config()
                    if not cfg.get("enabled"):
                        return jsonify(
                            {
                                "status": "error",
                                "message": _(
                                    "Telegram está deshabilitado en la configuración."
                                ),
                            }
                        ), 400
                    return jsonify(
                        {
                            "status": "error",
                            "message": _(
                                "No se pudo inicializar el servicio Telegram. "
                                "Verifique las credenciales API."
                            ),
                        }
                    ), 400

            # Re-import after possible reinitialize
            from services.notifications.telegram_integration import (
                _telegram_service as svc,
            )

            health = run_async(svc.health_check())
            if health.get("connected"):
                return jsonify(
                    {
                        "status": "success",
                        "message": _(
                            "Conexión con Telegram establecida correctamente."
                        ),
                        "details": health,
                    }
                )
            else:
                return jsonify(
                    {
                        "status": "error",
                        "message": _(
                            "No se pudo conectar a Telegram. Verifique las credenciales."
                        ),
                        "details": health,
                    }
                ), 400

        except Exception as exc:
            logger.exception(f"Error during Telegram connection test: {exc}")
            return jsonify(
                {
                    "status": "error",
                    "message": _("Error interno al probar la conexión Telegram."),
                }
            ), 500

    # ------------------------------------------------------------------ #
    # Status                                                               #
    # ------------------------------------------------------------------ #

    @bp.route("/api/telegram/status", methods=["GET"])
    @api_auth_required
    def telegram_status():
        try:
            from services.notifications.telegram_integration import (
                _telegram_service,
                run_async,
            )

            if _telegram_service is None:
                cfg = load_config()
                return jsonify(
                    {
                        "status": "ok",
                        "enabled": cfg.get("enabled", False),
                        "connected": False,
                    }
                )

            health = run_async(_telegram_service.health_check())
            return jsonify({"status": "ok", **health})

        except Exception as exc:
            logger.error(f"Error getting Telegram status: {exc}")
            return jsonify(
                {"status": "error", "message": _("No se pudo obtener el estado.")}
            ), 500

    # ------------------------------------------------------------------ #
    # Send test message                                                    #
    # ------------------------------------------------------------------ #

    @bp.route("/api/telegram/send-test", methods=["POST"])
    @csrf.exempt
    @api_auth_required
    def telegram_send_test():
        try:
            from services.notifications.telegram_integration import (
                send_telegram_notification,
                _telegram_service,
                initialize_telegram_service,
            )

            if _telegram_service is None:
                if not initialize_telegram_service():
                    cfg = load_config()
                    if not cfg.get("enabled"):
                        return jsonify(
                            {
                                "status": "error",
                                "message": _(
                                    "Telegram está deshabilitado en la configuración."
                                ),
                            }
                        ), 400
                    if not cfg.get("recipients"):
                        return jsonify(
                            {
                                "status": "error",
                                "message": _(
                                    "No hay destinatarios configurados para Telegram."
                                ),
                            }
                        ), 400
                    return jsonify(
                        {
                            "status": "error",
                            "message": _(
                                "No se pudo inicializar el servicio Telegram. Verifique las credenciales y la configuración."
                            ),
                        }
                    ), 400

            success = send_telegram_notification(
                notification_type="info",
                message=_("Este es un mensaje de prueba enviado desde SquidStats."),
                source="admin",
            )
            if success:
                return jsonify(
                    {"status": "success", "message": _("Mensaje de prueba enviado.")}
                )

            cfg = load_config()
            if not cfg.get("enabled"):
                message = _(
                    "Telegram está deshabilitado en la configuración."
                )
            elif not cfg.get("recipients"):
                message = _(
                    "No hay destinatarios configurados para Telegram."
                )
            else:
                message = _(
                    "No se pudo enviar el mensaje. Verifique la configuración y los destinatarios."
                )

            return jsonify({"status": "error", "message": message}), 400
        except Exception as exc:
            logger.error(f"Error sending Telegram test message: {exc}")
            return jsonify(
                {"status": "error", "message": _("Error al enviar mensaje de prueba.")}
            ), 500
