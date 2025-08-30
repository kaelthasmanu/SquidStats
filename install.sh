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
    local venv_dir="/opt/SquidStats/venv"

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
    pip install -r /opt/SquidStats/requirements.txt

    if [ $? -ne 0 ]; then
        error "Error al instalar dependencias"
        deactivate
        return 1
    fi

    ok "Dependencias instaladas correctamente en el entorno virtual"
    deactivate
    return 0
}
#  pthon3-pymysql delete from packages
function checkPackages() {
    local packages=("git" "python3" "python3-pip" "python3-venv" "libmariadb-dev" "curl" "build-essential" "libssl-dev" "libicapapi-dev" "python3-dev" "libpq-dev")
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

function updateOrCloneRepo() {
    local repo_url="https://github.com/kaelthasmanu/SquidStats.git"
    local destino="/opt/SquidStats"
    local branch="main"
    local env_exists=false
    local db_exists=false

    if [ -d "$destino" ]; then
        echo "El directorio $destino ya existe, intentando actualizar con git pull..."
        cd "$destino"

        if [ -d ".git" ]; then
            if [ -f ".env" ]; then
                env_exists=true
                echo ".env existente detectado, se preservará"
                cp .env /tmp/.env.backup
            fi

            local db_files=(*.db)
            if [ -e "${db_files[0]}" ]; then
                db_exists=true
                echo "Archivos .db detectados, se preservarán"
                mkdir -p /tmp/db_backup
                cp *.db /tmp/db_backup/
            fi

            if git fetch origin "$branch" && git checkout "$branch" && git pull origin "$branch"; then
                [ "$env_exists" = true ] && mv /tmp/.env.backup .env
                
                if [ "$db_exists" = true ]; then
                    mv /tmp/db_backup/*.db . 2>/dev/null || true
                    rm -rf /tmp/db_backup
                    echo "📊 Archivos .db restaurados"
                fi
                
                echo "✅ Repositorio actualizado exitosamente en la rama '$branch'"
                return 0
            else
                echo "❌ Error al actualizar el repositorio, se procederá a clonar de nuevo"
                cd ..
                rm -rf "$destino"
            fi
        else
            echo "⚠️ El directorio existe pero no es un repositorio git, se procederá a clonar de nuevo"
            rm -rf "$destino"
        fi
    fi

    echo "🔄 Clonando repositorio por primera vez desde la rama '$branch'..."
    if git clone --branch "$branch" "$repo_url" "$destino"; then
        chown -R $USER:$USER "$destino"
        echo "✅ Repositorio clonado exitosamente en $destino"

        if [ "$env_exists" = true ] && [ -f /tmp/.env.backup ]; then
            mv /tmp/.env.backup "$destino/.env"
            echo "⚙️ Archivo .env restaurado"
        fi

        if [ "$db_exists" = true ] && [ -d /tmp/db_backup ]; then
            mv /tmp/db_backup/*.db "$destino/" 2>/dev/null || true
            rm -rf /tmp/db_backup
            echo "📊 Archivos .db restaurados"
        fi

        return 0
    else
        echo "❌ Error al clonar el repositorio"
        return 1
    fi
}

function moveDB() {
    local databaseSQlite="/opt/SquidStats/squidstats.db"
    local env_file="/opt/SquidStats/.env"
    local current_version=0

    current_version=$(grep -E '^VERSION\s*=' "$env_file" | cut -d= -f2 | tr -dc '0-9' || echo 0)

    if ! grep -qE '^VERSION\s*=' "$env_file"; then
        echo "VERSION=2" >>"$env_file"
        echo "Eliminando base de datos antigua por actualización..."
        rm -rf "$databaseSQlite"
        ok "Base de datos antigua eliminada"
    else
        echo "Base de datos no requiere actualización"
    fi

    if [ -f "$databaseSQlite" ] && [ "$current_version" -lt 2 ]; then
        echo "Eliminando base de datos antigua por actualización..."
        rm -rf "$databaseSQlite"
        ok "Base de datos antigua eliminada"
    else
        echo "Base de datos no requiere actualización"
    fi

    return 0
}

function createEnvFile() {
    local env_file="/opt/SquidStats/.env"

    if [ -f "$env_file" ]; then
        echo "El archivo .env ya existe en $env_file."
        return 0
    else
        echo "Creando archivo de configuración .env..."
        cat >"$env_file" <<EOF
VERSION=2
SQUID_HOST=127.0.0.1
SQUID_PORT=3128
LOG_FORMAT=DETAILED
FLASK_DEBUG=True
DATABASE_TYPE=SQLITE
SQUID_LOG=/var/log/squid/access.log
DATABASE_STRING_CONNECTION=/opt/SquidStats/squidstats.db
REFRESH_INTERVAL=60
BLACKLIST_DOMAINS="facebook.com,twitter.com,instagram.com,tiktok.com,youtube.com,netflix.com"
HTTP_PROXY=""
SQUID_CONFIG_PATH=/etc/squid/squid.conf
ACL_FILES_DIR=/etc/squid/config/acls
EOF
        ok "Archivo .env creado correctamente en $env_file"
        return 0
    fi
}

function createService() {
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
WorkingDirectory=/opt/SquidStats
ExecStart=/opt/SquidStats/venv/bin/python3 /opt/SquidStats/app.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/SquidStats/.env
Environment=PATH=/opt/SquidStats/venv/bin:$PATH

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
    local env_file="/opt/SquidStats/.env"

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

            validation_result=$(python3 /opt/SquidStats/utils/validateString.py "$conn_str" 2>&1)
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
        sqlite_path="/opt/SquidStats/squidstats.db"
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
        echo "Verificando Dependecias de python..."
        installDependencies
        echo "Actualizando Servicio..."
        updateOrCloneRepo
        echo "Reiniciando Servicio..."
        systemctl restart squidstats.service

        ok "Actualizacion completada! Acceda en: \033[1;37mhttp://IP:5000\033[0m"
    elif [ "$1" = "--uninstall" ]; then
        uninstallSquidStats
    else
        echo "Instalando aplicación web..."
        checkPackages
        updateOrCloneRepo
        checkSquidLog
        installDependencies
        createEnvFile
        configureDatabase
        moveDB
        createService

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
