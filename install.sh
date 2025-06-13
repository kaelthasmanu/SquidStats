#! /bin/bash

function ok() {
    echo -e "\n\033[1;42m ✓ $1 \033[0m\n"
}

function error() {
    echo -e "\n\033[1;41m ✗ ERROR: $1 \033[0m\n"
}

function info() {
    echo -e "\n\033[1;46m ℹ INFO: $1 \033[0m\n"
}

function warning() {
    echo -e "\n\033[1;43m ⚠ ADVERTENCIA: $1 \033[0m\n"
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
    local paquetes=("git" "python3" "python3-pip" "python3-venv" "python3-pymysql" "libmariadb-dev" "curl")
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
        error "¡ADVERTENCIA!: No hemos encontrado el log en la ruta por defecto. Recargue su squid, navegue y genere logs para crearlo"
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

function moveDB() {
    local databaseSQlite="/opt/squidstats/logs.db"
    local env_file="/opt/squidstats/.env"
    local current_version=0

    if [ ! -f "$env_file" ]; then
        echo "Archivo .env no encontrado, será creado en el siguiente paso"
        return 0
    fi

    current_version=$(grep -E '^VERSION\s*=' "$env_file" | cut -d= -f2 | tr -dc '0-9' 2>/dev/null || echo 0)

    if ! grep -qE '^VERSION\s*=' "$env_file"; then
        echo "Agregando VERSION=2 al archivo .env..."
        echo "VERSION=2" >> "$env_file"
        echo "Eliminando base de datos antigua por actualización..."
        rm -rf "$databaseSQlite" 2>/dev/null
        ok "Base de datos antigua eliminada"
    else
        echo "Base de datos no requiere actualización de versión"
    fi

    if [ -f "$databaseSQlite" ] && [ "$current_version" -lt 2 ]; then
        echo "Eliminando base de datos antigua por actualización de versión..."
        rm -rf "$databaseSQlite"
        ok "Base de datos antigua eliminada"
    else
        echo "Base de datos está actualizada"
    fi

    return 0
}

function configureBlacklist() {
    local env_file="/opt/squidstats/.env"
    
    echo -e "\n\033[1;44m=== CONFIGURACIÓN DE BLACKLIST ===\033[0m"
    echo "¿Desea configurar la lista de dominios bloqueados? (recomendado)"
    echo "1) Usar configuración por defecto (facebook.com, twitter.com, instagram.com, etc.)"
    echo "2) Configurar dominios personalizados"
    echo "3) Omitir configuración de blacklist"
    
    while true; do
        read -p "Opción [1/2/3]: " choice
        case $choice in
            1|"")
                info "Usando configuración de blacklist por defecto"
                break
                ;;
            2)
                echo -e "\nIngrese los dominios a bloquear separados por comas:"
                echo "Ejemplo: facebook.com,twitter.com,youtube.com,netflix.com"
                read -p "Dominios: " custom_domains
                
                if [ -n "$custom_domains" ]; then
                    # Validar formato básico
                    if [[ "$custom_domains" =~ ^[a-zA-Z0-9.-]+(\.[a-zA-Z]{2,})(,[a-zA-Z0-9.-]+(\.[a-zA-Z]{2,}))*$ ]]; then
                        sed -i "s|^BLACKLIST_DOMAINS\s*=.*|BLACKLIST_DOMAINS=\"${custom_domains}\"|" "$env_file"
                        ok "Blacklist personalizada configurada: $custom_domains"
                    else
                        error "Formato inválido. Usando configuración por defecto."
                    fi
                else
                    info "No se ingresaron dominios. Usando configuración por defecto."
                fi
                break
                ;;
            3)
                info "Configuración de blacklist omitida"
                break
                ;;
            *)
                error "Opción inválida. Intente nuevamente."
                ;;
        esac
    done
}

function checkSystemResources() {
    local min_ram_mb=512
    local min_disk_mb=1024
    
    # Verificar RAM disponible
    local available_ram=$(free -m | awk 'NR==2{printf "%.0f", $7}')
    if [ "$available_ram" -lt "$min_ram_mb" ]; then
        warning "RAM disponible: ${available_ram}MB. Se recomiendan al menos ${min_ram_mb}MB"
    fi
    
    # Verificar espacio en disco
    local available_disk=$(df /opt 2>/dev/null | awk 'NR==2{gsub(/[^0-9]/,"",$4); print int($4/1024)}' || echo "1024")
    if [ "$available_disk" -lt "$min_disk_mb" ]; then
        warning "Espacio disponible en /opt: ${available_disk}MB. Se recomiendan al menos ${min_disk_mb}MB"
    fi
    
    # Verificar si Squid está ejecutándose
    if systemctl is-active --quiet squid 2>/dev/null || systemctl is-active --quiet squid3 2>/dev/null; then
        ok "Servicio Squid detectado y ejecutándose"
    else
        warning "Squid no parece estar ejecutándose. Asegúrese de tener Squid instalado y funcionando."
    fi
}

function updateEnvFile() {
    local env_file="/opt/squidstats/.env"
    local updated=false

    echo "Verificando y actualizando archivo .env..."

    # Actualizar DATABASE a DATABASE_STRING_CONNECTION si existe
    if grep -q "^DATABASE\s*=" "$env_file" && ! grep -q "^DATABASE_STRING_CONNECTION\s*=" "$env_file"; then
        echo "Actualizando variable DATABASE a DATABASE_STRING_CONNECTION..."
        sed -i 's/^DATABASE\(\s*=\s*\)\(.*\)/DATABASE_STRING_CONNECTION\1\2/' "$env_file"
        updated=true
    fi

    # Agregar BLACKLIST_DOMAINS si no existe
    if ! grep -q "^BLACKLIST_DOMAINS\s*=" "$env_file"; then
        echo "Agregando configuración BLACKLIST_DOMAINS..."
        echo "BLACKLIST_DOMAINS=\"facebook.com,twitter.com,instagram.com,tiktok.com,youtube.com,netflix.com\"" >> "$env_file"
        updated=true
    fi

    # Agregar VERSION si no existe
    if ! grep -q "^VERSION\s*=" "$env_file"; then
        echo "Agregando VERSION..."
        sed -i '1i\VERSION=2' "$env_file"
        updated=true
    fi

    # Agregar REFRESH_INTERVAL si no existe
    if ! grep -q "^REFRESH_INTERVAL\s*=" "$env_file"; then
        echo "Agregando REFRESH_INTERVAL..."
        echo "REFRESH_INTERVAL=60" >> "$env_file"
        updated=true
    fi

    if [ "$updated" = true ]; then
        ok "Archivo .env actualizado correctamente"
    else
        echo "Archivo .env ya está actualizado"
    fi

    return 0
}

function createEnvFile() {
    local env_file="/opt/squidstats/.env"

    if [ -f "$env_file" ]; then
        echo "El archivo .env ya existe en $env_file."
        updateEnvFile
        return 0
    else
        echo "Creando archivo de configuración .env..."
        cat > "$env_file" << EOF
VERSION=2
SQUID_HOST="127.0.0.1"
SQUID_PORT=3128
FLASK_DEBUG="True"
DATABASE_TYPE="SQLITE"
SQUID_LOG="/var/log/squid/access.log"
DATABASE_STRING_CONNECTION="/opt/squidstats/"
REFRESH_INTERVAL=60
BLACKLIST_DOMAINS="facebook.com,twitter.com,instagram.com,tiktok.com,youtube.com,netflix.com"
EOF
        ok "Archivo .env creado correctamente en $env_file"
        return 0
    fi
}

function createBackup() {
    local backup_dir="/opt/squidstats/backups"
    local timestamp=$(date +"%Y%m%d_%H%M%S")
    local env_file="/opt/squidstats/.env"
    
    if [ ! -f "$env_file" ]; then
        return 0
    fi
    
    echo "Creando backup de la configuración..."
    mkdir -p "$backup_dir"
    
    if cp "$env_file" "$backup_dir/.env_backup_$timestamp"; then
        info "Backup creado: $backup_dir/.env_backup_$timestamp"
        
        # Mantener solo los últimos 5 backups
        ls -t "$backup_dir"/.env_backup_* 2>/dev/null | tail -n +6 | xargs rm -f 2>/dev/null
    else
        warning "No se pudo crear el backup de configuración"
    fi
}

function validateEnvironment() {
    local env_file="/opt/squidstats/.env"
    local errors=0
    
    echo "Validando configuración del entorno..."
    
    if [ ! -f "$env_file" ]; then
        error "Archivo .env no encontrado"
        return 1
    fi
    
    # Validar variables requeridas
    local required_vars=("DATABASE_TYPE" "SQUID_LOG" "DATABASE_STRING_CONNECTION")
    
    for var in "${required_vars[@]}"; do
        if ! grep -q "^${var}\s*=" "$env_file"; then
            error "Variable requerida '$var' no encontrada en .env"
            errors=$((errors + 1))
        fi
    done
    
    # Validar archivo de log de Squid
    local squid_log=$(grep -E '^SQUID_LOG\s*=' "$env_file" | cut -d= -f2 | tr -d '"' | tr -d "'" | xargs)
    if [ -n "$squid_log" ] && [ ! -f "$squid_log" ]; then
        warning "Archivo de log de Squid no encontrado: $squid_log"
    fi
    
    if [ $errors -eq 0 ]; then
        ok "Validación del entorno completada exitosamente"
        return 0
    else
        return 1
    fi
}

function validateBlacklistConfig() {
    local env_file="/opt/squidstats/.env"
    
    if [ ! -f "$env_file" ]; then
        echo "Archivo .env no encontrado para validar blacklist"
        return 1
    fi

    local blacklist_domains=$(grep -E '^BLACKLIST_DOMAINS\s*=' "$env_file" | cut -d= -f2 | tr -d '"' | tr -d "'" 2>/dev/null)
    
    if [ -z "$blacklist_domains" ]; then
        echo "BLACKLIST_DOMAINS no configurado en .env"
        return 1
    fi

    local domain_count=$(echo "$blacklist_domains" | tr ',' '\n' | wc -l)
    info "Configuración de blacklist validada: $domain_count dominios configurados"
    echo "Dominios: $blacklist_domains"
    
    return 0
}

function createService() {
    local service_file="/etc/systemd/system/squidstats.service"

    if [ -f "$service_file" ]; then
        echo "El servicio ya existe en $service_file, no se realizan cambios."
        return 0
    fi

    echo "Creando servicio en $service_file..."
    cat > "$service_file" << EOF
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
    ok "Servicio creado y iniciado correctamente"
}

function configureDatabase() {
    local env_file="/opt/squidstats/.env"

    echo -e "\n\033[1;44mCONFIGURACIÓN DE BASE DE DATOS\033[0m"
    echo "Seleccione el tipo de base de datos:"
    echo "1) SQLite (por defecto)"
    echo "2) MariaDB (necesitas tener mariadb ejecutándose)"
    
    while true; do
        read -p "Opción [1/2]: " choice
        case $choice in
            1|"") break;;  
            2) break;;
            *) error "Opción inválida. Intente nuevamente.";;
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

                if [[ $? -eq 0 ]]; then
                    escaped_str=$(sed 's/[\/&|]/\\&/g' <<< "$validation_result")
                    sed -i "s|^DATABASE_STRING_CONNECTION\s*=.*|DATABASE_STRING_CONNECTION = \"${escaped_str}\"|" "$env_file"
                    sed -i "s|^DATABASE_TYPE\s*=.*|DATABASE_TYPE = MARIADB|" "$env_file"
                    ok "Configuración MariaDB actualizada!\nCadena codificada: $validation_result"
                    break
                else
                    error "Error en la cadena:\n${validation_result#ERROR: }"
                fi
            done
            ;;
        *)
            sqlite_path="/opt/squidstats/"
            sed -i "s|^DATABASE_STRING_CONNECTION\s*=.*|DATABASE_STRING_CONNECTION = \"${sqlite_path}\"|" "$env_file"
            sed -i "s|^DATABASE_TYPE\s*=.*|DATABASE_TYPE = SQLITE|" "$env_file"
            ok "Configuración SQLite establecida!"
            ;;
    esac
}

function patchSquidConf() {
    local squid_conf=""
    # Busca squid.conf en rutas típicas
    if [ -f "/etc/squid/squid.conf" ]; then
        squid_conf="/etc/squid/squid.conf"
    elif [ -f "/etc/squid3/squid.conf" ]; then
        squid_conf="/etc/squid3/squid.conf"
    else
        error "Debe tener instalado un servidor proxy Squid. No se encontró squid.conf en /etc/squid/ ni /etc/squid3/"
        return 1
    fi

    # Backup antes de modificar
    cp "$squid_conf" "${squid_conf}.back"
    ok "Backup realizado: ${squid_conf}.back"

    local logformat_line='logformat detailed \'
    logformat_line+='
  "%ts.%03tu %>a %ui %un [%tl] \"%rm %ru HTTP/%rv\" %>Hs %<st %rm %ru %>a %mt %<a %<rm %Ss/%Sh %<st'
    local access_detailed='access_log /var/log/squid/access.log detailed'
    local access_default='access_log /var/log/squid/defaultaccess.log'

    # Busca si existe una línea access_log /var/log/squid/access.log (sin detailed)
    if grep -q '^access_log[[:space:]]\+/var/log/squid/access\.log[[:space:]]*$' "$squid_conf"; then
        # Si no existe logformat detailed, lo agrega encima de la línea access_log
        if ! grep -q '^logformat detailed' "$squid_conf"; then
            awk -v l1="$logformat_line" '
                BEGIN{inserted=0}
                /^access_log[[:space:]]+\/var\/log\/squid\/access\.log[[:space:]]*$/ && !inserted {
                    print l1
                    inserted=1
                }
                {print}
            ' "$squid_conf" > "${squid_conf}.tmp" && mv "${squid_conf}.tmp" "$squid_conf"
            ok "Se agregó logformat detailed encima de access_log /var/log/squid/access.log"
        else
            echo "logformat detailed ya existe, no se agrega de nuevo."
        fi
        # Modifica la línea access_log para agregar detailed al final y agrega defaultaccess.log debajo
        awk -v l2="$access_default" '
            {
                if ($0 ~ /^access_log[[:space:]]+\/var\/log\/squid\/access\.log[[:space:]]*$/) {
                    print $0 " detailed"
                    print l2
                } else {
                    print
                }
            }
        ' "$squid_conf" > "${squid_conf}.tmp" && mv "${squid_conf}.tmp" "$squid_conf"
        ok "Se modificó access_log /var/log/squid/access.log para usar detailed y se agregó access_log defaultaccess.log debajo."
    else
        # No existe access_log /var/log/squid/access.log, agrega todo al final
        {
            echo "$logformat_line"
            echo "$access_detailed"
            echo "$access_default"
        } >> "$squid_conf"
        ok "Se agregaron logformat detailed, access_log /var/log/squid/access.log detailed y access_log /var/log/squid/defaultaccess.log al final de $squid_conf"
    fi
}

function main() {
    checkSudo

    if [ "$1" = "--update" ]; then
        echo -e "\n\033[1;44m=== ACTUALIZANDO SQUIDSTATS ===\033[0m"
        
        # Crear backup antes de actualizar
        createBackup
        
        updateOrCloneRepo
        
        # Actualizar archivo .env con nuevas variables
        updateEnvFile
        
        # Validar entorno y configuración
        validateEnvironment
        validateBlacklistConfig
        
        echo "Reiniciando servicio SquidStats..."
        systemctl restart squidstats.service
        
        if systemctl is-active --quiet squidstats.service; then
            ok "Actualización completada exitosamente!"
            echo -e "Acceda en: \033[1;37mhttp://$(hostname -I | awk '{print $1}'):5000\033[0m"
        else
            error "El servicio no se pudo iniciar correctamente. Verifique los logs con: journalctl -u squidstats.service"
        fi
    else
        echo -e "\n\033[1;44m=== INSTALANDO SQUIDSTATS ===\033[0m"
        
        echo "Verificando recursos del sistema..."
        checkSystemResources
        
        echo "Verificando paquetes del sistema..."
        checkPackages
        
        echo "Descargando/actualizando código fuente..."
        updateOrCloneRepo
        
        echo "Configurando Squid..."
        patchSquidConf
        
        echo "Verificando logs de Squid..."
        checkSquidLog
        
        echo "Configurando entorno Python..."
        setupVenv
        installDependencies
        
        echo "Configurando archivos de configuración..."
        createEnvFile
        configureDatabase
        
        # Configuración interactiva de blacklist
        configureBlacklist
        
        moveDB
        
        echo "Configurando servicio del sistema..."
        createService
        
        # Validar configuración final
        echo "Validando configuración..."
        validateEnvironment
        validateBlacklistConfig
        
        if systemctl is-active --quiet squidstats.service; then
            ok "¡Instalación completada exitosamente!"
            echo -e "\n\033[1;42m=== INFORMACIÓN IMPORTANTE ===\033[0m"
            echo -e "• Acceso web: \033[1;37mhttp://$(hostname -I | awk '{print $1}'):5000\033[0m"
            echo -e "• Archivo de configuración: \033[1;37m/opt/squidstats/.env\033[0m"
            echo -e "• Logs del servicio: \033[1;37mjournalctl -u squidstats.service\033[0m"
            echo -e "• Estado del servicio: \033[1;37msystemctl status squidstats.service\033[0m"
            echo -e "\n\033[1;43m=== CONFIGURACIÓN DE BLACKLIST ===\033[0m"
            echo -e "• Formato: BLACKLIST_DOMAINS=\"dominio1.com,dominio2.com,dominio3.com\""
            echo -e "• Reinicie el servicio después de cambios: \033[1;37msudo systemctl restart squidstats.service\033[0m"
            echo -e "• Acceda a la sección '/blacklist' en la interfaz web para ver la lista"
            echo -e "• Para reconfigurar solo la blacklist: \033[1;37msudo $0 --configure-blacklist o edite el fichero .env\033[0m\n"
        else
            error "La instalación completó pero el servicio no se pudo iniciar. Verifique los logs con: journalctl -u squidstats.service"
        fi
    fi
}

function showHelp() {
    echo -e "\n\033[1;44m=== SQUIDSTATS INSTALLER ===\033[0m"
    echo -e "Script de instalación y configuración de SquidStats"
    echo -e "\n\033[1;37mUSO:\033[0m"
    echo -e "  $0 [OPCIÓN]"
    echo -e "\n\033[1;37mOPCIONES:\033[0m"
    echo -e "  \033[1;32m(sin parámetros)\033[0m     Instalación completa de SquidStats"
    echo -e "  \033[1;32m--update\033[0m            Actualizar SquidStats a la última versión"
    echo -e "  \033[1;32m--configure-blacklist\033[0m Reconfigurar solo la lista de dominios bloqueados"
    echo -e "  \033[1;32m--help\033[0m              Mostrar esta ayuda"
    echo -e "\n\033[1;37mEJEMPLOS:\033[0m"
    echo -e "  sudo $0                    # Instalación completa"
    echo -e "  sudo $0 --update           # Actualizar versión"
    echo -e "  sudo $0 --configure-blacklist  # Solo reconfigurar blacklist"
    echo -e "\n\033[1;37mREQUISITOS:\033[0m"
    echo -e "  • Sistema operativo: Ubuntu 20.04+ o Debian 12+"
    echo -e "  • Privilegios de superusuario (ejecutar con sudo)"
    echo -e "  • Squid Proxy instalado y funcionando"
    echo -e "  • Conexión a internet para descargar dependencias"
    echo -e "\n\033[1;37mARCHIVOS Y DIRECTORIOS:\033[0m"
    echo -e "  • Instalación: /opt/squidstats/"
    echo -e "  • Configuración: /opt/squidstats/.env"
    echo -e "  • Servicio: /etc/systemd/system/squidstats.service"
    echo -e "  • Interfaz web: http://IP:5000"
    echo ""
}

function configureBlacklistOnly() {
    local env_file="/opt/squidstats/.env"
    
    if [ ! -f "$env_file" ]; then
        error "SquidStats no está instalado. Ejecute primero: sudo $0"
        exit 1
    fi
    
    echo -e "\n\033[1;44m=== RECONFIGURACIÓN DE BLACKLIST ===\033[0m"
    
    # Mostrar configuración actual
    local current_blacklist=$(grep -E '^BLACKLIST_DOMAINS\s*=' "$env_file" | cut -d= -f2 | tr -d '"' | tr -d "'" 2>/dev/null)
    if [ -n "$current_blacklist" ]; then
        echo -e "\n\033[1;37mConfiguración actual:\033[0m"
        echo "$current_blacklist" | tr ',' '\n' | sed 's/^/  • /'
    fi
    
    configureBlacklist
    
    # Reiniciar servicio
    echo "Reiniciando servicio SquidStats..."
    if systemctl restart squidstats.service; then
        ok "Blacklist reconfigurada correctamente"
        validateBlacklistConfig
        echo -e "Acceda a la interfaz web: \033[1;37mhttp://$(hostname -I | awk '{print $1}'):5000/blacklist\033[0m"
    else
        error "Error al reiniciar el servicio. Verifique con: journalctl -u squidstats.service"
    fi
}

case "$1" in
    "--update")
        main "$1"
        ;;
    "--configure-blacklist")
        checkSudo
        configureBlacklistOnly
        ;;
    "--help"|"-h")
        showHelp
        ;;
    "")
        main
        ;;
    *)
        error "Parámetro no reconocido: $1"
        echo "Use '$0 --help' para ver las opciones disponibles"
        exit 1
        ;;
esac
