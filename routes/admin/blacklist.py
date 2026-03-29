"""Admin blacklist management routes."""

from flask import flash, redirect, render_template, request, url_for
from loguru import logger

from database.database import get_session
from database.models.models import BlacklistDomain
from services.auth.auth_service import admin_required, api_auth_required
from services.database.admin_helpers import load_env_vars
from services.security.blacklist_service import (
    delete_blacklist_by_source_url,
    get_url_blacklists_with_counts,
    import_domains_from_file,
    import_domains_from_url,
    merge_and_save_blacklist,
    save_custom_list,
    test_pihole_connection,
)
from services.security.blocklist_enforcement import (
    disable_single_blocklist,
    enable_single_blocklist,
    get_enforced_blocklist_urls,
)

from .helpers import (
    flash_and_redirect,
    flash_error_with_details,
    get_config_manager,
    json_error,
    json_success,
)


def register_routes(bp):
    @bp.route("/blacklist", methods=["GET"])
    @admin_required
    def manage_blacklist():
        """Render the blacklist management UI."""
        env_vars = load_env_vars()
        cm = get_config_manager()

        session = get_session()
        try:
            rows = (
                session.query(BlacklistDomain)
                .filter(
                    BlacklistDomain.active == 1,
                    BlacklistDomain.source.in_(["custom", "env_migration"]),
                )
                .order_by(BlacklistDomain.domain)
                .all()
            )
            blacklist = "\n".join([r.domain for r in rows])
        finally:
            session.close()

        url_lists = get_url_blacklists_with_counts()

        enforced_urls = get_enforced_blocklist_urls(cm)
        for item in url_lists:
            item["enforced"] = item["source_url"] in enforced_urls
        custom_enforced = "__custom__" in enforced_urls

        return render_template(
            "admin/blacklist.html",
            env_vars=env_vars,
            blacklist=blacklist,
            url_lists=url_lists,
            custom_enforced=custom_enforced,
        )

    @bp.route("/blacklist/test-connection", methods=["POST"])
    @admin_required
    def blacklist_test_connection():
        host = request.form.get("host") or request.form.get("pihole_host")
        token = request.form.get("token") or request.form.get("api_token")
        if not host:
            flash("Host de Pi-hole no proporcionado", "error")
            return redirect(url_for("admin.manage_blacklist"))
        success, msg = test_pihole_connection(host, token)
        return flash_and_redirect(success, msg, "admin.manage_blacklist")

    @bp.route("/blacklist/sync", methods=["POST"])
    @admin_required
    def blacklist_sync():
        flash("Sincronización de listas iniciada (en segundo plano)", "success")
        return redirect(url_for("admin.manage_blacklist"))

    @bp.route("/blacklist/import", methods=["POST"])
    @admin_required
    def blacklist_import():
        file_domains: set = set()
        url_domains: set = set()

        uploaded = request.files.get("file")
        if uploaded and uploaded.filename:
            try:
                file_domains = import_domains_from_file(uploaded)
                flash("Archivo importado correctamente", "success")
            except Exception as e:
                logger.exception("Error importando archivo de blacklist")
                flash_error_with_details("Error al procesar el archivo", e)
                return redirect(url_for("admin.manage_blacklist"))

        url = request.form.get("url")
        if url:
            ok, imported_url_domains, err = import_domains_from_url(url)
            if ok:
                url_domains.update(imported_url_domains)
                flash("Lista importada desde URL correctamente", "success")
            else:
                flash(f"Error importando desde URL: {err}", "error")

        try:
            if file_domains:
                merge_and_save_blacklist(file_domains, source="file")
            if url_domains:
                merge_and_save_blacklist(url_domains, source="url", source_url=url)
            if not file_domains and not url_domains:
                flash("No se encontraron dominios para importar", "warning")
            else:
                flash("Blacklist actualizada exitosamente", "success")
        except Exception as e:
            logger.exception("Error guardando BLACKLIST_DOMAINS")
            flash_error_with_details("Error al guardar blacklist", e)

        return redirect(url_for("admin.manage_blacklist"))

    @bp.route("/blacklist/save-custom", methods=["POST"])
    @admin_required
    def blacklist_save_custom():
        custom = request.form.get("custom_list", "")
        if not custom.strip():
            flash("Lista personalizada vacía", "error")
            return redirect(url_for("admin.manage_blacklist"))

        items = []
        for line in custom.splitlines():
            for part in line.split(","):
                d = part.strip()
                if d:
                    items.append(d)

        try:
            save_custom_list(items)

            cm = get_config_manager()
            if "__custom__" in get_enforced_blocklist_urls(cm):
                ok, msg = enable_single_blocklist(None, cm)
                if ok:
                    flash("Lista personalizada guardada y archivo custom de Squid actualizado", "success")
                else:
                    flash(
                        f"Lista personalizada guardada en DB, pero no se pudo regenerar el archivo de Squid: {msg}",
                        "error",
                    )
            else:
                flash("Lista personalizada guardada en BLACKLIST_DOMAINS", "success")
        except Exception as e:
            logger.exception("Error guardando lista personalizada")
            flash_error_with_details("Error al guardar la lista", e)

        return redirect(url_for("admin.manage_blacklist"))

    @bp.route("/blacklist/delete-list", methods=["POST"])
    @admin_required
    def blacklist_delete_list():
        url = request.form.get("source_url")
        if not url:
            flash("URL no proporcionada", "error")
            return redirect(url_for("admin.manage_blacklist"))
        cm = get_config_manager()
        count = delete_blacklist_by_source_url(url)
        disable_single_blocklist(url, cm)
        flash(f"Lista eliminada: {url} ({count} dominios)", "success")
        return redirect(url_for("admin.manage_blacklist"))

    @bp.route("/api/blocklist/toggle", methods=["POST"])
    @api_auth_required
    def blocklist_toggle():
        """Toggle Squid enforcement for a single blocklist.

        Expects JSON: ``{"source_url": "...", "enable": true/false}``
        Use ``source_url: null`` for the custom/manual list.
        """
        data = request.get_json()
        if data is None:
            return json_error("JSON inválido")

        source_url = data.get("source_url")
        enable = data.get("enable", False)
        cm = get_config_manager()

        try:
            if enable:
                ok, msg = enable_single_blocklist(source_url, cm)
            else:
                ok, msg = disable_single_blocklist(source_url, cm)

            if ok:
                return json_success(msg)
            return json_error(msg)
        except Exception as e:
            logger.exception("Error en toggle de blocklist")
            return json_error(
                "Error interno al cambiar estado de blocklist",
                500,
                details=str(e),
            )
