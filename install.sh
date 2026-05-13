#!/bin/sh

# Variable global para modo no interactivo
NON_INTERACTIVE=false
# Tipo de distribución detectada: debian | alpine
DISTRO_TYPE=""
# Archivo de log
LOG_FILE="/tmp/squidstats_install.log"

init_log() {
    local install_dir="${1:-}"
    # Si tenemos directorio de instalación, mover el log ahí
    if [ -n "$install_dir" ] && [ -d "$install_dir" ]; then
        mkdir -p "$install_dir/logs"
        local new_log="$install_dir/logs/install.log"
        if [ -f "$LOG_FILE" ] && [ "$LOG_FILE" != "$new_log" ]; then
            cat "$LOG_FILE" >> "$new_log"
            rm -f "$LOG_FILE"
        fi
        LOG_FILE="$new_log"
    fi
    echo "" >> "$LOG_FILE"
    echo "========================================" >> "$LOG_FILE"
    echo "  SquidStats Installer - $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
    echo "  Argumentos: $*" >> "$LOG_FILE"
    echo "========================================" >> "$LOG_FILE"
}

log_msg() {
    local level="$1"
    shift
    local msg="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $msg" >> "$LOG_FILE"
}

error() {
    echo -e "\n\033[1;41m$1\033[0m\n"
    log_msg "ERROR" "$1"
}

ok() {
    echo -e "\n\033[1;42m$1\033[0m\n"
    log_msg "OK" "$1"
}

isContainer() {
    grep -qaE 'docker|containerd' /proc/1/cgroup 2>/dev/null && return 0
    [ -f /.dockerenv ] && return 0
    return 1
}

detectDistro() {
    log_msg "INFO" "Detectando distribución del sistema..."
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case "$ID" in
            alpine)
                DISTRO_TYPE="alpine"
                ;;
            debian|ubuntu|linuxmint|pop|raspbian|kali)
                DISTRO_TYPE="debian"
                ;;
            *)
                # Intentar detectar por familia
                if echo "$ID_LIKE" | grep -qi "debian"; then
                    DISTRO_TYPE="debian"
                elif echo "$ID_LIKE" | grep -qi "alpine"; then
                    DISTRO_TYPE="alpine"
                else
                    error "Distribución no soportada: $ID ($PRETTY_NAME)\nDistribuciones soportadas: Debian/Ubuntu, Alpine Linux"
                    exit 1
                fi
                ;;
        esac
    elif [ -f /etc/alpine-release ]; then
        DISTRO_TYPE="alpine"
    elif [ -f /etc/debian_version ]; then
        DISTRO_TYPE="debian"
    else
        error "No se pudo detectar la distribución del sistema operativo"
        exit 1
    fi
    log_msg "INFO" "Distribución detectada: $DISTRO_TYPE"
    echo "Distribución detectada: $DISTRO_TYPE"
}

checkSudo() {
    if [ "$(id -u)" -ne 0 ]; then
        error "ERROR: Este script debe ejecutarse como root."
        exit 1
    fi
}

installDependencies() {
    local install_dir="${1:-/opt/SquidStats}"
    local venv_dir="$install_dir/venv"

    log_msg "INFO" "Iniciando instalación de dependencias en $install_dir"

    if [ ! -d "$venv_dir" ]; then
        echo "El entorno virtual no existe en $venv_dir, creándolo..."
        log_msg "INFO" "Creando entorno virtual en $venv_dir"
        python3 -m venv "$venv_dir" || {
            error "Error al crear el entorno virtual en $venv_dir"
            return 1
        }
        ok "Entorno virtual creado correctamente en $venv_dir"
    fi

    echo "Instalando dependencias en el entorno virtual..."

    log_msg "INFO" "Actualizando pip..."
    "$venv_dir/bin/pip" install --upgrade pip || {
        log_msg "ERROR" "Error al actualizar pip"
        return 1
    }
    log_msg "INFO" "Instalando paquetes desde requirements.txt"
    "$venv_dir/bin/pip" install -r "$install_dir/requirements.txt" || {
        error "Error al instalar dependencias"
        return 1
    }

    ok "Dependencias instaladas correctamente en el entorno virtual"
    return 0
}
#  python3-pymysql delete from packages
checkPackages() {
    #local packages=("git" "python3" "python3-pip" "python3-venv" "libmariadb-dev" "curl" "build-essential" "libssl-dev" "python3-dev" "libpq-dev") # C-ICAP Implementation not using for now libicapapi-dev
    local packages=""
    local missing=""

    log_msg "INFO" "Verificando paquetes del sistema ($DISTRO_TYPE)"

    if [ "$DISTRO_TYPE" = "alpine" ]; then
        packages="git python3 py3-pip py3-virtualenv mariadb-dev curl build-base openssl-dev python3-dev postgresql-dev openrc"

        for pkg in $packages; do
            if ! apk info -e "$pkg" >/dev/null 2>&1; then
                missing="$missing $pkg"
            fi
        done

        if [ -n "$missing" ]; then
            log_msg "INFO" "Paquetes faltantes (alpine):$missing"
            echo "Instalando paquetes faltantes:$missing"
            apk update

            if ! apk add --no-cache $missing; then
                error "ERROR: Compruebe la versión de su Alpine Linux (se recomienda 3.18+)"
                exit 1
            fi

            ok "Paquetes instalados correctamente"
        else
            log_msg "INFO" "Todos los paquetes del sistema ya están instalados"
            echo "Todos los paquetes necesarios ya están instalados"
        fi
    else
        packages="git python3 python3-pip python3-venv libmariadb-dev curl build-essential libssl-dev python3-dev libpq-dev libcairo2-dev libpango1.0-dev"

        for pkg in $packages; do
            if ! dpkg -l | grep -q "^ii  $pkg "; then
                missing="$missing $pkg"
            fi
        done

        if [ -n "$missing" ]; then
            log_msg "INFO" "Paquetes faltantes (debian):$missing"
            echo "Instalando paquetes faltantes:$missing"
            export DEBIAN_FRONTEND=noninteractive
            apt-get update

            if ! apt-get install -y $missing; then
                error "ERROR: Compruebe la versión de su OS se recomienda Ubuntu20.04+ o Debian12+"
                exit 1
            fi

            ok "Paquetes instalados correctamente"
        else
            log_msg "INFO" "Todos los paquetes del sistema ya están instalados"
            echo "Todos los paquetes necesarios ya están instalados"
        fi
    fi
}

checkSquidLog() {
    local log_file="/var/log/squid/access.log"
    log_msg "INFO" "Verificando log de Squid en $log_file"

    if [ ! -f "$log_file" ]; then
        error "¡ADVERTENCIA!: No hemos encontrado el log en la ruta por defecto. Recargue su squid, navegue y genere logs para crearlo"
        return 1
    else
        log_msg "INFO" "Archivo de log de Squid encontrado: $log_file"
        echo "Archivo de log de Squid encontrado: $log_file"
        return 0
    fi
}

findInstallDir() {
    local destinos="/opt/SquidStats /usr/share/squidstats /opt/squidstats"

    # Agregar el directorio actual si contiene archivos de SquidStats
    if [ -f "app.py" ] && [ -f "requirements.txt" ] && [ -d ".git" ]; then
        destinos="$(pwd) $destinos"
    fi

    for dir in $destinos; do
        if [ -f "$dir/app.py" ] && [ -f "$dir/requirements.txt" ]; then
            log_msg "INFO" "Directorio de instalación encontrado: $dir"
            echo "$dir"
            return 0
        fi
    done

    log_msg "WARN" "No se encontró directorio de instalación"
    return 1
}

updateOrCloneRepo() {
    local repo_url="https://github.com/kaelthasmanu/SquidStats.git"
    local branch="main"
    local env_exists=false
    local found_dir=""

    log_msg "INFO" "Iniciando actualización/clonación del repositorio"
    found_dir=$(findInstallDir)

    if [ -z "$found_dir" ]; then
        log_msg "INFO" "No se encontró instalación existente, clonando repositorio en /opt/SquidStats"
        echo "No se encontró instalación existente, clonando repositorio en /opt/SquidStats..."
        if git clone "$repo_url" /opt/SquidStats && cd /opt/SquidStats && git checkout "$branch"; then
            log_msg "OK" "Repositorio clonado exitosamente en /opt/SquidStats"
            echo "✅ Repositorio clonado exitosamente en /opt/SquidStats"
            return 0
        else
            log_msg "ERROR" "Error al clonar el repositorio"
            echo "❌ Error al clonar el repositorio."
            return 1
        fi
    fi

    if [ "$found_dir" = "/usr/share/squidstats" ]; then
        log_msg "WARN" "Instalación .deb detectada en /usr/share/squidstats, no se puede actualizar con git"
        echo "ℹ️ Instalación detectada en /usr/share/squidstats. Esta versión fue instalada desde un .deb y no puede actualizarse con git."
        echo "Por favor, use el gestor de paquetes de su distribución para actualizar."
        return 1
    fi

    log_msg "INFO" "Actualizando repositorio en $found_dir"
    echo "El directorio $found_dir ya existe, intentando actualizar con git pull..."
    cd "$found_dir"

    if [ -d ".git" ]; then
        if [ -f ".env" ]; then
            env_exists=true
            log_msg "INFO" "Respaldando archivo .env"
            echo ".env existente detectado, se preservará"
            cp .env /tmp/.env.backup
        fi

        remote_url=$(git remote get-url origin 2>/dev/null || true)
        if [ -n "$remote_url" ] && echo "$remote_url" | grep -qE '^(git@|ssh://)github.com[:/]'; then
            log_msg "INFO" "Remote origin usa SSH ($remote_url), cambiando a HTTPS"
            git remote set-url origin "$repo_url" >> "$LOG_FILE" 2>&1 || {
                error "No se pudo actualizar la URL remota a HTTPS"
                return 1
            }
            log_msg "INFO" "Remote origin actualizado a $repo_url"
        fi

        if git fetch origin "$branch" && git checkout "$branch" && git pull origin "$branch"; then
            [ "$env_exists" = true ] && mv /tmp/.env.backup .env
            log_msg "OK" "Repositorio actualizado exitosamente en la rama '$branch'"
            echo "✅ Repositorio actualizado exitosamente en la rama '$branch'"
            return 0
        else
            log_msg "ERROR" "Error al actualizar el repositorio con git pull"
            echo "❌ Error al actualizar el repositorio."
            return 1
        fi
    else
        log_msg "ERROR" "El directorio $found_dir no es un repositorio git"
        echo "⚠️ El directorio $found_dir existe pero no es un repositorio git. No se puede actualizar automáticamente."
        return 1
    fi
}

updateEnvVersion() {
    local install_dir="${1:-/opt/SquidStats}"
    local CURRENT_VERSION="2.3.2"  # Variable de versión actual del script
    local env_file="$install_dir/.env"
    
    log_msg "INFO" "Verificando versión en .env ($env_file)"
    
    if [ ! -f "$env_file" ]; then
        log_msg "WARN" "Archivo .env no encontrado en $env_file"
        echo "⚠️ Archivo .env no encontrado en $env_file"
        return 1
    fi
    
    # Leer la versión actual del .env
    local env_version=$(grep "^VERSION=" "$env_file" | cut -d'=' -f2)
    
    # Comparar versiones
    if [ "$env_version" != "$CURRENT_VERSION" ]; then
        log_msg "INFO" "Actualizando VERSION de $env_version a $CURRENT_VERSION"
        echo "Actualizando VERSION de $env_version a $CURRENT_VERSION en .env..."
        
        # Verificar si existe la línea VERSION en .env
        if grep -q "^VERSION=" "$env_file"; then
            # Actualizar VERSION existente
            sed -i "s/^VERSION=.*/VERSION=$CURRENT_VERSION/" "$env_file"
            log_msg "OK" "VERSION actualizada a $CURRENT_VERSION en .env"
            echo "✅ VERSION actualizada a $CURRENT_VERSION en .env"
        else
            # Agregar VERSION al inicio del archivo si no existe
            sed -i "1iVERSION=$CURRENT_VERSION" "$env_file"
            log_msg "OK" "VERSION agregada: $CURRENT_VERSION en .env"
            echo "✅ VERSION agregada: $CURRENT_VERSION en .env"
        fi
    else
        log_msg "INFO" "VERSION ya está actualizada ($CURRENT_VERSION)"
        echo "✓ VERSION ya está actualizada ($CURRENT_VERSION)"
    fi
    
    return 0
}

createEnvFile() {
    local install_dir="${1:-/opt/SquidStats}"
    local env_file="$install_dir/.env"

    log_msg "INFO" "Verificando archivo .env en $env_file"

    if [ -f "$env_file" ]; then
        log_msg "INFO" "El archivo .env ya existe en $env_file"
        echo "El archivo .env ya existe en $env_file."
        return 0
    else
        log_msg "INFO" "Creando archivo .env en $env_file"
        echo "Creando archivo de configuración .env..."
        cat >"$env_file" <<EOF
VERSION=2.3.2
SQUID_HOST=127.0.0.1
SQUID_PORT=3128
SQUID_HOSTS=
LOG_FORMAT=DETAILED
FLASK_DEBUG=True
DATABASE_TYPE=SQLITE
SQUID_LOG=/var/log/squid/access.log
SQUID_CACHE_LOG=/var/log/squid/cache.log
DATABASE_STRING_CONNECTION=$install_dir/squidstats.db
REFRESH_INTERVAL=60
HTTP_PROXY=""
HTTPS_PROXY=
NO_PROXY=
SQUID_CONFIG_PATH=/etc/squid/squid.conf
ACL_FILES_DIR=/etc/squid/config/acls
LISTEN_HOST=0.0.0.0
LISTEN_PORT=5000
FIRST_PASSWORD="admin"
JWT_EXPIRY_HOURS=24
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_DURATION_MINUTES=15
EOF
        ok "Archivo .env creado correctamente en $env_file"
        return 0
    fi
}

createService() {
    local install_dir="${1:-/opt/SquidStats}"

    log_msg "INFO" "Creando servicio del sistema en $install_dir"

    if isContainer; then
        log_msg "WARN" "Entorno contenedor detectado, no se creará servicio"
        echo "⚠️ Entorno contenedor detectado. No se creará servicio."
        echo "Para iniciar manualmente:"
        echo "$install_dir/venv/bin/python3 $install_dir/app.py"
        ok "Instalación completada en modo contenedor"
        return 0
    fi

    if [ "$DISTRO_TYPE" = "alpine" ]; then
        
        local service_file="/etc/init.d/squidstats"
        local template="$install_dir/utils/openRC"

        if [ -f "$service_file" ]; then
            log_msg "INFO" "El servicio ya existe en $service_file"
            echo "El servicio ya existe en $service_file, no se realizan cambios."
            return 0
        fi

        if [ ! -f "$template" ]; then
            error "Plantilla de servicio OpenRC no encontrada en $template"
            return 1
        fi

        mkdir -p /etc/init.d

        echo "Creando servicio OpenRC en $service_file..."
        log_msg "INFO" "Creando servicio OpenRC en $service_file"
        sed "s|__INSTALL_DIR__|$install_dir|g" "$template" > "$service_file"
        chmod +x "$service_file"

        if command -v rc-update >/dev/null 2>&1; then
            rc-update add squidstats default
            chmod 755 /etc/init.d/squidstats

            # Verifica si OpenRC ya está inicializado
            if [ -f /run/openrc/softlevel ]; then
                echo "✓ OpenRC ya está inicializado"
                rc-status --all | head -5
                
            else
                echo "✗ OpenRC NO está inicializado... intentando inicializarlo..."
                openrc boot
            fi
            
            rc-service squidstats start
            ok "Servicio OpenRC creado y iniciado correctamente"
        else
            echo "⚠️ OpenRC no está activo (probable entorno Docker/contenedor). El servicio se ha creado en $service_file."
            echo "Para iniciarlo manualmente: $install_dir/venv/bin/python3 $install_dir/app.py"
            ok "Archivo de servicio OpenRC creado correctamente"
        fi
    else
        local service_file="/etc/systemd/system/squidstats.service"
        local template="$install_dir/utils/squidstats.service"

        if [ -f "$service_file" ]; then
            log_msg "INFO" "El servicio ya existe en $service_file"
            echo "El servicio ya existe en $service_file, no se realizan cambios."
            return 0
        fi

        if [ ! -f "$template" ]; then
            error "Plantilla de servicio systemd no encontrada en $template"
            return 1
        fi

        echo "Creando servicio systemd en $service_file..."
        log_msg "INFO" "Creando servicio systemd en $service_file"
        sed "s|__INSTALL_DIR__|$install_dir|g" "$template" > "$service_file"

        systemctl daemon-reload
        systemctl enable squidstats.service
        systemctl start squidstats.service
        ok "Servicio systemd creado y iniciado correctamente"
    fi
}

configureDatabase() {
    local install_dir="${1:-/opt/SquidStats}"
    local env_file="$install_dir/.env"

    log_msg "INFO" "Iniciando configuración de base de datos"

    # En modo no interactivo, usar SQLite por defecto
    if [ "$NON_INTERACTIVE" = true ]; then
        log_msg "INFO" "Modo no interactivo: configurando SQLite por defecto"
        echo "Modo no interactivo: configurando SQLite por defecto"
        choice=1
    else
        echo -e "\n\033[1;44mCONFIGURACIÓN DE BASE DE DATOS\033[0m"
        echo "Seleccione el tipo de base de datos:"
        echo "1) SQLite (por defecto)"
        echo "2) MariaDB (necesitas tener mariadb ejecutándose)"

        while true; do
            read -p "Opción [1/2]: " choice
            case $choice in
            1 | "") break ;;
            2) break ;;
            *) error "Opción inválida. Intente nuevamente." ;;
            esac
        done
    fi

    case $choice in
    2)
        while true; do
            read -p "Ingrese cadena de conexión (mysql+pymysql://user:clave@host:port/db): " conn_str

            case "$conn_str" in
            mysql+pymysql://*) ;;
            *) error "Formato inválido. Debe comenzar con: mysql+pymysql://"
               continue ;;
            esac

            validation_result=$(python3 $install_dir/utils/validateString.py "$conn_str" 2>&1)
            exit_code=$?

            if [ "$exit_code" -eq 0 ]; then
                sed -i "s|^DATABASE_TYPE=.*|DATABASE_TYPE=MARIADB|" "$env_file"

                # validation_result tiene la cadena codificada, escapamos para sed
                escaped_conn_str=$(printf '%s\n' "$validation_result" | sed -e 's/[\/&]/\\&/g')
                sed -i "s|^DATABASE_STRING_CONNECTION=.*|DATABASE_STRING_CONNECTION=$escaped_conn_str|" "$env_file"

                ok "Configuración MariaDB actualizada!"
                break
            else
                error "Error en la cadena:\n${validation_result#ERROR: }"
            fi
        done
        ;;
    *)
        sqlite_path="$install_dir/squidstats.db"
        sed -i "s|^DATABASE_TYPE=.*|DATABASE_TYPE=SQLITE|" "$env_file"
        sed -i "s|^DATABASE_STRING_CONNECTION=.*|DATABASE_STRING_CONNECTION=$sqlite_path|" "$env_file"
        ok "Configuración SQLite establecida!"
        ;;
    esac
}

stopAndRemoveService() {
    log_msg "INFO" "Deteniendo y eliminando servicio"
    if [ "$DISTRO_TYPE" = "alpine" ]; then
        local service_file="/etc/init.d/squidstats"
        if [ -f "$service_file" ]; then
            if command -v rc-service >/dev/null 2>&1; then
                echo "Deteniendo servicio squidstats..."
                rc-service squidstats stop 2>/dev/null || true

                echo "Deshabilitando servicio squidstats..."
                rc-update del squidstats default 2>/dev/null || true
            fi

            echo "Eliminando archivo de servicio..."
            rm -f "$service_file"

            ok "Servicio squidstats (OpenRC) eliminado"
        else
            echo "Servicio squidstats no encontrado"
        fi
    else
        local service_file="/etc/systemd/system/squidstats.service"
        if [ -f "$service_file" ]; then
            echo "Deteniendo servicio squidstats..."
            systemctl stop squidstats.service 2>/dev/null || true

            echo "Deshabilitando servicio squidstats..."
            systemctl disable squidstats.service 2>/dev/null || true

            echo "Eliminando archivo de servicio..."
            rm -f "$service_file"

            systemctl daemon-reload
            ok "Servicio squidstats (systemd) eliminado"
        else
            echo "Servicio squidstats no encontrado"
        fi
    fi
}

restartService() {
    log_msg "INFO" "Reiniciando servicio squidstats"
    if [ "$DISTRO_TYPE" = "alpine" ]; then
        if command -v rc-service >/dev/null 2>&1; then
            rc-service squidstats restart
            log_msg "OK" "Servicio reiniciado (OpenRC)"
        else
            log_msg "WARN" "OpenRC no disponible"
            echo "⚠️ OpenRC no disponible, reinicie manualmente la aplicación"
        fi
    else
        systemctl restart squidstats.service
        log_msg "OK" "Servicio reiniciado (systemd)"
    fi
}

uninstallSquidStats() {
    local destino
    destino=$(findInstallDir)

    log_msg "INFO" "Iniciando proceso de desinstalación"
    echo -e "\n\033[1;43mDESINSTALACIÓN DE SQUIDSTATS\033[0m"
    echo "Esta operación eliminará completamente SquidStats del sistema."

    if [ -z "$destino" ]; then
        echo "No se encontró ninguna instalación de SquidStats."
        log_msg "WARN" "No se encontró directorio de instalación para desinstalar"
        return 1
    fi

    echo "Instalación detectada en: $destino"
    
    # En modo no interactivo, proceder sin confirmación
    if [ "$NON_INTERACTIVE" = true ]; then
        echo "Modo no interactivo: procediendo con la desinstalación"
        confirm="s"
    else
        echo "¿Está seguro de que desea continuar? (s/N)"
        read -p "Respuesta: " confirm
    fi

    if [ "$confirm" != "s" ] && [ "$confirm" != "S" ]; then
        log_msg "INFO" "Desinstalación cancelada por el usuario"
        echo "Desinstalación cancelada."
        return 0
    fi

    log_msg "INFO" "Confirmada desinstalación de $destino, procediendo..."
    echo "Iniciando desinstalación..."

    stopAndRemoveService
    
    if [ -d "$destino" ]; then
        echo "Eliminando directorio de instalación $destino..."
        rm -rf "$destino"
        ok "Directorio de instalación eliminado: $destino"
    else
        echo "Directorio de instalación no encontrado"
    fi

    ok "SquidStats ha sido desinstalado completamente del sistema"
}

main() {
    checkSudo
    detectDistro
    init_log "$@"

    # Procesar parámetros de modo no interactivo
    local action=""
    for arg in "$@"; do
        case "$arg" in
            --non-interactive|-y)
                NON_INTERACTIVE=true
                log_msg "INFO" "Modo no interactivo activado"
                echo "Modo no interactivo activado"
                ;;
            --update|--uninstall)
                action="$arg"
                ;;
        esac
    done

    log_msg "INFO" "Acción seleccionada: ${action:-instalación nueva}"

    if [ "$action" = "--update" ]; then
        log_msg "INFO" "=== INICIO ACTUALIZACIÓN ==="
        echo "Verificando paquetes instalados..."
        checkPackages
        echo "Actualizando Servicio..."
        updateOrCloneRepo
        
        # Find the installation directory
        local install_dir=$(findInstallDir)
        
        if [ -z "$install_dir" ]; then
            error "No se pudo determinar el directorio de instalación"
            return 1
        fi

        # Mover log al directorio de instalación
        init_log "$install_dir"
        
        echo "Verificando Dependecias de python..."
        installDependencies "$install_dir"
        echo "Compilando traducciones..."
        "$install_dir/venv/bin/pybabel" compile -d "$install_dir/translations" >> "$LOG_FILE" 2>&1 && \
            ok "Traducciones compiladas correctamente" || \
            log_msg "WARN" "No se pudieron compilar las traducciones"
        echo "Actualizando versión en .env..."
        updateEnvVersion "$install_dir"
        
        if [ "$install_dir" = "/opt/SquidStats" ] || [ "$install_dir" = "/usr/share/squidstats" ] || [ "$install_dir" = "/opt/squidstats" ]; then
            echo "Reiniciando Servicio..."
            restartService
        else
            log_msg "INFO" "Instalación de desarrollo detectada en $install_dir, no se reinicia el servicio"
            echo "Instalación de desarrollo detectada en $install_dir. No se reinicia el servicio del sistema."
            echo "Para ejecutar en modo desarrollo, use: python3 app.py"
        fi

        log_msg "OK" "=== ACTUALIZACIÓN COMPLETADA ==="
        ok "Actualizacion completada! Acceda en: \033[1;37mhttp://IP:5000\033[0m"
    elif [ "$action" = "--uninstall" ]; then
        log_msg "INFO" "=== INICIO DESINSTALACIÓN ==="
        uninstallSquidStats
        log_msg "OK" "=== DESINSTALACIÓN COMPLETADA ==="
    else
        log_msg "INFO" "=== INICIO INSTALACIÓN ==="
        echo "Instalando aplicación web..."
        checkPackages

        # Detectar si ya estamos en el directorio del repo (CI/desarrollo local)
        if [ "$NON_INTERACTIVE" = true ] && [ -f "app.py" ] && [ -f "requirements.txt" ]; then
            log_msg "INFO" "Modo CI/local detectado: usando repositorio actual en $(pwd)"
            echo "Modo CI/local detectado: usando repositorio actual en $(pwd)"
            install_dir="$(pwd)"
        else
            if ! updateOrCloneRepo; then
                error "Error al obtener el repositorio"
                exit 1
            fi
            install_dir=$(findInstallDir)
            if [ -z "$install_dir" ]; then
                install_dir="/opt/SquidStats"
            fi
        fi

        # Mover log al directorio de instalación
        init_log "$install_dir"

        checkSquidLog || true
        installDependencies "$install_dir"
        echo "Compilando traducciones..."
        "$install_dir/venv/bin/pybabel" compile -d "$install_dir/translations" >> "$LOG_FILE" 2>&1 && \
            ok "Traducciones compiladas correctamente" || \
            log_msg "WARN" "No se pudieron compilar las traducciones"
        createEnvFile "$install_dir"
        configureDatabase "$install_dir"
        createService "$install_dir"

        log_msg "OK" "=== INSTALACIÓN COMPLETADA ==="
        ok "Instalación completada! Acceda en: \033[1;37mhttp://IP:5000\033[0m"
    fi

    echo "Log del instalador guardado en: $LOG_FILE"
}

# Procesar argumentos
if [ $# -eq 0 ]; then
    main
else
    # Verificar si hay parámetros válidos
    valid_params=false
    for arg in "$@"; do
        case "$arg" in
            --update|--uninstall|--non-interactive|-y)
                valid_params=true
                ;;
            *)
                echo "Parámetro no reconocido: $arg"
                echo "Uso: $0 [--update|--uninstall] [--non-interactive|-y]"
                echo "  Sin parámetros: Instala SquidStats"
                echo "  --update: Actualiza SquidStats existente"
                echo "  --uninstall: Desinstala SquidStats completamente"
                echo "  --non-interactive, -y: Modo no interactivo (sin preguntas)"
                echo ""
                echo "Ejemplos:"
                echo "  $0                    # Instalación interactiva"
                echo "  $0 --non-interactive  # Instalación automática"
                echo "  $0 --update -y        # Actualización automática"
                echo "  $0 --uninstall -y     # Desinstalación automática"
                exit 1
                ;;
        esac
    done
    
    if [ "$valid_params" = true ]; then
        main "$@"
    fi
fi
