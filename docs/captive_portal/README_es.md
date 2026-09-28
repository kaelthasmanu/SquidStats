# Guía de despliegue del portal cautivo de SquidStats

Esta guía explica cómo desplegar el portal cautivo de SquidStats con ACL de Squid, el helper de ACL externa, autenticación LDAP/Active Directory, redirecciones del firewall y una topología de red segura.

La funcionalidad está pensada para redes controladas, como una VLAN de invitados o una red Wi-Fi de laboratorio. La sesión se identifica por la dirección IP de origen del cliente. No es adecuada para entornos donde muchos usuarios independientes comparten una misma IP NAT, salvo que todos deban tratarse como una única sesión.

## 1. Arquitectura

El flujo es el siguiente:

1. El cliente se conecta a la red LAN o Wi-Fi controlada.
2. El firewall envía el tráfico HTTP a Squid en modo intercept, o el cliente se configura para utilizar Squid explícitamente.
3. Squid pregunta al helper de ACL externa si la IP de origen tiene una sesión activa.
4. El helper lee una IP por línea desde stdin y consulta la base de datos de SquidStats.
5. El helper devuelve `OK` si la sesión está activa y `ERR` en cualquier otro caso.
6. Squid redirige las peticiones HTTP no autenticadas a `/portal/login`.
7. El portal autentica al usuario contra la configuración LDAP/AD de SquidStats.
8. SquidStats crea o renueva una sesión para la IP del cliente.
9. Las siguientes peticiones de esa IP se permiten hasta que la sesión expire o un administrador la revoque.

Componentes relevantes del proyecto:

- `services/captive_portal/session_service.py`: creación, validación, revocación y expiración de sesiones.
- `services/captive_portal/helper/captive_portal_helper.py`: protocolo de `external_acl_type` de Squid.
- `services/ldap/ldap_service.py`: autenticación de usuarios finales contra LDAP/AD.
- `services/squid/captive_portal_config_service.py`: bloque administrado de configuración de Squid.
- `routes/captive_portal_routes.py`: rutas públicas del portal.
- `routes/admin/captive_portal.py`: configuración administrativa y sesiones activas.
- `alembic/versions/014_add_captive_portal.py`: esquema de base de datos.

## 2. Limitaciones importantes

### Sesiones por IP de origen

La sesión se guarda por dirección IP. Si diez clientes llegan a Squid como `192.168.10.20`, autenticar a uno autentica esa dirección para los diez. Si esto no es aceptable, utiliza autenticación explícita del proxy o una pasarela de red con identidad individual por cliente.

### Intercepción de HTTPS

Una redirección normal de `http_access` puede redirigir peticiones HTTP. No puede sustituir de forma segura páginas HTTPS arbitrarias por una página de login HTTP. Además, los navegadores modernos utilizan HSTS, QUIC/HTTP3, validación de certificados y mecanismos propios de detección de portales cautivos, por lo que interceptar HTTPS es frágil.

Comportamiento recomendado en producción:

- Redirigir el puerto 80 al portal cautivo.
- No redirigir ciegamente el puerto 443 al puerto HTTP interceptado de Squid.
- Permitir el host del portal y los servicios DNS/DHCP necesarios antes de la regla cautiva.
- Usar una pasarela cautiva dedicada o una solución de portal cautivo nativa del sistema si es necesario gestionar la incorporación por HTTPS.
- Si los clientes están configurados explícitamente para usar el proxy, Squid puede autenticar la petición `CONNECT`, pero no puede mostrar una página de login arbitraria dentro del túnel cifrado.

### El helper debe ejecutarse donde se ejecuta Squid

La directiva generada utiliza el Python y la ruta del helper visibles para el proceso de SquidStats. Squid debe poder ejecutar esa ruta y acceder a la misma base de datos.

El `docker-compose.yml` actual del repositorio ejecuta solamente `squidstats_app`; no ejecuta Squid. Por eso, cuando Squid se ejecuta en otro host o contenedor, no debes apuntar Squid a una ruta de helper que solo existe dentro del contenedor Flask. Instala una copia del helper y de los módulos necesarios en el host de Squid, o utiliza un servicio local de helper con un transporte auditado. La disposición más sencilla y fiable es:

- Squid y el helper en el mismo host.
- El helper y Flask utilizan el mismo archivo SQLite, o ambos se conectan a la misma base de datos MariaDB/PostgreSQL.
- El helper se ejecuta con un usuario restringido y, cuando sea posible, con acceso de solo lectura a la base de datos.

## 3. Requisitos previos

Prepara lo siguiente:

- Squid 4 o posterior con soporte para `external_acl_type`.
- Python 3.12 o posterior, utilizando el runtime compatible con el proyecto.
- El entorno virtual y el código de SquidStats disponibles para el helper.
- La base de datos migrada hasta `014_add_captive_portal`.
- Conectividad LDAP o Active Directory desde SquidStats.
- Una URL pública o un nombre DNS interno para el portal, por ejemplo `https://portal.example.net:5000`.
- Un firewall o router donde se pueda aislar la VLAN de clientes de la red de administración.
- DNS y DHCP disponibles para clientes no autenticados.
- Un certificado TLS si el portal se sirve por HTTPS.

No expongas el panel de administración directamente a la red de invitados. Protégelo con una VLAN de administración, VPN, reglas de acceso del reverse proxy o reglas separadas del firewall.

## 4. Configuración del entorno

Copia el archivo de ejemplo y define valores de producción:

```sh
cd /opt/SquidStats/app
cp example.env .env
chmod 600 .env
```

Como mínimo, revisa estos valores:

```dotenv
VERSION=2.6
FLASK_DEBUG=False
LISTEN_HOST=127.0.0.1
LISTEN_PORT=5000

SECRET_KEY=pon-aqui-un-secreto-largo-y-aleatorio
JWT_SECRET_KEY=pon-aqui-otro-secreto-largo-y-aleatorio
FIRST_PASSWORD=cambia-esta-clave-antes-del-primer-login

DATABASE_TYPE=SQLITE
DATABASE_STRING_CONNECTION=/opt/SquidStats/app/squidstats.db

SQUID_HOST=127.0.0.1
SQUID_PORT=3128
SQUID_CONFIG_PATH=/etc/squid/squid.conf
ACL_FILES_DIR=/etc/squid/squid.d
```

Para una base de datos externa, utiliza la configuración existente del proyecto y asegúrate de que el helper recibe las mismas variables de entorno. Nunca uses una ruta de base de datos que exista dentro de un contenedor pero no esté montada en el host donde se ejecuta Squid.

Puedes generar secretos con un gestor de contraseñas o con:

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

No uses `FLASK_DEBUG=True` en producción. No subas `.env` al repositorio.

## 5. Instalar y migrar la base de datos

Desde la raíz del proyecto:

```sh
python3 -m venv /opt/SquidStats/venv
/opt/SquidStats/venv/bin/pip install -r requirements.txt
cd /opt/SquidStats/app
/opt/SquidStats/venv/bin/python manage_db.py upgrade
/opt/SquidStats/venv/bin/python manage_db.py current
```

La revisión actual debe incluir `014_add_captive_portal`. La aplicación también ejecuta migraciones al arrancar, pero ejecutar el comando explícitamente permite detectar errores antes de activar el servicio.

No uses `manage_db.py init` sobre una base de datos que no hayas verificado. `init` marca la base de datos y no aplica los cambios de esquema pendientes.

## 6. Configurar LDAP o Active Directory

Abre el panel de administración y configura **LDAP/AD y Grupos**. Debes definir:

- Host y puerto LDAP.
- Uso de TLS/SSL.
- Tipo de autenticación: `SIMPLE` o `NTLM`.
- DN y contraseña de la cuenta de servicio.
- Base DN.

La cuenta de servicio necesita permisos suficientes para buscar usuarios. No necesita privilegios de administrador. El portal busca primero al usuario y después intenta hacer bind con el usuario y contraseña introducidos.

Recomendaciones:

- Usa LDAPS o LDAP con StartTLS cuando sea compatible.
- Usa un certificado que el host pueda validar.
- Limita la cuenta de servicio a permisos de búsqueda.
- Restringe mediante firewall el acceso LDAP al host de SquidStats.
- Prueba el login de un usuario real antes de activar la regla de Squid.
- Para AD/NTLM utiliza un formato admitido por el directorio, como `DOMAIN\\usuario` o `usuario@dominio`.

## 7. Preparar la URL del portal y el acceso de red

En **Admin > Portal Cautivo**, define la URL pública, por ejemplo:

```text
https://portal.example.net
```

La URL debe ser HTTP o HTTPS y no debe contener credenciales, parámetros de consulta ni fragmentos. El host del portal debe ser accesible antes de autenticarse. Permite como mínimo:

- Resolución DNS del nombre del portal.
- TCP 80/443 hacia el reverse proxy del portal.
- TCP 389/636 desde SquidStats hacia LDAP/AD, según corresponda.
- DHCP y gateway para la VLAN de clientes.
- El puerto de escucha de Squid desde la VLAN de clientes.

Si SquidStats y Squid están en máquinas diferentes, confirma que el nombre del portal resuelve hacia la aplicación SquidStats o su reverse proxy, no hacia el puerto proxy de Squid.

Un reverse proxy típico debe reenviar las rutas del portal hacia `127.0.0.1:5000` y no debe exponer `/admin` a la red de invitados.

## 8. Configurar Squid

El bloque generado contiene directivas equivalentes a:

```squid
external_acl_type squidstats_captive_portal ttl=60 negative_ttl=0 %SRC "/opt/SquidStats/venv/bin/python" "/opt/SquidStats/app/services/captive_portal/helper/captive_portal_helper.py"
acl squidstats_captive_portal_valid external squidstats_captive_portal
acl squidstats_captive_portal_domain dstdomain "portal.example.net"
deny_info 302:https://portal.example.net/portal/login?redirect=%s squidstats_captive_portal_valid
http_access allow squidstats_captive_portal_domain
http_access deny !squidstats_captive_portal_valid
```

Las rutas exactas de Python y del helper se generan desde la instalación que está ejecutando SquidStats. El bloque del portal debe quedar después de las ACL básicas de seguridad de Squid y después de la excepción estrecha de Cache Manager, pero antes de las reglas generales `http_access allow`.

Antes de recargar Squid, valida la configuración:

```sh
sudo squid -k parse -f /etc/squid/squid.conf
sudo squid -k reconfigure
```

En una instalación systemd:

```sh
sudo systemctl reload squid
sudo systemctl status squid --no-pager
```

La acción administrativa de SquidStats también intenta recargar Squid después de aplicar la configuración. El resultado de la recarga es obligatorio: guardar el archivo sin recargar Squid correctamente no constituye un despliegue funcional.

### Modos de escritura managed y manual

El servicio Debian define intencionadamente:

```ini
Environment=SQUIDSTATS_SQUID_CONFIG_WRITE_MODE=manual
```

Esto protege `/etc/squid` frente al proceso web. En este modo el panel muestra una vista previa, pero no escribe `squid.conf`. Copia el bloque generado mediante el procedimiento aprobado, valida la configuración y recarga Squid como root.

En una instalación controlada que permita explícitamente las escrituras desde el panel, define:

```ini
SQUIDSTATS_SQUID_CONFIG_WRITE_MODE=managed
```

Úsalo solamente cuando la cuenta del servicio tenga los permisos exactos y exista un procedimiento auditado de rollback. No concedas permisos amplios de escritura sobre `/etc`.

## 9. Instalar el helper en el host de Squid

Si Squid y SquidStats están en el mismo host, prueba el helper directamente:

```sh
sudo -u squid /opt/SquidStats/venv/bin/python \
  /opt/SquidStats/app/services/captive_portal/helper/captive_portal_helper.py
```

El comando espera entrada. Escribe una IP y pulsa Enter. Debe devolver `OK` o `ERR`; pulsa `Ctrl-D` para salir.

Si el helper está en un host de Squid separado:

1. Copia el paquete necesario de la aplicación, las dependencias del entorno virtual y el helper a una ruta controlada.
2. Copia los valores necesarios de `.env` o utiliza un archivo de entorno dedicado.
3. Verifica que la base de datos sea accesible desde ese host.
4. Define propietario y permisos para que únicamente el usuario de Squid pueda ejecutar o leer el helper y las credenciales de base de datos.
5. Utiliza rutas absolutas para Python y el helper en `external_acl_type`.

El helper no debe imprimir logs en stdout. Squid utiliza stdout para el protocolo de ACL. Los diagnósticos deben ir a stderr o al log de la aplicación.

### Squid en un contenedor y SquidStats en el host

`external_acl_type` ejecuta el helper localmente dentro del entorno de Squid; no realiza una llamada HTTP al Flask que corre en el host. Por tanto, el contenedor de Squid debe tener disponibles:

- El ejecutable de Python y sus dependencias.
- El código del helper y los módulos de SquidStats que importa.
- El archivo `.env` correspondiente.
- La misma base de datos, o conectividad hacia la misma base de datos del host.

Si la aplicación del host genera la configuración que después se copia al contenedor, define las rutas que existen dentro del contenedor antes de volver a generar el bloque:

```dotenv
SQUIDSTATS_HELPER_PYTHON=/usr/bin/python3
SQUIDSTATS_HELPER_PATH=/opt/squidstats-helper/services/captive_portal/helper/captive_portal_helper.py
```

Estas variables solo cambian las rutas escritas en `squid.conf`; no copian archivos ni instalan dependencias. Monta el código y la base de datos en esas rutas, instala las dependencias Python dentro del contenedor y prueba allí mismo:

```sh
docker exec -it squid /usr/bin/python3 \
  /opt/squidstats-helper/services/captive_portal/helper/captive_portal_helper.py
```

Escribe una IP seguida de Enter y confirma que responde `OK` o `ERR`. Si el helper usa SQLite, el archivo montado debe ser el mismo que actualiza SquidStats; dos copias del archivo SQLite producirán sesiones aparentemente inexistentes.

## 10. Redirección del firewall con iptables

El siguiente ejemplo supone un gateway Linux donde:

- `LAN_IF=br-lan` es la interfaz de invitados.
- `WAN_IF=eth0` es la interfaz hacia Internet.
- `LAN_CIDR=192.168.50.0/24` es la red de invitados.
- Squid escucha en `3128` en modo intercept.
- SquidStats está disponible como `portal.example.net` por TCP 443.

Sustituye todos los valores según tu topología. Prueba desde una sesión de mantenimiento antes de persistir las reglas.

### Activar forwarding

```sh
sudo sysctl -w net.ipv4.ip_forward=1
```

Persiste la configuración en `/etc/sysctl.d/99-captive-portal.conf`:

```ini
net.ipv4.ip_forward=1
```

Aplica los cambios:

```sh
sudo sysctl --system
```

### Listener intercept de Squid

El listener de Squid debe utilizar modo intercept en el puerto que recibe el tráfico HTTP redirigido:

```squid
http_port 3128 intercept
```

No uses `http_port ... intercept` para clientes que ya estén configurados con un proxy explícito, salvo que hayas separado intencionadamente ambos listeners.

### Redirección HTTP

```sh
LAN_IF=br-lan
WAN_IF=eth0
LAN_CIDR=192.168.50.0/24
SQUID_PORT=3128

sudo iptables -t nat -A PREROUTING -i "$LAN_IF" -s "$LAN_CIDR" \
  -p tcp --dport 80 -j REDIRECT --to-ports "$SQUID_PORT"
```

No redirijas el tráfico destinado al propio servicio del portal. Si el portal está en la misma máquina, utiliza una regla ACCEPT anterior o un reverse proxy con una dirección separada. Una disposición habitual es alojar el portal en otro host o balanceador, de forma que el cliente evite naturalmente el camino de intercepción.

### Política de forwarding

Un ejemplo restrictivo es:

```sh
sudo iptables -A FORWARD -i "$LAN_IF" -o "$WAN_IF" -s "$LAN_CIDR" \
  -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -A FORWARD -i "$LAN_IF" -o "$WAN_IF" -s "$LAN_CIDR" \
  -j ACCEPT
```

Si el firewall utiliza una política por defecto `DROP`, añade reglas explícitas para DNS, DHCP, el portal, LDAP desde el host de la aplicación y el listener de Squid. No permitas que la red de invitados alcance la interfaz de administración.

### NAT para clientes autenticados

Si este host también es el gateway de Internet:

```sh
sudo iptables -t nat -A POSTROUTING -s "$LAN_CIDR" -o "$WAN_IF" -j MASQUERADE
```

No mezcles estos ejemplos sin revisión con un gestor de firewall existente. `ufw`, firewalld, nftables, Docker y Kubernetes pueden instalar sus propias cadenas y reglas de ordenación.

### No redirigir HTTPS a ciegas

Esta regla no está recomendada para un portal HTTP normal:

```sh
# No añadir en un portal cautivo HTTP normal:
# iptables -t nat -A PREROUTING -i "$LAN_IF" -p tcp --dport 443 \
#   -j REDIRECT --to-ports "$SQUID_PORT"
```

Redirigir TCP 443 a un listener intercept HTTP produce errores TLS o peticiones CONNECT inutilizables. Usa una pasarela cautiva dedicada con walled garden si necesitas gestionar el acceso inicial por HTTPS.

## 11. Alternativa con nftables

En sistemas que utilizan nftables, la redirección HTTP equivalente es conceptualmente:

```nft
table ip nat {
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        iifname "br-lan" ip saddr 192.168.50.0/24 tcp dport 80 redirect to :3128
    }
}
```

Integra esta regla en el conjunto nftables existente en lugar de crear una tabla en conflicto. Persiste la configuración utilizando el servicio nftables de la distribución.

## 12. Activar la funcionalidad

Después de probar LDAP, la URL del portal, el helper y Squid:

1. Abre **Admin > Portal Cautivo**.
2. Define el título del portal.
3. Define la URL pública.
4. Define la duración de la sesión. Empieza con 480 minutos o menos.
5. Define el `TTL de la ACL` con un valor bajo, como 30-60 segundos.
6. Mantén `negative_ttl=0` durante las pruebas para que un cliente recién autenticado sea reconocido inmediatamente.
7. Activa el portal.
8. Aplica la configuración generada según el modo `managed` o `manual`.
9. Valida y recarga Squid.
10. Prueba desde un cliente no autenticado.

Valores iniciales recomendados:

```text
Duración de sesión: 480 minutos
TTL de ACL: 30 segundos
TTL negativo de ACL: 0 segundos
```

Reduce la duración de sesión en redes públicas. Reduce el TTL de ACL cuando la revocación inmediata sea importante. Los valores altos reducen la carga del helper y de la base de datos, pero retrasan los cambios de sesión.

## 13. Persistencia y arranque del servicio

Para una instalación mediante el paquete Debian:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now squidstats
sudo systemctl status squidstats --no-pager
sudo journalctl -u squidstats -n 100 --no-pager
```

El servicio se ejecuta como `squidstats`, con `ProtectSystem=full` y sin escalada de privilegios. Por eso el servicio empaquetado utiliza el modo manual para la configuración de Squid.

Para Docker:

```sh
docker compose up -d --build
docker compose logs -f squidstats
```

Monta de forma consistente la base de datos y `.env`, y confirma que el entorno de ejecución del helper esté disponible para Squid. Un contenedor Squid separado necesita su propia ruta de helper y conectividad hacia la misma base de datos.

## 14. Checklist de verificación

Ejecuta estas comprobaciones en orden:

```sh
# Esquema de base de datos
/opt/SquidStats/venv/bin/python manage_db.py current

# Importación de la aplicación
/opt/SquidStats/venv/bin/python -c 'import app; print("app import OK")'

# Configuración de Squid
sudo squid -k parse -f /etc/squid/squid.conf

# Servicio SquidStats
sudo systemctl status squidstats --no-pager

# Servicio Squid
sudo systemctl status squid --no-pager

# Protocolo del helper
sudo -u squid /opt/SquidStats/venv/bin/python \
  /opt/SquidStats/app/services/captive_portal/helper/captive_portal_helper.py
```

Prueba funcional:

1. Conecta un cliente de prueba a la VLAN de invitados.
2. Confirma que recibe IP, gateway y DNS.
3. Navega a una URL HTTP normal.
4. Confirma que Squid redirige al portal.
5. Inicia sesión con un usuario LDAP de prueba.
6. Confirma en el panel que la IP aparece como activa.
7. Vuelve a navegar y verifica que el acceso se permite.
8. Revoca la sesión desde el panel.
9. Confirma que la siguiente petición vuelve a ser desafiada después de expirar la caché de ACL.
10. Confirma que un destino HTTPS no está siendo redirigido incorrectamente.

## 15. Diagnóstico

### El helper no devuelve nada

- Confirma que ningún log se escribe en stdout.
- Ejecútalo manualmente como el usuario de Squid.
- Verifica la ruta del helper y el ejecutable Python en `squid.conf`.
- Verifica que el helper pueda cargar `.env` y conectarse a la base de datos.
- Revisa permisos y políticas SELinux/AppArmor.

### Squid muestra errores del helper o `BH`

- Revisa la sintaxis de `external_acl_type` y las rutas entre comillas.
- Confirma que el helper devuelve exactamente una línea `OK` o `ERR` por cada línea recibida.
- Confirma que el helper no termina ante errores de base de datos.
- Revisa los logs de caché de Squid y el journal del servicio SquidStats.

### El login funciona pero el acceso sigue bloqueado

- Confirma que se creó una fila para la IP real del cliente.
- Comprueba si un reverse proxy o NAT cambia la dirección de origen.
- Espera el TTL configurado o usa TTL negativo cero.
- Verifica que helper y Flask utilicen la misma base de datos.
- Verifica que el portal esté activado en la configuración de la base de datos.

### El portal entra en un bucle de redirecciones

- Confirma que el hostname del portal está permitido antes de `http_access deny !squidstats_captive_portal_valid`.
- Confirma que DNS y el reverse proxy del portal son accesibles sin sesión activa.
- Verifica que la URL del portal no sea redirigida a Squid.
- Confirma que la URL pública apunta a SquidStats, no al puerto proxy de Squid.

### HTTPS falla

- Elimina cualquier regla REDIRECT de 443 hacia 3128.
- Confirma que el cliente no esté utilizando QUIC/HTTP3 si las pruebas requieren TCP.
- Utiliza una pasarela cautiva compatible para el acceso inicial HTTPS.
- Para clientes con proxy explícito, revisa la política CONNECT separadamente de las redirecciones HTTP.

### No se puede escribir la configuración

- Comprueba `SQUIDSTATS_SQUID_CONFIG_WRITE_MODE`.
- El servicio Debian funciona intencionadamente en modo `manual`.
- Usa la vista previa, aplica el bloque mediante el procedimiento privilegiado, ejecuta `squid -k parse` y recarga Squid.

## 16. Checklist de seguridad

- Usa HTTPS para el portal.
- Mantén `FLASK_DEBUG=False`.
- Utiliza valores únicos para `SECRET_KEY` y `JWT_SECRET_KEY`.
- Cambia inmediatamente la contraseña inicial del administrador.
- No expongas `/admin` a los clientes invitados.
- Protege `.env`, las bases de datos, las credenciales LDAP y la configuración de Squid.
- Restringe los permisos del helper y de la base de datos.
- Utiliza una cuenta LDAP de servicio con privilegios mínimos.
- Monitoriza y limita los intentos de login del portal.
- Mantén los TTL de ACL suficientemente bajos para los requisitos de revocación.
- Haz copias de seguridad de la base de datos y de Squid antes de cambiar la configuración.
- No uses sesiones por IP cuando la identidad NAT compartida no sea aceptable.
- Revisa las reglas del firewall después de cada cambio de topología.

## 17. Rollback

Para desactivar la funcionalidad de forma segura:

1. Desactiva **Portal Cautivo** en el panel, o elimina manualmente el bloque administrado.
2. Valida la configuración de Squid.
3. Recarga Squid.
4. Elimina la redirección HTTP del firewall si ya no es necesaria.
5. Conserva la migración de base de datos salvo que vayas a eliminar completamente la funcionalidad del código.
6. Revoca las sesiones activas si es necesario.

Nunca elimines un bloque activo de Squid sin validar el archivo resultante. Conserva disponible la última copia de configuración conocida como válida.
