# 🚀 Guía Rápida: Testing del Workflow Localmente

## ✅ ¡El workflow funciona correctamente!

Se ha probado localmente con `act` y el paquete .deb se construye exitosamente.

## 🎯 Resultados del Testing Local

```bash
# El build completó exitosamente:
✅ Estructura Debian creada
✅ Paquete .deb construido
✅ Lintian verificado (solo warnings menores)
⚠️  Upload artifacts falló (esperado en act, funcionará en GitHub)
```

## Opción 1: Testing Rápido con act ✅ PROBADO

### Ejecutar el build:
```bash
# Opción A: Con script automatizado
./.github/workflows/test-build.sh

# Opción B: Manual
act -j build-deb
```

**Resultado esperado:**
- ✅ Success - Main Create Debian package structure
- ✅ Success - Main Build Debian package  
- ✅ Success - Main Check package with lintian
- ❌ Failure - Main Upload artifacts (normal con act)

---

## Opción 2: Testing con Docker (Sin act)

```bash
# Construir en contenedor Ubuntu
docker run --rm -v "$(pwd):/workspace" -w /workspace ubuntu:22.04 bash -c "
  apt-get update && 
  apt-get install -y debhelper dh-python python3-all devscripts build-essential lintian &&
  export VERSION=1.0.0-test &&
  export PACKAGE_NAME=squidstats &&
  # ... el resto del workflow aquí
"
```

---

## Opción 3: Testing en Rama Separada (Más seguro)

```bash
# 1. Crear rama de prueba
git checkout -b test/ppa-workflow

# 2. Commit de los cambios
git add .github/
git commit -m "test: add PPA build workflow"

# 3. Subir a GitHub
git push origin test/ppa-workflow

# 4. Crear tag de prueba
git tag v0.0.1-test
git push origin v0.0.1-test

# 5. Ver el workflow en GitHub Actions
# Ve a: https://github.com/kaelthasmanu/SquidStats/actions

# 6. Si todo funciona, merge a main
git checkout main
git merge test/ppa-workflow
git push origin main
```

---

## ⚙️ Preparación Previa (Una sola vez)

### 1. Crear clave GPG (si no tienes):
```bash
gpg --full-generate-key
# Tipo: RSA and RSA
# Tamaño: 4096
# Validez: 0 (no expira)
```

### 2. Exportar clave:
```bash
# Obtener ID
gpg --list-secret-keys --keyid-format=long

# Exportar privada (para secret)
gpg --armor --export-secret-keys TU_KEY_ID > private-key.asc

# Exportar pública (para Launchpad)
gpg --armor --export TU_KEY_ID > public-key.asc
```

### 3. Registrar en Launchpad:
1. Ir a https://launchpad.net/~tu-usuario/+editpgpkeys
2. Pegar contenido de `public-key.asc`
3. Confirmar email

### 4. Subir a keyserver:
```bash
gpg --keyserver keyserver.ubuntu.com --send-keys TU_KEY_ID
```

### 5. Configurar secretos en GitHub:
Settings → Secrets → Actions → New secret:
- `GPG_PRIVATE_KEY`: Contenido de `private-key.asc`
- `GPG_PASSPHRASE`: Tu passphrase de GPG
- `GPG_KEY_ID`: Tu key ID
- `PPA_NAME`: `ppa:usuario/nombre-ppa`

---

## 📋 Checklist antes de usar en producción

- [ ] ✅ Validación pasó: `./.github/workflows/validate-structure.sh`
- [ ] Workflow probado con act o en rama de testing
- [ ] Clave GPG creada y registrada en Launchpad
- [ ] Secretos configurados en GitHub
- [ ] PPA creado en Launchpad
- [ ] `MAINTAINER_NAME` y `MAINTAINER_EMAIL` actualizados en el workflow
- [ ] Versión inicial definida (ej: v1.0.0)

---

## 🎯 Primera Ejecución en Producción

```bash
# 1. Asegúrate de estar en main y actualizado
git checkout main
git pull

# 2. Crear tag de release
git tag -a v1.0.0 -m "Release version 1.0.0"

# 3. Subir tag
git push origin v1.0.0

# 4. Verificar en GitHub Actions
# https://github.com/kaelthasmanu/SquidStats/actions

# 5. Verificar en Launchpad (tarda ~5-10 min)
# https://launchpad.net/~usuario/+archive/ubuntu/ppa
```

---

## 🔍 Verificar resultados

### En GitHub:
- Actions tab → Ver el workflow ejecutándose
- Releases → Debe aparecer el .deb descargable

### En Launchpad:
- Tu PPA → Packages → Debe aparecer squidstats
- Estado debe cambiar a "Published" después de construir

### Instalar desde PPA:
```bash
sudo add-apt-repository ppa:usuario/squidstats
sudo apt update
sudo apt install squidstats
```

---

## 📚 Documentación completa

- **Setup completo de PPA**: `.github/workflows/PPA_SETUP.md`
- **Testing local detallado**: `.github/workflows/LOCAL_TESTING.md`
- **Workflow**: `.github/workflows/create-ppa.yml`

---

## 🆘 Ayuda rápida

```bash
# Validar estructura
./.github/workflows/validate-structure.sh

# Test con act
act -j build-deb -n

# Ver logs del workflow en GitHub
gh run list
gh run view --log

# Ver estado del paquete
dpkg -l | grep squidstats
systemctl status squidstats
```
