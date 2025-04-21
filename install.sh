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

function setupVenv() {
    local venv_dir="/opt/squidstats/venv"

    if [ -d "$venv_dir" ]; then
        echo "Entorno virtual ya existe en $venv_dir"
        return 0
    fi

    echo "Creando entorno virtual Python en $venv_dir"
    python3 -m venv "$venv_dir"

    if [ $? -ne 0 ]; then
        error "Error al crear el entorno virtual"
        return 1
    fi

    ok "Entorno virtual creado correctamente"
    return 0
}

function installDependencies() {
    local venv_dir="/opt/squidstats/venv"

    if [ ! -d "$venv_dir" ]; then
        error "El entorno virtual no existe en $venv_dir"
        return 1
    fi

    echo "Activando entorno virtual y instalando dependencias..."
    source "$venv_dir/bin/activate"

    pip install --upgrade pip
    pip install -r /opt/squidstats/requirements.txt

    if [ $? -ne 0 ]; then
        error "Error al instalar dependencias"
        deactivate
        return 1
    fi

    ok "Dependencias instaladas correctamente en el entorno virtual"
    deactivate
    return 0
}

function checkPackages() {
    local paquetes=("git" "python3" "python3-pip" "python3-venv")
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

function updateOrCloneRepo() {
    local repo_url="https://github.com/kaelthasmanu/SquidStats.git"
    local destino="/opt/squidstats"
    local env_exists=false


    if [ -d "$destino" ]; then
        echo "El directorio $destino ya existe, intentando actualizar con git pull..."
        cd "$destino"

        if [ -d ".git" ]; then
            if [ -f ".env" ]; then
                env_exists=true
                echo ".env existente detectado, se preservará"
            fi

            if git pull; then
                ok "Repositorio actualizado exitosamente"
                return 0
            else
                error "Error al actualizar el repositorio, se procederá a clonar de nuevo"
                cd ..
                rm -rf "$destino"
            fi
        else
            error "El directorio existe pero no es un repositorio git, se procederá a clonar de nuevo"
            rm -rf "$destino"
        fi
    fi

    echo "Clonando repositorio por primera vez..."
    if git clone "$repo_url" "$destino"; then
        chown -R $USER:$USER "$destino"
        ok "Repositorio clonado exitosamente en $destino"
        return 0
    else
        error "Error al clonar el repositorio"
        return 1
    fi
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

function createService() {
  touch /etc/systemd/system/squidstats.service

   cat > /etc/systemd/system/squidstats.service << EOF
[Unit]
Description=SquidStats
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/squidstats
ExecStart=/opt/squidstats/venv/bin/python /opt/squidstats/app.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/squidstats/.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable squidstats.service
systemctl start squidstats.service

}

function executeApp() {
    createService
    ok "Proceso completado... Visite la URL http://IP:5000 para ver la app \n Para salir presione ctrl+c"
}

function main() {

    checkSudo

    checkPackages

    checkSquidLog

    clonRepo

    setupVenv

    installDependencies

    createEnvFile

    executeApp
}

main
