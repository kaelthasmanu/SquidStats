#! /bin/bash

function error() {
    echo -e "\n\033[1;41m$1\033[0m\n"
}

function ok() {
    echo -e "\n\033[1;42m$1\033[0m\n"
}

function checkSudo() {
    if [ "$EUID" -ne 0 ]; then
        error "ERROR: Este script debe ejecutarse con privilegios de superusuario.\nPor favor, ejecútelo con: sudo $0"
        exit 1
    fi
}

function checkPackages() {
    local paquetes=("git" "python3" "python3-pip")
    local faltantes=()

    for pkg in "${paquetes[@]}"; do
        if ! dpkg -l | grep -q "^ii  $pkg "; then
            faltantes+=("$pkg")
        fi
    done

    if [ ${#faltantes[@]} -ne 0 ]; then
        echo "Instalando paquetes faltantes: ${faltantes[*]}"
        apt-get update

        if ! apt-get install -y "${faltantes[@]}"; then
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
        error "¡ADVERTENCIA!: ¿Tiene Squid realmente instalado? No hemos encontrado el log en la ruta por defecto"
        return 1
    else
        echo "Archivo de log de Squid encontrado: $log_file"
        return 0
    fi
}

function clonRepo() {
    local repo_url="https://github.com/kaelthasmanu/SquidStats.git"
    local destino="/opt/squidstats"

    echo "Preparando para clonar repositorio $repo_url en $destino..."

    mkdir -p "$(dirname "$destino")"

    if [ -d "$destino" ]; then
        echo "Eliminando directorio existente $destino..."
        rm -rf "$destino"
    fi

    echo "Clonando repositorio..."

    if git clone "$repo_url" "$destino"; then
        chown -R $USER:$USER "$destino"
        ok "Repositorio clonado exitosamente en $destino"
    else
        mostrar_error "Error al clonar el repositorio"
        return 1
    fi
}

function installDependencies() {
    cd /opt/squidstats

    echo "Instalando Dependencias..."
    pip3 install -r requirements.txt --break-system-packages

}

function createEnvFile() {
    local env_file="/opt/squidstats/.env"

    echo "Creando archivo de configuración .env..."

    cat > "$env_file" << EOF
SQUID_HOST = "127.0.0.1"
SQUID_PORT = 3128
FLASK_DEBUG = "True"
SQUID_LOG = "/var/log/squid/access.log"
DATABASE = "/opt/squidstats/logs.db"
REFRESH_INTERVAL = 60
EOF

    ok "Archivo .env creado correctamente en $env_file"
}

function executeApp() {
    ok "Proceso completado... Visite la URL http://IP:5000 para ver la app \n Para salir presione ctrl+c"
    python3 /opt/squidstats/app.py
}

function main() {

    checkSudo

    checkPackages

    checkSquidLog

    clonRepo

    installDependencies

    createEnvFile

    executeApp
}

main