"""Admin LDAP / Active Directory configuration routes."""

from flask import jsonify, render_template, request
from flask_babel import gettext as _
from loguru import logger

from services.auth.auth_service import admin_required, api_auth_required
from services.ldap import ldap_config_service, ldap_service


def _load_request_config():
    data = request.get_json(silent=True) or {}
    if isinstance(data, dict) and any(
        key in data for key in ("host", "port", "bind_dn", "base_dn")
    ):
        return data
    cfg = ldap_config_service.load_config()
    return cfg


def register_routes(bp):
    @bp.route("/ldap-config", endpoint="ldap_config")
    @admin_required
    def ldap_config_view():
        cfg = ldap_config_service.load_config()
        return render_template("admin/ldap_config.html", cfg=cfg)

    # ------------------------------------------------------------------
    # Save configuration
    # ------------------------------------------------------------------

    @bp.route("/api/ldap/save-config", methods=["POST"])
    @api_auth_required
    def ldap_save_config():
        data = request.get_json(silent=True) or {}
        try:
            ldap_config_service.save_config(data)
            return jsonify(
                {"status": "success", "message": _("Configuración LDAP guardada.")}
            )
        except Exception as exc:
            logger.error(f"Error al guardar configuración LDAP: {exc}")
            return jsonify(
                {"status": "error", "message": _("Error al guardar la configuración.")}
            ), 500

    @bp.route("/api/ldap/groups", methods=["GET", "POST"])
    @api_auth_required
    def ldap_groups_api():
        if request.method == "GET":
            return jsonify(ldap_config_service.list_groups())

        data = request.get_json(silent=True) or {}
        action = (data.get("action") or "").strip().lower()

        try:
            if action in ("", "list"):
                return jsonify(ldap_config_service.list_groups())
            if action in ("create", "save"):
                return jsonify(ldap_config_service.create_group(data))
            if action in ("add-member", "add-members"):
                return jsonify(ldap_config_service.add_members(data))
            if action == "remove-member":
                return jsonify(ldap_config_service.remove_member(data))
            if action == "delete":
                return jsonify(ldap_config_service.delete_group(data))
            return jsonify(ldap_config_service.list_groups())
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc), "groups": []}), 400
        except Exception as exc:
            logger.exception(f"Unexpected LDAP group error: {exc}")
            return jsonify({"status": "error", "message": _("Error interno en grupos LDAP."), "groups": []}), 500

    # ------------------------------------------------------------------
    # Test connection
    # ------------------------------------------------------------------

    @bp.route("/api/ldap/test", methods=["POST"])
    @api_auth_required
    def ldap_test():
        cfg = request.get_json(silent=True)
        if cfg is None:
            cfg = request.get_json(force=True, silent=True)
        cfg = cfg or {}
        if not cfg:
            cfg = ldap_config_service.load_config()
        if not cfg.get("host"):
            return jsonify(
                {
                    "status": "error",
                    "message": _("No se ha configurado el servidor LDAP."),
                    "cfg": cfg,
                }
            ), 400
        try:
            result = ldap_service.test_connection(cfg)
            return jsonify(result)
        except Exception as exc:
            logger.exception(f"Unexpected error during ldap_test: {exc}")
            return jsonify(
                {
                    "status": "error",
                    "message": _("Error interno al probar LDAP."),
                }
            ), 500

    # ------------------------------------------------------------------
    # Stats (total users / groups)
    # ------------------------------------------------------------------

    @bp.route("/api/ldap/stats", methods=["GET", "POST"])
    @api_auth_required
    def ldap_stats():
        cfg = _load_request_config()
        if not cfg.get("host"):
            return jsonify(
                {
                    "status": "error",
                    "message": _("LDAP no configurado."),
                    "users": 0,
                    "groups": 0,
                    "cfg": cfg,
                }
            ), 400
        result = ldap_service.get_stats(cfg)
        return jsonify(result)

    # ------------------------------------------------------------------
    # Search users
    # ------------------------------------------------------------------

    @bp.route("/api/ldap/search-users", methods=["GET", "POST"])
    @api_auth_required
    def ldap_search_users():
        data = request.get_json(silent=True) or {}
        query = ""
        if request.method == "POST":
            query = (data.get("q") or "").strip()
        if not query:
            query = request.args.get("q", "").strip()
        if not query:
            return jsonify(
                {
                    "status": "error",
                    "message": _("Parámetro 'q' requerido."),
                    "results": [],
                }
            ), 400
        cfg = _load_request_config()
        if not cfg.get("host"):
            return jsonify(
                {"status": "error", "message": _("LDAP no configurado."), "results": []}
            ), 400
        result = ldap_service.search_users(cfg, query)
        return jsonify(result)

    # ------------------------------------------------------------------
    # Search groups
    # ------------------------------------------------------------------

    @bp.route("/api/ldap/search-groups", methods=["GET", "POST"])
    @api_auth_required
    def ldap_search_groups():
        data = request.get_json(silent=True) or {}
        query = ""
        if request.method == "POST":
            query = (data.get("q") or "").strip()
        if not query:
            query = request.args.get("q", "").strip()
        cfg = _load_request_config()
        if not cfg.get("host"):
            return jsonify(
                {"status": "error", "message": _("LDAP no configurado."), "results": []}
            ), 400
        result = ldap_service.search_groups(cfg, query)
        return jsonify(result)

    # ------------------------------------------------------------------
    # User group membership
    # ------------------------------------------------------------------

    @bp.route("/api/ldap/user-groups", methods=["GET", "POST"])
    @api_auth_required
    def ldap_user_groups():
        data = request.get_json(silent=True) or {}
        username = ""
        if request.method == "POST":
            username = (data.get("username") or "").strip()
        if not username:
            username = request.args.get("username", "").strip()
        if not username:
            return jsonify(
                {
                    "status": "error",
                    "message": _("Parámetro 'username' requerido."),
                    "groups": [],
                }
            ), 400
        cfg = _load_request_config()
        if not cfg.get("host"):
            return jsonify(
                {"status": "error", "message": _("LDAP no configurado."), "groups": []}
            ), 400
        result = ldap_service.get_user_groups(cfg, username)
        return jsonify(result)
