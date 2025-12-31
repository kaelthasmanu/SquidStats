# Configuración del GitHub Actions para PPA

Este workflow automatiza la creación de paquetes .deb y su publicación en un PPA de Ubuntu.

## Requisitos Previos

### 1. Cuenta en Launchpad

1. Crea una cuenta en [Launchpad](https://launchpad.net/)
2. Crea un PPA en tu perfil (por ejemplo: `ppa:tu-usuario/squidstats`)

### 2. Generar clave GPG

```bash
# Generar nueva clave GPG
gpg --full-generate-key

# Opciones recomendadas:
# - Tipo: RSA and RSA
# - Tamaño: 4096
# - Validez: 0 (no expira) o el tiempo que prefieras
# - Nombre: Tu nombre
# - Email: El mismo email de Launchpad

# Listar claves
gpg --list-secret-keys --keyid-format=long

# Exportar clave privada (para GitHub Secrets)
gpg --armor --export-secret-keys TU_KEY_ID > private-key.asc

# Exportar clave pública (para Launchpad)
gpg --armor --export TU_KEY_ID > public-key.asc
```

### 3. Subir clave pública a Launchpad

1. Ve a tu perfil de Launchpad
2. Navega a "OpenPGP keys"
3. Importa el contenido de `public-key.asc`

### 4. Subir clave pública a Ubuntu Keyserver

```bash
gpg --keyserver keyserver.ubuntu.com --send-keys TU_KEY_ID
```

## Configuración de GitHub Secrets

Ve a tu repositorio → Settings → Secrets and variables → Actions y crea los siguientes secrets:

### Secrets Requeridos:

1. **`GPG_PRIVATE_KEY`**
   - Contenido del archivo `private-key.asc`
   - Incluye las líneas `-----BEGIN PGP PRIVATE KEY BLOCK-----` y `-----END PGP PRIVATE KEY BLOCK-----`

2. **`GPG_PASSPHRASE`**
   - La contraseña que usaste al crear la clave GPG

3. **`GPG_KEY_ID`**
   - El ID de tu clave GPG (formato largo, ej: `ABCD1234EFGH5678`)
   - Obtenerlo con: `gpg --list-secret-keys --keyid-format=long`

4. **`PPA_NAME`**
   - El nombre de tu PPA en formato: `ppa:usuario/nombre-ppa`
   - Ejemplo: `ppa:kaelthasmanu/squidstats`

## Uso del Workflow

### Opción 1: Mediante Tags (Recomendado)

```bash
# Crear y subir un tag
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

El workflow se ejecutará automáticamente y:
- Construirá el paquete .deb
- Lo firmará con tu clave GPG
- Lo subirá al PPA
- Creará un release en GitHub

### Opción 2: Ejecución Manual

1. Ve a Actions en tu repositorio
2. Selecciona "Build and Publish to PPA"
3. Haz clic en "Run workflow"
4. Ingresa la versión deseada (ej: 1.0.0)

**Nota:** La ejecución manual NO sube al PPA, solo construye el paquete.

## Verificación

### Verificar en Launchpad

1. Ve a tu PPA en Launchpad
2. Deberías ver el paquete en "Packages"
3. El paquete debe mostrar estado "Published" después de unos minutos

### Instalación desde PPA

```bash
sudo add-apt-repository ppa:tu-usuario/squidstats
sudo apt update
sudo apt install squidstats
```

## Personalización

Edita las siguientes variables en `.github/workflows/create-ppa.yml`:

```yaml
env:
  PACKAGE_NAME: squidstats
  MAINTAINER_NAME: "Tu Nombre"
  MAINTAINER_EMAIL: "tu-email@example.com"
  DESCRIPTION: "Descripción de tu paquete"
```

## Troubleshooting

### Error: "GPG signing failed"
- Verifica que `GPG_PRIVATE_KEY` y `GPG_PASSPHRASE` sean correctos
- Asegúrate de incluir todo el bloque de la clave privada

### Error: "Upload rejected by PPA"
- Verifica que la clave GPG esté registrada en Launchpad
- La clave debe estar en el keyserver de Ubuntu
- El email de la clave debe coincidir con el de Launchpad

### Error: "Package already exists"
- Incrementa el número de versión
- O incrementa el número de release en `debian/changelog`

### El paquete no aparece en el PPA
- Revisa la cola de construcción en Launchpad
- Pueden tardar varios minutos en procesarse
- Revisa los logs de construcción en Launchpad

## Estructura del Paquete

El paquete instalará:
- Aplicación en `/opt/squidstats/`
- Configuración en `/etc/squidstats/.env`
- Logs en `/var/log/squidstats/`
- Servicio systemd: `squidstats.service`

## Comandos útiles después de la instalación

```bash
# Ver estado del servicio
sudo systemctl status squidstats

# Reiniciar servicio
sudo systemctl restart squidstats

# Ver logs
sudo journalctl -u squidstats -f

# Editar configuración
sudo nano /etc/squidstats/.env

# Reiniciar después de cambios
sudo systemctl restart squidstats
```

## Distribuciones Soportadas

Por defecto, el paquete se construye para Ubuntu 22.04 (Jammy). Para soportar otras versiones:

1. Modifica `debian/changelog` para incluir la distribución
2. Ajusta las dependencias en `debian/control` según la versión

Ejemplo para múltiples distribuciones:
```bash
# En el workflow, construir para cada distribución
for DIST in jammy focal noble; do
  debuild -S -sa -d
  dput ppa:usuario/ppa squidstats_version~${DIST}1_source.changes
done
```
