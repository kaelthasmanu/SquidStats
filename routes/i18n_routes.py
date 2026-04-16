"""
Internationalization (i18n) routes.
Provides language switching and JS translation endpoint.
"""

from urllib.parse import urlparse

from flask import Blueprint, jsonify, make_response, redirect, request, session
from flask_babel import gettext as _

from config import Config

i18n_bp = Blueprint("i18n", __name__)


@i18n_bp.route("/set-language/<lang>")
def set_language(lang):
    """Set the user's preferred language."""
    supported_locales = tuple(Config.BABEL_SUPPORTED_LOCALES)
    canonical_locales = {locale: locale for locale in supported_locales}
    selected_lang = canonical_locales.get(lang, Config.BABEL_DEFAULT_LOCALE)

    session["lang"] = selected_lang

    referrer = (request.referrer or "").replace("\\", "")
    parsed_referrer = urlparse(referrer)
    redirect_target = (
        referrer if not parsed_referrer.netloc and not parsed_referrer.scheme else "/"
    )

    response = make_response(redirect(redirect_target))
    response.set_cookie(
        "lang", selected_lang, max_age=365 * 24 * 60 * 60, samesite="Lax"
    )
    return response


@i18n_bp.route("/api/translations")
def get_translations():
    """Return JS-needed translations for the current locale."""
    translations = {
        # Common
        "confirm": _("Confirmar"),
        "cancel": _("Cancelar"),
        "save": _("Guardar"),
        "delete": _("Eliminar"),
        "edit": _("Editar"),
        "close": _("Cerrar"),
        "loading": _("Cargando..."),
        "error": _("Error"),
        "success": _("Éxito"),
        "warning": _("Advertencia"),
        "info": _("Información"),
        "yes": _("Sí"),
        "no": _("No"),
        "search": _("Buscar"),
        "actions": _("Acciones"),
        "back": _("Volver"),
        "next": _("Siguiente"),
        "previous": _("Anterior"),
        "of": _("de"),
        "all": _("Todos"),
        "none": _("Ninguno"),
        "active": _("Activo"),
        "inactive": _("Inactivo"),
        "enabled": _("Habilitado"),
        "disabled": _("Deshabilitado"),
        "unknown": _("Desconocido"),
        "no_data": _("Sin datos"),
        "no_results": _("Sin resultados"),
        "required_field": _("Campo requerido"),
        # Connections
        "block_user": _("Bloquear usuario"),
        "unblock_user": _("Desbloquear usuario"),
        "throttle_user": _("Reducir velocidad"),
        "unthrottle_user": _("Restaurar velocidad"),
        "confirm_block": _("¿Estás seguro de que deseas bloquear a este usuario?"),
        "confirm_unblock": _("¿Estás seguro de que deseas desbloquear a este usuario?"),
        "confirm_throttle": _(
            "¿Estás seguro de que deseas reducir la velocidad de este usuario?"
        ),
        "confirm_unthrottle": _(
            "¿Estás seguro de que deseas restaurar la velocidad de este usuario?"
        ),
        "operation_success": _("Operación exitosa"),
        "operation_error": _("Error en la operación"),
        "connection_error": _("Error de conexión"),
        "select_valid_pool": _("Selecciona un delay pool válido"),
        "connections": _("conexiones"),
        "no_active_connections": _("No hay conexiones activas"),
        "anonymous": _("Anónimo"),
        # Dashboard
        "error_loading_data": _("Error al cargar los datos"),
        "no_data_found": _("No se encontraron datos"),
        "active_connections": _("Conexiones activas"),
        "total_bandwidth": _("Ancho de banda total"),
        "unique_users": _("Usuarios únicos"),
        # Notifications
        "notifications": _("Notificaciones"),
        "loading_notifications": _("Cargando notificaciones..."),
        "no_notifications": _("No hay notificaciones"),
        "view_all_notifications": _("Ver todas las notificaciones"),
        "mark_as_read": _("Marcar como leída"),
        "mark_all_read": _("Marcar todas como leídas"),
        "delete_all": _("Eliminar todas"),
        # Squid updates
        "confirm_squid_update": _("¿Deseas actualizar Squid?"),
        "confirm_web_update": _("¿Deseas actualizar SquidStats?"),
        "updating": _("Actualizando..."),
        "update_complete": _("Actualización completada"),
        "update_failed": _("Error en la actualización"),
        # Admin
        "confirm_delete": _("¿Estás seguro de que deseas eliminar esto?"),
        "action_irreversible": _("Esta acción no se puede deshacer"),
        "saved_successfully": _("Guardado correctamente"),
        "deleted_successfully": _("Eliminado correctamente"),
        "error_saving": _("Error al guardar"),
        "error_deleting": _("Error al eliminar"),
        "error_loading": _("Error al cargar"),
        # Reports
        "generating_report": _("Generando reporte..."),
        "report_ready": _("Reporte listo"),
        "download_pdf": _("Descargar PDF"),
        "no_report_data": _("No hay datos para el reporte"),
        "visits": _("Visitas"),
        "number_of_visits": _("Número de Visitas"),
        # Cache
        "cache_hits": _("Aciertos de caché"),
        "cache_misses": _("Fallos de caché"),
        "hit_ratio": _("Tasa de aciertos"),
        # Logs
        "filter_by_date": _("Filtrar por fecha"),
        "filter_by_user": _("Filtrar por usuario"),
        "export": _("Exportar"),
        # Blacklist
        "domain_blocked": _("Dominio bloqueado"),
        "domain_unblocked": _("Dominio desbloqueado"),
        "add_domain": _("Agregar dominio"),
        # Quota
        "quota_exceeded": _("Cuota excedida"),
        "quota_remaining": _("Cuota restante"),
        # ACLs
        "acl_added": _("ACL agregada"),
        "acl_deleted": _("ACL eliminada"),
        "acl_updated": _("ACL actualizada"),
        # Backup
        "creating_backup": _("Creando respaldo..."),
        "backup_created": _("Respaldo creado"),
        "backup_deleted": _("Respaldo eliminado"),
        "confirm_delete_backup": _(
            "¿Estás seguro de que deseas eliminar este respaldo?"
        ),
        "restoring_backup": _("Restaurando respaldo..."),
        # System
        "reloading_squid": _("Recargando Squid..."),
        "restarting_squid": _("Reiniciando Squid..."),
        "squid_reloaded": _("Squid recargado"),
        "squid_restarted": _("Squid reiniciado"),
        # Charts
        "bytes_sent": _("Bytes enviados"),
        "bytes_received": _("Bytes recibidos"),
        "requests": _("Peticiones"),
        "traffic": _("Tráfico"),
        # Date/Time
        "today": _("Hoy"),
        "yesterday": _("Ayer"),
        "last_7_days": _("Últimos 7 días"),
        "last_30_days": _("Últimos 30 días"),
        "from_date": _("Desde"),
        "to_date": _("Hasta"),
        # Audit
        "audit_search": _("Buscar auditoría"),
        "user_activity": _("Actividad del usuario"),
        "date_range": _("Rango de fechas"),
    }
    return jsonify(translations)
