# Guía para Probar el Workflow Localmente

Esta guía te ayudará a probar el workflow de GitHub Actions localmente antes de subirlo al repositorio.

## Método 1: Usar act (Recomendado para testing básico)

### 1. Instalar act

```bash
# macOS con Homebrew
brew install act

# Verificar instalación
act --version
```

### 2. Configurar secretos locales

Edita el archivo `.github/workflows/.secrets` con tus valores reales:

```bash
# Crear archivo de secretos
nano .github/workflows/.secrets
```

Contenido:
```
GPG_PRIVATE_KEY=-----BEGIN PGP PRIVATE KEY BLOCK-----
tu-clave-completa-aqui
-----END PGP PRIVATE KEY BLOCK-----
GPG_PASSPHRASE=tu-passphrase
GPG_KEY_ID=ABCD1234EFGH5678
PPA_NAME=ppa:usuario/squidstats
```

### 3. Ejecutar el workflow

```bash
# Test completo del job build-deb
act -j build-deb --secret-file .github/workflows/.secrets

# Test solo hasta construir el .deb (sin subir a PPA)
act -j build-deb --secret-file .github/workflows/.secrets -e .github/workflows/test-event.json

# Listar los jobs disponibles
act -l

# Dry-run (ver qué haría sin ejecutar)
act -j build-deb --secret-file .github/workflows/.secrets --dryrun
```

### 4. Crear evento de prueba manual

```bash
cat > .github/workflows/test-event.json << 'EOF'
{
  "inputs": {
    "version": "1.0.0-test"
  }
}
EOF

# Ejecutar con evento personalizado
act workflow_dispatch -j build-deb --secret-file .github/workflows/.secrets --eventpath .github/workflows/test-event.json
```

### Limitaciones de act:
- Usa imágenes Docker, puede ser lento la primera vez
- Algunas acciones de GitHub pueden no funcionar idénticamente
- No ejecuta la parte de subida al PPA (lo cual está bien para testing)

---

## Método 2: Docker Manual (Más control)

### 1. Crear Dockerfile de prueba

```bash
cat > .github/workflows/Dockerfile.test << 'EOF'
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    debhelper \
    dh-python \
    python3-all \
    python3-setuptools \
    python3-pip \
    devscripts \
    build-essential \
    lintian \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

CMD ["/bin/bash"]
EOF
```

### 2. Script de prueba

```bash
cat > .github/workflows/test-build.sh << 'EOF'
#!/bin/bash
set -e

VERSION="${1:-1.0.0-test}"
PACKAGE_NAME="squidstats"

echo "=== Building package version: $VERSION ==="

# Crear estructura
PACKAGE_DIR="${PACKAGE_NAME}-${VERSION}"
mkdir -p $PACKAGE_DIR

# Copiar archivos (ajusta según tu proyecto)
cp -r app.py config.py requirements.txt $PACKAGE_DIR/
cp -r database parsers routes services static templates utils $PACKAGE_DIR/ 2>/dev/null || true
cp -r assets $PACKAGE_DIR/ 2>/dev/null || true

# Crear debian/
mkdir -p $PACKAGE_DIR/debian

# (Aquí van todos los cat > debian/* del workflow)
# ... copia el contenido del workflow aquí ...

echo "=== Building package ==="
cd $PACKAGE_DIR
debuild -us -uc -b
cd ..

echo "=== Checking with lintian ==="
lintian --info *.deb || true

echo "=== Package built successfully ==="
ls -lh *.deb

echo "=== Package info ==="
dpkg-deb --info *.deb

echo "=== Package contents ==="
dpkg-deb --contents *.deb
EOF

chmod +x .github/workflows/test-build.sh
```

### 3. Ejecutar en Docker

```bash
# Construir imagen
docker build -f .github/workflows/Dockerfile.test -t squidstats-builder .

# Ejecutar build
docker run --rm -v "$(pwd):/workspace" squidstats-builder ./github/workflows/test-build.sh 1.0.0-test

# Los archivos .deb quedarán en tu directorio actual
```

---

## Método 3: VM Local con Vagrant (Más realista)

### 1. Crear Vagrantfile

```bash
cat > Vagrantfile << 'EOF'
Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/jammy64"
  
  config.vm.provider "virtualbox" do |vb|
    vb.memory = "2048"
    vb.cpus = 2
  end
  
  config.vm.provision "shell", inline: <<-SHELL
    apt-get update
    apt-get install -y debhelper dh-python python3-all python3-setuptools \
                       devscripts build-essential lintian git
  SHELL
  
  config.vm.synced_folder ".", "/vagrant"
end
EOF
```

### 2. Usar la VM

```bash
# Iniciar VM
vagrant up

# Conectar
vagrant ssh

# Dentro de la VM
cd /vagrant
./.github/workflows/test-build.sh 1.0.0-test

# Salir
exit

# Detener VM
vagrant halt
```

---

## Método 4: Testing Incremental (Lo más práctico)

### Script de validación rápida

```bash
cat > .github/workflows/validate-structure.sh << 'EOF'
#!/bin/bash

echo "=== Validando estructura del proyecto ==="

# Verificar archivos necesarios
FILES=(
    "app.py"
    "config.py"
    "requirements.txt"
    "database/__init__.py"
    "parsers/__init__.py"
    "routes/__init__.py"
    "services/__init__.py"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file existe"
    else
        echo "✗ $file NO ENCONTRADO"
        exit 1
    fi
done

echo ""
echo "=== Validando requirements.txt ==="
cat requirements.txt

echo ""
echo "=== Simulando creación de estructura debian/ ==="
TEMP_DIR=$(mktemp -d)
mkdir -p "$TEMP_DIR/debian"

echo "✓ Estructura básica creada en $TEMP_DIR"

echo ""
echo "=== Test de sintaxis Python ==="
python3 -m py_compile app.py config.py
echo "✓ Sintaxis correcta"

echo ""
echo "✓ Validación completa"
rm -rf "$TEMP_DIR"
EOF

chmod +x .github/workflows/validate-structure.sh
```

### Ejecutar validación

```bash
# Validación rápida
./.github/workflows/validate-structure.sh

# Si pasa, probar con act
act -j build-deb --secret-file .github/workflows/.secrets -n

# Si act funciona, probar build completo
act -j build-deb --secret-file .github/workflows/.secrets
```

---

## Checklist de Validación

Antes de subir al repositorio, verifica:

- [ ] El workflow tiene la sintaxis YAML correcta
  ```bash
  # Instalar yamllint
  pip3 install yamllint
  
  # Validar
  yamllint .github/workflows/create-ppa.yml
  ```

- [ ] Los paths de archivos son correctos
  ```bash
  ./.github/workflows/validate-structure.sh
  ```

- [ ] El paquete se construye sin errores
  ```bash
  act -j build-deb --secret-file .github/workflows/.secrets
  ```

- [ ] El archivo .deb se crea correctamente
  ```bash
  # Después de ejecutar act o el script
  ls -lh *.deb
  dpkg-deb --info squidstats_*.deb
  ```

- [ ] Los secretos están configurados (en local)
  ```bash
  cat .github/workflows/.secrets
  ```

---

## Recomendación Final

**El flujo más eficiente:**

1. **Validación sintaxis**: `yamllint .github/workflows/create-ppa.yml`
2. **Validación estructura**: `./.github/workflows/validate-structure.sh`
3. **Build local rápido**: Usar el script de Docker
4. **Test completo**: `act -j build-deb --secret-file .github/workflows/.secrets`
5. **Verificar .deb**: `dpkg-deb --info *.deb`
6. **Subir a GitHub**: Crear rama de prueba primero

```bash
# Crear rama de testing
git checkout -b test/github-actions
git add .github/workflows/
git commit -m "test: add PPA workflow"
git push origin test/github-actions

# Probar con tag en la rama
git tag v0.0.1-test
git push origin v0.0.1-test

# Ver resultados en GitHub Actions
# Si funciona, merge a main
```

---

## Troubleshooting

### act no encuentra Docker
```bash
# Verificar Docker está corriendo
docker ps

# Iniciar Docker Desktop si es necesario
```

### Errores de permisos en act
```bash
# Ejecutar con privilegios si es necesario
act -j build-deb --secret-file .github/workflows/.secrets --privileged
```

### Quiero ver el output completo
```bash
# Modo verbose
act -j build-deb --secret-file .github/workflows/.secrets -v
```
