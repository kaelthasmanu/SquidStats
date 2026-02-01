#! /bin/bash

function error() {
    echo -e "\n\033[1;41m$1\033[0m\n"
}

function ok() {
    echo -e "\n\033[1;42m$1\033[0m\n"
}

function checkSudo() {
    if [ "$EUID" -ne 0 ]; then
        error "ERROR: Este script debe ejecutarse con privilegios de superusuario.\nPor favor, ejecútelo con el usuario: root $0"
        exit 1
    fi
}

function installDependencies() {
    local install_dir="${1:-/opt/SquidStats}"
    local venv_dir="$install_dir/venv"

    if [ ! -d "$venv_dir" ]; then
        echo "El entorno virtual no existe en $venv_dir, creándolo..."
        python3 -m venv "$venv_dir"
        
        if [ $? -ne 0 ]; then
            error "Error al crear el entorno virtual en $venv_dir"
            return 1
        fi
        
        ok "Entorno virtual creado correctamente en $venv_dir"
    fi

    echo "Activando entorno virtual y instalando dependencias..."
    source "$venv_dir/bin/activate"

    pip install --upgrade pip
    pip install -r "$install_dir/requirements.txt"

    if [ $? -ne 0 ]; then
        error "Error al instalar dependencias"
        deactivate
        return 1
    fi

    ok "Dependencias instaladas correctamente en el entorno virtual"
    deactivate
    return 0
}
#  python3-pymysql delete from packages
function checkPackages() {
    local packages=("git" "python3" "python3-pip" "python3-venv" "libmariadb-dev" "curl" "build-essential" "libssl-dev" "python3-dev" "libpq-dev") # C-ICAP Implementation not using for now libicapapi-dev
    local missing=()

    for pkg in "${packages[@]}"; do
        if ! dpkg -l | grep -q "^ii  $pkg "; then
            missing+=("$pkg")
        fi
    done

    if [ ${#missing[@]} -ne 0 ]; then
        echo "Instalando paquetes faltantes: ${missing[*]}"
        apt-get update

        if ! apt-get install -y "${missing[@]}"; then
            error "ERROR: Compruebe la versión de su OS se recomienda Ubuntu20.04+ o Debian12+"
            exit 1
        fi

        ok "Paquetes instalados correctamente"
    else
        echo "Todos los paquetes necesarios ya están instalados"
    fi
}

function checkSquidLog() {
    local log_file="/var/log/squid/access.log"

    if [ ! -f "$log_file" ]; then
        error "¡ADVERTENCIA!: No hemos encontrado el log en la ruta por defecto. Recargue su squid, navegue y genere logs para crearlo"
        return 1
    else
        echo "Archivo de log de Squid encontrado: $log_file"
        return 0
    fi
}

function findInstallDir() {
    local destinos=("/opt/SquidStats" "/usr/share/squidstats" "/home/manuel/Desktop/Projects/SquidStats")

    # Agregar el directorio actual si contiene archivos de SquidStats
    if [ -f "app.py" ] && [ -f "requirements.txt" ] && [ -d ".git" ]; then
        destinos+=("$(pwd)")
    fi

    for dir in "${destinos[@]}"; do
        if [ -d "$dir" ]; then
            echo "$dir"
            return 0
        fi
    done

    return 1
}

function updateOrCloneRepo() {
    local repo_url="https://github.com/kaelthasmanu/SquidStats.git"
    local branch="main"
    local env_exists=false
    local found_dir=""

    found_dir=$(findInstallDir)

    if [ -z "$found_dir" ]; then
        echo "No se encontró instalación existente, clonando repositorio en /opt/SquidStats..."
        if git clone "$repo_url" /opt/SquidStats && cd /opt/SquidStats && git checkout "$branch"; then
            echo "✅ Repositorio clonado exitosamente en /opt/SquidStats"
            return 0
        else
            echo "❌ Error al clonar el repositorio."
            return 1
        fi
    fi

    if [ "$found_dir" = "/usr/share/squidstats" ]; then
        echo "ℹ️ Instalación detectada en /usr/share/squidstats. Esta versión fue instalada desde un .deb y no puede actualizarse con git."
        echo "Por favor, use el gestor de paquetes (apt/dpkg) para actualizar."
        return 1
    fi

    echo "El directorio $found_dir ya existe, intentando actualizar con git pull..."
    cd "$found_dir"

    if [ -d ".git" ]; then
        if [ -f ".env" ]; then
            env_exists=true
            echo ".env existente detectado, se preservará"
            cp .env /tmp/.env.backup
        fi

        if git fetch origin "$branch" && git checkout "$branch" && git pull origin "$branch"; then
            [ "$env_exists" = true ] && mv /tmp/.env.backup .env
            echo "✅ Repositorio actualizado exitosamente en la rama '$branch'"
            return 0
        else
            echo "❌ Error al actualizar el repositorio."
            return 1
        fi
    else
        echo "⚠️ El directorio $found_dir existe pero no es un repositorio git. No se puede actualizar automáticamente."
        return 1
    fi
}

function updateEnvVersion() {
    local install_dir="${1:-/opt/SquidStats}"
    local CURRENT_VERSION="2.2"  # Variable de versión actual del script
    local env_file="$install_dir/.env"
    
    if [ ! -f "$env_file" ]; then
        echo "⚠️ Archivo .env no encontrado en $env_file"
        return 1
    fi
    
    # Leer la versión actual del .env
    local env_version=$(grep "^VERSION=" "$env_file" | cut -d'=' -f2)
    
    # Comparar versiones
    if [ "$env_version" != "$CURRENT_VERSION" ]; then
        echo "Actualizando VERSION de $env_version a $CURRENT_VERSION en .env..."
        
        # Verificar si existe la línea VERSION en .env
        if grep -q "^VERSION=" "$env_file"; then
            # Actualizar VERSION existente
            sed -i "s/^VERSION=.*/VERSION=$CURRENT_VERSION/" "$env_file"
            echo "✅ VERSION actualizada a $CURRENT_VERSION en .env"
        else
            # Agregar VERSION al inicio del archivo si no existe
            sed -i "1iVERSION=$CURRENT_VERSION" "$env_file"
            echo "✅ VERSION agregada: $CURRENT_VERSION en .env"
        fi
    else
        echo "✓ VERSION ya está actualizada ($CURRENT_VERSION)"
    fi
    
    return 0
}

function createEnvFile() {
    local install_dir="${1:-/opt/SquidStats}"
    local env_file="$install_dir/.env"

    if [ -f "$env_file" ]; then
        echo "El archivo .env ya existe en $env_file."
        return 0
    else
        echo "Creando archivo de configuración .env..."
        cat >"$env_file" <<EOF
VERSION=2.2
SECRET_KEY="your-secret-key-here-generate-with-python-secrets"
SQUID_HOST=127.0.0.1
SQUID_PORT=3128
LOG_FORMAT=DETAILED
FLASK_DEBUG=True
DATABASE_TYPE=SQLITE
SQUID_LOG=/var/log/squid/access.log
SQUID_CACHE_LOG=/var/log/squid/cache.log
DATABASE_STRING_CONNECTION=$install_dir/squidstats.db
REFRESH_INTERVAL=60
BLACKLIST_DOMAINS="facebook.com,twitter.com,instagram.com,tiktok.com,youtube.com,netflix.com"
HTTP_PROXY=""
HTTPS_PROXY=
NO_PROXY=
SQUID_CONFIG_PATH=/etc/squid/squid.conf
ACL_FILES_DIR=/etc/squid/config/acls
LISTEN_HOST=127.0.0.1
LISTEN_PORT=5000
FIRST_PASSWORD="admin"
JWT_EXPIRY_HOURS=24
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_DURATION_MINUTES=15
TELEGRAM_ENABLED=false
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_BOT_TOKEN=
TELEGRAM_PHONE=
TELEGRAM_SESSION_NAME=squidstats_bot
TELEGRAM_RECIPIENTS=
EOF
        ok "Archivo .env creado correctamente en $env_file"
        return 0
    fi
}

function createService() {
    local install_dir="${1:-/opt/SquidStats}"
    local service_file="/etc/systemd/system/squidstats.service"

    if [ -f "$service_file" ]; then
        echo "El servicio ya existe en $service_file, no se realizan cambios."
        return 0
    fi

    echo "Creando servicio en $service_file..."
    cat >"$service_file" <<EOF
[Unit]
Description=SquidStats Web Application
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$install_dir
ExecStart=$install_dir/venv/bin/python3 $install_dir/app.py
Restart=always
RestartSec=5
EnvironmentFile=$install_dir/.env
Environment=PATH=$install_dir/venv/bin:$PATH

# Resource limits
MemoryLimit=2048M
TimeoutStartSec=30
TimeoutStopSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=squidstats

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable squidstats.service
    systemctl start squidstats.service
    ok "Servicio creado y iniciado correctamente"
}

function configureDatabase() {
    local install_dir="${1:-/opt/SquidStats}"
    local env_file="$install_dir/.env"

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

    case $choice in
    2)
        while true; do
            read -p "Ingrese cadena de conexión (mysql+pymysql://user:clave@host:port/db): " conn_str

            if [[ "$conn_str" != mysql+pymysql://* ]]; then
                error "Formato inválido. Debe comenzar con: mysql+pymysql://"
                continue
            fi

            validation_result=$(python3 $install_dir/utils/validateString.py "$conn_str" 2>&1)
            exit_code=$?

            if [[ $exit_code -eq 0 ]]; then
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

function uninstallSquidStats() {
    local destino="/opt/SquidStats"
    local service_file="/etc/systemd/system/squidstats.service"

    echo -e "\n\033[1;43mDESINSTALACIÓN DE SQUIDSTATS\033[0m"
    echo "Esta operación eliminará completamente SquidStats del sistema."
    echo "¿Está seguro de que desea continuar? (s/N)"

    read -p "Respuesta: " confirm

    if [[ ! "$confirm" =~ ^[sS]$ ]]; then
        echo "Desinstalación cancelada."
        return 0
    fi

    echo "Iniciando desinstalación..."

    if [ -f "$service_file" ]; then
        echo "Deteniendo servicio squidstats..."
        systemctl stop squidstats.service 2>/dev/null || true

        echo "Deshabilitando servicio squidstats..."
        systemctl disable squidstats.service 2>/dev/null || true

        echo "Eliminando archivo de servicio..."
        rm -f "$service_file"

        systemctl daemon-reload
        ok "Servicio squidstats eliminado"
    else
        echo "Servicio squidstats no encontrado"
    fi
    
    if [ -d "$destino" ]; then
        echo "Eliminando directorio de instalación $destino..."
        rm -rf "$destino"
        ok "Directorio de instalación eliminado"
    else
        echo "Directorio de instalación no encontrado"
    fi

    ok "SquidStats ha sido desinstalado completamente del sistema"
}

function main() {
    checkSudo

    if [ "$1" = "--update" ]; then
        echo "Verificando paquetes instalados..."
        checkPackages
        echo "Actualizando Servicio..."
        if ! updateOrCloneRepo; then
            return 1
        fi
        
        # Find the installation directory
        local install_dir=$(findInstallDir)
        
        if [ -z "$install_dir" ]; then
            error "No se pudo determinar el directorio de instalación"
            return 1
        fi
        
        echo "Verificando Dependecias de python..."
        installDependencies "$install_dir"
        echo "Actualizando versión en .env..."
        updateEnvVersion "$install_dir"
        
        if [ "$install_dir" = "/opt/SquidStats" ] || [ "$install_dir" = "/usr/share/squidstats" ]; then
            echo "Reiniciando Servicio..."
            systemctl restart squidstats.service
        else
            echo "Instalación de desarrollo detectada en $install_dir. No se reinicia el servicio del sistema."
            echo "Para ejecutar en modo desarrollo, use: python3 app.py"
        fi

        ok "Actualizacion completada! Acceda en: \033[1;37mhttp://IP:5000\033[0m"
    elif [ "$1" = "--uninstall" ]; then
        uninstallSquidStats
    else
        echo "Instalando aplicación web..."
        checkPackages
        updateOrCloneRepo
        checkSquidLog
        installDependencies "/opt/SquidStats"
        createEnvFile "/opt/SquidStats"
        configureDatabase "/opt/SquidStats"
        createService "/opt/SquidStats"

        ok "Instalación completada! Acceda en: \033[1;37mhttp://IP:5000\033[0m"
    fi
}

case "$1" in
"--update")
    main "$1"
    ;;
"--uninstall")
    main "$1"
    ;;
"")
    main
    ;;
*)
    echo "Parámetro no reconocido: $1"
    echo "Uso: $0 [--update|--uninstall]"
    echo "  Sin parámetros: Instala SquidStats"
    echo "  --update: Actualiza SquidStats existente"
    echo "  --uninstall: Desinstala SquidStats completamente"
    exit 1
    ;;
esac
