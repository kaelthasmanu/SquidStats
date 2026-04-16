#!/usr/bin/env python3
"""
Auto-translate Spanish msgid strings to English msgstr in a .po file.
Uses a dictionary of known translations for common UI terms.
"""

import re
import sys

# Spanish → English translation dictionary for common UI strings
TRANSLATIONS = {
    # Navigation & General UI
    "Inicio": "Home",
    "Estadísticas": "Statistics",
    "Usuarios": "Users",
    "Reportes": "Reports",
    "Auditoría": "Audit",
    "Blacklist": "Blacklist",
    "Admin": "Admin",
    "Configuración": "Configuration",
    "Acciones": "Actions",
    "Estado": "Status",
    "Buscar": "Search",
    "Buscar...": "Search...",
    "Filtrar": "Filter",
    "Limpiar": "Clear",
    "Cerrar": "Close",
    "Guardar": "Save",
    "Cancelar": "Cancel",
    "Eliminar": "Delete",
    "Editar": "Edit",
    "Crear": "Create",
    "Agregar": "Add",
    "Actualizar": "Update",
    "Volver": "Back",
    "Enviar": "Send",
    "Aceptar": "Accept",
    "Confirmar": "Confirm",
    "Descargar": "Download",
    "Cargar": "Load",
    "Subir": "Upload",
    "Ver": "View",
    "Mostrar": "Show",
    "Ocultar": "Hide",
    "Activar": "Enable",
    "Desactivar": "Disable",
    "Sí": "Yes",
    "No": "No",
    "Todos": "All",
    "Ninguno": "None",
    "Anterior": "Previous",
    "Siguiente": "Next",
    "Primero": "First",
    "Último": "Last",
    "Cargando...": "Loading...",
    "Procesando...": "Processing...",
    "Exportar": "Export",
    "Importar": "Import",
    # Auth
    "Iniciar sesión": "Log In",
    "Cerrar sesión": "Log Out",
    "Contraseña": "Password",
    "Usuario": "User",
    "Nombre de usuario": "Username",
    "Recordarme": "Remember me",
    "Olvidé mi contraseña": "Forgot password",
    "Has cerrado sesión correctamente.": "You have logged out successfully.",
    # Status
    "Activo": "Active",
    "Inactivo": "Inactive",
    "Habilitado": "Enabled",
    "Deshabilitado": "Disabled",
    "Conectado": "Connected",
    "Desconectado": "Disconnected",
    "En línea": "Online",
    "Fuera de línea": "Offline",
    "Nunca": "Never",
    "Pendiente": "Pending",
    "Completado": "Completed",
    "Fallido": "Failed",
    # Table headers & common labels
    "Nombre": "Name",
    "Descripción": "Description",
    "Fecha": "Date",
    "Hora": "Time",
    "Tipo": "Type",
    "Tamaño": "Size",
    "Rol": "Role",
    "IP": "IP",
    "Puerto": "Port",
    "Dominio": "Domain",
    "Dominios": "Domains",
    "URL": "URL",
    "Origen": "Source",
    "Destino": "Destination",
    "Protocolo": "Protocol",
    "Método": "Method",
    "Resultado": "Result",
    "Total": "Total",
    "Promedio": "Average",
    "Máximo": "Maximum",
    "Mínimo": "Minimum",
    "Detalles": "Details",
    "Resumen": "Summary",
    "Último Login": "Last Login",
    "Última conexión": "Last Connection",
    "Fecha de creación": "Creation Date",
    "Acciones": "Actions",
    "ID": "ID",
    # Admin sections
    "Gestión de Usuarios": "User Management",
    "Crear Usuario": "Create User",
    "Editar Usuario": "Edit User",
    "Eliminar Usuario": "Delete User",
    "Panel de Administración": "Administration Panel",
    "Panel de administración del sistema": "System administration panel",
    "Configuración de Squid": "Squid Configuration",
    "Configuración del Sistema": "System Configuration",
    "Variables de Entorno": "Environment Variables",
    "Base de Datos": "Database",
    "Gestión de Base de Datos": "Database Management",
    "Respaldo": "Backup",
    "Respaldos": "Backups",
    "Sistema": "System",
    "Logs": "Logs",
    "Registros": "Records",
    "Notificaciones": "Notifications",
    "Reglas de Acceso": "Access Rules",
    "Listas de Control de Acceso": "Access Control Lists",
    "ACLs": "ACLs",
    "Delay Pools": "Delay Pools",
    "Cuotas": "Quotas",
    # Dashboard
    "Panel principal con conexiones activas": "Main panel with active connections",
    "Conexiones Activas": "Active Connections",
    "Tráfico Total": "Total Traffic",
    "Uso de CPU": "CPU Usage",
    "Uso de Memoria": "Memory Usage",
    "Disco": "Disk",
    "Espacio en Disco": "Disk Space",
    "Tiempo de Actividad": "Uptime",
    "Versión de Squid": "Squid Version",
    # Blacklist
    "Gestión de Blacklist": "Blacklist Management",
    "Lista Negra": "Blacklist",
    "Agregar Dominio": "Add Domain",
    "Importar Lista": "Import List",
    "Exportar Lista": "Export List",
    "Dominios bloqueados": "Blocked Domains",
    "Fuente": "Source",
    "URL no proporcionada": "URL not provided",
    "Host de Pi-hole no proporcionado": "Pi-hole host not provided",
    "Blacklist actualizada exitosamente": "Blacklist updated successfully",
    "Lista personalizada vacía": "Custom list is empty",
    "Lista personalizada guardada en BLACKLIST_DOMAINS": "Custom list saved to BLACKLIST_DOMAINS",
    "Sincronización de listas iniciada (en segundo plano)": "List synchronization started (in background)",
    "Lista importada desde URL correctamente": "List imported from URL successfully",
    "Archivo importado correctamente": "File imported successfully",
    "No se encontraron dominios para importar": "No domains found to import",
    # Reports
    "Generar Reporte": "Generate Report",
    "Reporte Diario": "Daily Report",
    "Reporte Semanal": "Weekly Report",
    "Reporte Mensual": "Monthly Report",
    "Exportar PDF": "Export PDF",
    "Desde": "From",
    "Hasta": "To",
    "Rango de Fechas": "Date Range",
    "Sin datos disponibles": "No data available",
    "Sin datos": "No data",
    # Logs
    "Registros del Sistema": "System Logs",
    "Ver Logs": "View Logs",
    "Registros de Acceso": "Access Logs",
    "Nivel": "Level",
    "Mensaje": "Message",
    "Componente": "Component",
    # Config
    "Variables de entorno guardadas exitosamente": "Environment variables saved successfully",
    "ID de ACL inválido": "Invalid ACL ID",
    "Índice de regla inválido": "Invalid rule index",
    # Errors & Success messages
    "Error": "Error",
    "Éxito": "Success",
    "Advertencia": "Warning",
    "Información": "Information",
    "Error interno del servidor": "Internal server error",
    "Archivo no encontrado": "File not found",
    "Acceso denegado": "Access denied",
    "No autorizado": "Unauthorized",
    "Operación exitosa": "Operation successful",
    "Operación fallida": "Operation failed",
    "Datos inválidos": "Invalid data",
    "Campo requerido": "Required field",
    "Formato inválido": "Invalid format",
    "Error de conexión": "Connection error",
    "Error de autenticación": "Authentication error",
    "Sesión expirada": "Session expired",
    "Usuario no encontrado": "User not found",
    "Error saving configuration": "Error saving configuration",
    "Error saving configuration: %(message)s": "Error saving configuration: %(message)s",
    "Error al procesar el archivo": "Error processing file",
    "Error al guardar blacklist": "Error saving blacklist",
    "Error al guardar la lista": "Error saving list",
    "Error al cargar la vista": "Error loading view",
    "Error importando desde URL: %(err)s": "Error importing from URL: %(err)s",
    "Error al procesar el archivo: %(error)s": "Error processing file: %(error)s",
    "Error al guardar blacklist: %(error)s": "Error saving blacklist: %(error)s",
    "Error al guardar la lista: %(error)s": "Error saving list: %(error)s",
    "Error al cargar la vista: %(error)s": "Error loading view: %(error)s",
    "Lista eliminada: %(url)s (%(count)s dominios)": "List deleted: %(url)s (%(count)s domains)",
    # Squid specific
    "Actualizar paquetes y configuración de Squid": "Update Squid packages and configuration",
    "Actualizar aplicación web SquidStats": "Update SquidStats web application",
    "Squid": "Squid",
    "SquidStats": "SquidStats",
    "Web": "Web",
    "Caché": "Cache",
    "Proxy": "Proxy",
    "SquidStats Monitor": "SquidStats Monitor",
    # Error page
    "Error - Squid Monitor": "Error - Squid Monitor",
    "Volver al Inicio": "Back to Home",
    "Disculpamos las molestias. Por favor, intenta de nuevo más tarde o contacta al soporte si el problema persiste.": "We apologize for the inconvenience. Please try again later or contact support if the problem persists.",
    # Auth page
    "Iniciar Sesión": "Log In",
    "Bienvenido a SquidStats": "Welcome to SquidStats",
    "Ingresa tus credenciales para acceder al sistema": "Enter your credentials to access the system",
    "Recuérdame": "Remember me",
    # Notifications
    "Cargando notificaciones...": "Loading notifications...",
    "Ver todas las notificaciones": "View all notifications",
    "Todas las Notificaciones": "All Notifications",
    "No hay notificaciones": "No notifications",
    "Marcar todo como leído": "Mark all as read",
    "Leer": "Read",
    "No leído": "Unread",
    "Logo SquidStats": "SquidStats Logo",
    "Toggle menu": "Toggle menu",
    # LDAP
    "Configuración LDAP": "LDAP Configuration",
    "Configuración LDAP guardada.": "LDAP configuration saved.",
    "Error al guardar la configuración.": "Error saving configuration.",
    "No se ha configurado el servidor LDAP.": "LDAP server has not been configured.",
    "Error interno al probar LDAP.": "Internal error testing LDAP.",
    "LDAP no configurado.": "LDAP not configured.",
    "Parámetro 'q' requerido.": "Parameter 'q' required.",
    "Parámetro 'username' requerido.": "Parameter 'username' required.",
    "Conexión exitosa al servidor LDAP/AD.": "Successfully connected to LDAP/AD server.",
    # Backup
    "Motor de BD desconocido": "Unknown database engine",
    "Frecuencia inválida": "Invalid frequency",
    "Configuración guardada correctamente": "Configuration saved successfully",
    "Error leyendo salvas": "Error reading backups",
    "Archivo no encontrado": "File not found",
    "Nombre de archivo inválido": "Invalid filename",
    "La salva no existe": "Backup does not exist",
    # Database admin
    "Nombre de tabla no proporcionado": "Table name not provided",
    "Nombre de tabla inválido": "Invalid table name",
    "La tabla no existe": "Table does not exist",
    "No se puede eliminar estas tablas críticas": "Cannot delete these critical tables",
    # Split config
    "Archivo requerido no encontrado. Verifique la configuración del archivo squid.conf.": "Required file not found. Please check the squid.conf file configuration.",
    "No se tienen permisos suficientes para crear los archivos": "Insufficient permissions to create the files",
    "Error de validación de la configuración": "Configuration validation error",
    "Error interno al dividir la configuración": "Internal error splitting the configuration",
    "Archivo requerido no encontrado.": "Required file not found.",
    # Quota
    "Cuota": "Quota",
    "Límite": "Limit",
    "Consumido": "Consumed",
    "Restante": "Remaining",
    # System info
    "Información del Sistema": "System Information",
    "Procesador": "Processor",
    "Memoria RAM": "RAM",
    "Almacenamiento": "Storage",
    "Red": "Network",
    "Interfaz": "Interface",
    "Dirección": "Address",
    # Common phrases
    "Guardar cambios": "Save changes",
    "Guardar Cambios": "Save Changes",
    "Descartar cambios": "Discard changes",
    "¿Estás seguro?": "Are you sure?",
    "Esta acción no se puede deshacer": "This action cannot be undone",
    "Esta acción no se puede deshacer.": "This action cannot be undone.",
    "Confirmar eliminación": "Confirm deletion",
    "Confirmar acción": "Confirm action",
    "Seleccionar todo": "Select all",
    "Deseleccionar todo": "Deselect all",
    "Sin resultados": "No results",
    "Mostrando": "Showing",
    "de": "of",
    "resultados": "results",
    "registros": "records",
    "por página": "per page",
    "Página": "Page",
    "Tabla": "Table",
    "Columna": "Column",
    "Valor": "Value",
    "Fecha y Hora": "Date and Time",
    "Direcciones IP": "IP Addresses",
    "Tráfico": "Traffic",
    "Ancho de Banda": "Bandwidth",
    "Velocidad": "Speed",
    "Conexiones": "Connections",
    "Solicitudes": "Requests",
    "Respuestas": "Responses",
    "Errores": "Errors",
    "Aciertos": "Hits",
    "Fallos": "Misses",
    "Porcentaje": "Percentage",
    "Gráfico": "Chart",
    "Lista": "List",
    "Detalle": "Detail",
    "Información": "Information",
    "Aviso": "Notice",
    "Atención": "Attention",
    "Importante": "Important",
    "Nota": "Note",
    # Login specific
    "¡Bienvenido, %(username)s!": "Welcome, %(username)s!",
    # Admin specific
    "Gestión de Configuración de Squid": "Squid Configuration Management",
    "Editar Configuración": "Edit Configuration",
    "Ver Configuración": "View Configuration",
    "Dividir Configuración": "Split Configuration",
    "Configuración General": "General Configuration",
    "Guardar Configuración": "Save Configuration",
    "Restablecer": "Reset",
    "Aplicar": "Apply",
    "Recargar": "Reload",
    "Reiniciar": "Restart",
    "Detener": "Stop",
    "Iniciar": "Start",
    "Estado del Servicio": "Service Status",
    "Servicio activo": "Service active",
    "Servicio inactivo": "Service inactive",
    "Acciones del Servicio": "Service Actions",
    "Recargar Squid": "Reload Squid",
    "Reiniciar Squid": "Restart Squid",
    # Form labels
    "Nombre:": "Name:",
    "Tipo:": "Type:",
    "Valores:": "Values:",
    "Comentario:": "Comment:",
    "Seleccionar": "Select",
    "Seleccione una opción": "Select an option",
    "Requerido": "Required",
    "Opcional": "Optional",
    "Ejemplo:": "Example:",
    # Audit
    "Auditoría del Sistema": "System Audit",
    "Evento": "Event",
    "Acción": "Action",
    "Objeto": "Object",
    "Cambios": "Changes",
    "Antes": "Before",
    "Después": "After",
    "Sin cambios": "No changes",
    # Delay Pools
    "Gestión de Delay Pools": "Delay Pool Management",
    "Pool": "Pool",
    "Clase": "Class",
    "Velocidad Individual": "Individual Speed",
    "Velocidad Agregada": "Aggregate Speed",
    "Red Asociada": "Associated Network",
    # Misc
    "Información general": "General Information",
    "Confirmar": "Confirm",
    "Procesando": "Processing",
    "Operación completada": "Operation completed",
    "Operación cancelada": "Operation cancelled",
    "Sin datos disponibles": "No data available",
    "Versión": "Version",
    "Licencia": "License",
    "Documentación": "Documentation",
    "Soporte": "Support",
    "Ayuda": "Help",
    "Acerca de": "About",
    "Términos de Uso": "Terms of Use",
    "Política de Privacidad": "Privacy Policy",
    "Derechos Reservados": "All Rights Reserved",
}


def translate_msgid(msgid):
    """Try to translate a msgid using the dictionary."""
    # Direct match
    if msgid in TRANSLATIONS:
        return TRANSLATIONS[msgid]

    # Try case-insensitive match
    msgid_lower = msgid.lower()
    for es, en in TRANSLATIONS.items():
        if es.lower() == msgid_lower:
            return en

    return None


def process_po_file(filepath):
    """Process a .po file and fill in English translations."""
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # Parse the .po file
    lines = content.split("\n")
    result = []
    i = 0
    translated_count = 0
    untranslated = []
    total_msgids = 0

    while i < len(lines):
        line = lines[i]

        # Detect msgid
        if line.startswith('msgid "'):
            msgid_lines = [line]
            # Collect multi-line msgid
            j = i + 1
            while j < len(lines) and lines[j].startswith('"'):
                msgid_lines.append(lines[j])
                j += 1

            # Extract the full msgid text
            msgid_text = ""
            for ml in msgid_lines:
                m = re.match(r'(?:msgid )?"(.*)"', ml)
                if m:
                    msgid_text += m.group(1)

            # Skip the empty header msgid
            if msgid_text == "":
                for ml in msgid_lines:
                    result.append(ml)
                i = j
                continue

            total_msgids += 1

            # Find the corresponding msgstr
            msgstr_idx = j
            if msgstr_idx < len(lines) and lines[msgstr_idx].startswith('msgstr "'):
                msgstr_line = lines[msgstr_idx]
                m = re.match(r'msgstr "(.*)"', msgstr_line)
                existing_msgstr = m.group(1) if m else ""

                # Only translate if msgstr is empty
                if not existing_msgstr:
                    translation = translate_msgid(msgid_text)
                    if translation:
                        # Add the msgid lines
                        for ml in msgid_lines:
                            result.append(ml)
                        # Replace msgstr
                        escaped = translation.replace('"', '\\"')
                        result.append(f'msgstr "{escaped}"')
                        translated_count += 1
                        i = msgstr_idx + 1
                        # Skip any continuation lines of msgstr
                        while i < len(lines) and lines[i].startswith('"'):
                            i += 1
                        continue
                    else:
                        untranslated.append(msgid_text)

            # No translation found - keep original
            for ml in msgid_lines:
                result.append(ml)
            i = j
            continue

        result.append(line)
        i += 1

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(result))

    return translated_count, total_msgids, untranslated


def main():
    po_file = (
        sys.argv[1] if len(sys.argv) > 1 else "translations/en/LC_MESSAGES/messages.po"
    )

    print(f"Processing: {po_file}")
    translated, total, untranslated = process_po_file(po_file)

    print(f"Translated: {translated}/{total} strings")
    print(f"Remaining: {len(untranslated)} strings need manual translation")

    if untranslated:
        print("\nUntranslated strings (first 50):")
        for s in untranslated[:50]:
            print(f"  - {s}")
        if len(untranslated) > 50:
            print(f"  ... and {len(untranslated) - 50} more")


if __name__ == "__main__":
    main()
