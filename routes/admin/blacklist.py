"""Admin blacklist management routes."""

from flask import flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from loguru import logger

from database.database import get_session
from database.models.models import BlacklistDomain, BlockedUser
from services.analytics.blacklist_users import invalidate_blacklist_cache
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
from services.squid.user_restrictions_service import (
    _sync_blocked_file,
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
            blocked_users = session.query(BlockedUser).order_by(BlockedUser.ip).all()
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
            blocked_users=blocked_users,
            custom_enforced=custom_enforced,
        )

    @bp.route("/blacklist/test-connection", methods=["POST"])
    @admin_required
    def blacklist_test_connection():
        host = request.form.get("host") or request.form.get("pihole_host")
        token = request.form.get("token") or request.form.get("api_token")
        if not host:
            flash(_("Host de Pi-hole no proporcionado"), "error")
            return redirect(url_for("admin.manage_blacklist"))
        success, msg = test_pihole_connection(host, token)
        return flash_and_redirect(success, msg, "admin.manage_blacklist")

    @bp.route("/blacklist/sync", methods=["POST"])
    @admin_required
    def blacklist_sync():
        flash(_("Sincronización de listas iniciada (en segundo plano)"), "success")
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
                flash(_("Archivo importado correctamente"), "success")
            except Exception as e:
                logger.exception("Error importando archivo de blacklist")
                flash_error_with_details(_("Error al procesar el archivo"), e)
                return redirect(url_for("admin.manage_blacklist"))

        url = request.form.get("url")
        if url:
            ok, imported_url_domains, err = import_domains_from_url(url)
            if ok:
                url_domains.update(imported_url_domains)
                flash(_("Lista importada desde URL correctamente"), "success")
            else:
                flash(_("Error importando desde URL: %(err)s") % {"err": err}, "error")

        try:
            if file_domains:
                merge_and_save_blacklist(file_domains, source="file")
            if url_domains:
                merge_and_save_blacklist(url_domains, source="url", source_url=url)
            if not file_domains and not url_domains:
                flash(_("No se encontraron dominios para importar"), "warning")
            else:
                invalidate_blacklist_cache()
                flash(_("Blacklist actualizada exitosamente"), "success")
        except Exception as e:
            logger.exception("Error guardando BLACKLIST_DOMAINS")
            flash_error_with_details(_("Error al guardar blacklist"), e)

        return redirect(url_for("admin.manage_blacklist"))

    @bp.route("/blacklist/save-custom", methods=["POST"])
    @admin_required
    def blacklist_save_custom():
        custom = request.form.get("custom_list", "")
        if not custom.strip():
            flash(_("Lista personalizada vacía"), "error")
            return redirect(url_for("admin.manage_blacklist"))

        items = []
        for line in custom.splitlines():
            for part in line.split(","):
                d = part.strip()
                if d:
                    items.append(d)

        try:
            save_custom_list(items)
            invalidate_blacklist_cache()

            cm = get_config_manager()
            if "__custom__" in get_enforced_blocklist_urls(cm):
                ok, msg = enable_single_blocklist(None, cm)
                if ok:
                    flash(
                        _(
                            "Lista personalizada guardada y archivo custom de Squid actualizado"
                        ),
                        "success",
                    )
                else:
                    flash(
                        _(
                            "Lista personalizada guardada en DB, pero no se pudo regenerar el archivo de Squid: %(msg)s"
                        )
                        % {"msg": msg},
                        "error",
                    )
            else:
                flash(_("Lista personalizada guardada en BLACKLIST_DOMAINS"), "success")
        except Exception as e:
            logger.exception("Error guardando lista personalizada")
            flash_error_with_details(_("Error al guardar la lista"), e)

        return redirect(url_for("admin.manage_blacklist"))

    @bp.route("/blacklist/delete-list", methods=["POST"])
    @admin_required
    def blacklist_delete_list():
        url = request.form.get("source_url")
        if not url:
            flash(_("URL no proporcionada"), "error")
            return redirect(url_for("admin.manage_blacklist"))
        cm = get_config_manager()
        count = delete_blacklist_by_source_url(url)
        disable_single_blocklist(url, cm)
        invalidate_blacklist_cache()
        flash(
            _("Lista eliminada: %(url)s (%(count)s dominios)")
            % {"url": url, "count": count},
            "success",
        )
        return redirect(url_for("admin.manage_blacklist"))

    @bp.route("/blacklist/delete-blocked-user", methods=["POST"])
    @admin_required
    def blacklist_delete_blocked_user():
        data = request.get_json(silent=True)
        if data:
            blocked_user_id = data.get("blocked_user_id")
        else:
            blocked_user_id = request.form.get("blocked_user_id")

        if not blocked_user_id:
            message = _("ID del usuario no proporcionado")
            if data:
                return json_error(message)
            flash(message, "error")
            return redirect(url_for("admin.manage_blacklist"))

        try:
            blocked_user_id = int(blocked_user_id)
        except ValueError:
            message = _("ID del usuario inválido")
            if data:
                return json_error(message)
            flash(message, "error")
            return redirect(url_for("admin.manage_blacklist"))

        session = get_session()
        cm = get_config_manager()
        try:
            record = session.query(BlockedUser).filter_by(id=blocked_user_id).first()
            if not record:
                message = _("No se encontró el usuario bloqueado")
                if data:
                    return json_error(message)
                flash(message, "error")
                return redirect(url_for("admin.manage_blacklist"))

            username = record.username or record.ip
            session.delete(record)
            session.commit()
            _sync_blocked_file(session, cm)
            message = _(
                "Usuario bloqueado %(username)s eliminado y archivo de IPs actualizado"
            ) % {"username": username}
            if data:
                return json_success(message)
            flash(message, "success")
            return redirect(url_for("admin.manage_blacklist"))
        except Exception as e:
            session.rollback()
            logger.exception("Error eliminando usuario bloqueado")
            if data:
                return json_error(_("Error al eliminar usuario bloqueado"), 500)
            flash_error_with_details(_("Error al eliminar usuario bloqueado"), e)
        finally:
            session.close()

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
        except Exception:
            logger.exception("Error en toggle de blocklist")
            return json_error(
                "Error interno al cambiar estado de blocklist",
                500,
            )
