#!/bin/bash
# Script para configurar GPG y obtener los secrets necesarios

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Configuración de Secrets para GitHub Actions PPA${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""

# Verificar si gh está instalado
if ! command -v gh &> /dev/null; then
    echo -e "${YELLOW}⚠️  GitHub CLI (gh) no está instalado${NC}"
    echo "   Instalar con: brew install gh"
    echo ""
    GH_AVAILABLE=false
else
    GH_AVAILABLE=true
fi

# Verificar si gpg está instalado
if ! command -v gpg &> /dev/null; then
    echo -e "${RED}❌ GPG no está instalado${NC}"
    echo "   Instalar con: brew install gnupg"
    exit 1
fi

echo -e "${GREEN}═══ PASO 1: Crear o seleccionar clave GPG ═══${NC}"
echo ""

# Listar claves existentes
KEYS=$(gpg --list-secret-keys --keyid-format=long 2>/dev/null | grep -E "^sec" || true)

if [ -z "$KEYS" ]; then
    echo -e "${YELLOW}No se encontraron claves GPG existentes${NC}"
    echo ""
    read -p "¿Deseas crear una nueva clave GPG? (s/n): " CREATE_KEY
    
    if [[ $CREATE_KEY == "s" || $CREATE_KEY == "S" ]]; then
        echo ""
        echo "Creando nueva clave GPG..."
        echo "Por favor, proporciona la siguiente información:"
        echo ""
        read -p "Nombre completo: " FULLNAME
        read -p "Email (debe coincidir con Launchpad): " EMAIL
        
        # Crear clave
        cat > /tmp/gpg-gen-key << EOF
%echo Generando clave GPG
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: $FULLNAME
Name-Email: $EMAIL
Expire-Date: 0
%commit
%echo Clave GPG generada
EOF
        
        gpg --batch --gen-key /tmp/gpg-gen-key
        rm /tmp/gpg-gen-key
        
        echo -e "${GREEN}✓ Clave GPG creada exitosamente${NC}"
    else
        echo -e "${RED}No se puede continuar sin una clave GPG${NC}"
        exit 1
    fi
fi

echo ""
echo "Claves GPG disponibles:"
gpg --list-secret-keys --keyid-format=long

echo ""
read -p "Ingresa el KEY_ID (formato largo, ej: ABCD1234EFGH5678): " KEY_ID

if [ -z "$KEY_ID" ]; then
    echo -e "${RED}❌ KEY_ID no puede estar vacío${NC}"
    exit 1
fi

# Verificar que la clave existe
if ! gpg --list-secret-keys "$KEY_ID" &> /dev/null; then
    echo -e "${RED}❌ La clave $KEY_ID no existe${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Clave $KEY_ID verificada${NC}"
echo ""

# Obtener passphrase
echo -e "${GREEN}═══ PASO 2: Contraseña de la clave GPG ═══${NC}"
echo ""
read -sp "Ingresa la contraseña de tu clave GPG: " GPG_PASSPHRASE
echo ""

if [ -z "$GPG_PASSPHRASE" ]; then
    echo -e "${YELLOW}⚠️  Advertencia: La contraseña está vacía${NC}"
fi

echo -e "${GREEN}✓ Contraseña guardada${NC}"
echo ""

# Exportar claves
echo -e "${GREEN}═══ PASO 3: Exportar claves ═══${NC}"
echo ""

mkdir -p .github/secrets
chmod 700 .github/secrets

echo "Exportando clave privada..."
gpg --armor --export-secret-keys "$KEY_ID" > .github/secrets/private-key.asc

echo "Exportando clave pública..."
gpg --armor --export "$KEY_ID" > .github/secrets/public-key.asc

echo -e "${GREEN}✓ Claves exportadas a .github/secrets/${NC}"
echo ""

# Información de PPA
echo -e "${GREEN}═══ PASO 4: Configuración de PPA ═══${NC}"
echo ""
echo "Para configurar tu PPA en Launchpad:"
echo ""
echo "1. Ve a: https://launchpad.net/"
echo "2. Crea una cuenta o inicia sesión"
echo "3. Registra tu clave GPG:"
echo "   → https://launchpad.net/~tu-usuario/+editpgpkeys"
echo "   → Pega el contenido de: .github/secrets/public-key.asc"
echo ""
echo "4. Sube la clave al keyserver:"
echo -e "${YELLOW}   gpg --keyserver keyserver.ubuntu.com --send-keys $KEY_ID${NC}"
echo ""
echo "5. Crea tu PPA:"
echo "   → https://launchpad.net/~tu-usuario/+activate-ppa"
echo ""

read -p "¿Ya configuraste tu PPA? (s/n): " PPA_READY

if [[ $PPA_READY == "s" || $PPA_READY == "S" ]]; then
    read -p "Ingresa el nombre de tu PPA (ej: ppa:usuario/squidstats): " PPA_NAME
    
    if [[ ! $PPA_NAME =~ ^ppa:.+/.+ ]]; then
        echo -e "${YELLOW}⚠️  Advertencia: El formato debería ser ppa:usuario/nombre${NC}"
    fi
else
    echo -e "${YELLOW}Continúa sin PPA (podrás configurarlo después)${NC}"
    PPA_NAME="ppa:usuario/squidstats"
fi

echo ""

# Crear archivo de secrets
echo -e "${GREEN}═══ PASO 5: Generar archivo de secrets ═══${NC}"
echo ""

cat > .github/secrets/secrets.env << EOF
# GitHub Secrets para PPA Workflow
# Generado: $(date)

GPG_KEY_ID=$KEY_ID
GPG_PASSPHRASE=$GPG_PASSPHRASE
PPA_NAME=$PPA_NAME

# Nota: GPG_PRIVATE_KEY está en private-key.asc
EOF

chmod 600 .github/secrets/secrets.env

echo -e "${GREEN}✓ Archivo de secrets creado: .github/secrets/secrets.env${NC}"
echo ""

# Mostrar resumen
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  RESUMEN DE CONFIGURACIÓN${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}GPG_KEY_ID:${NC} $KEY_ID"
echo -e "${GREEN}GPG_PASSPHRASE:${NC} [Guardada en secrets.env]"
echo -e "${GREEN}PPA_NAME:${NC} $PPA_NAME"
echo -e "${GREEN}GPG_PRIVATE_KEY:${NC} En .github/secrets/private-key.asc"
echo -e "${GREEN}GPG_PUBLIC_KEY:${NC} En .github/secrets/public-key.asc"
echo ""

# Opción de configurar en GitHub
if [ "$GH_AVAILABLE" = true ]; then
    echo -e "${GREEN}═══ PASO 6: Configurar en GitHub (Opcional) ═══${NC}"
    echo ""
    read -p "¿Deseas configurar los secrets en GitHub ahora? (s/n): " SETUP_GH
    
    if [[ $SETUP_GH == "s" || $SETUP_GH == "S" ]]; then
        echo ""
        echo "Configurando secrets en GitHub..."
        
        gh secret set GPG_KEY_ID -b"$KEY_ID"
        gh secret set GPG_PASSPHRASE -b"$GPG_PASSPHRASE"
        gh secret set PPA_NAME -b"$PPA_NAME"
        gh secret set GPG_PRIVATE_KEY < .github/secrets/private-key.asc
        
        echo -e "${GREEN}✓ Secrets configurados en GitHub${NC}"
    else
        echo ""
        echo "Para configurar manualmente en GitHub:"
        echo "1. Ve a: https://github.com/kaelthasmanu/SquidStats/settings/secrets/actions"
        echo "2. Crea los siguientes secrets:"
        echo ""
        echo "   GPG_KEY_ID:"
        echo "   → Valor: $KEY_ID"
        echo ""
        echo "   GPG_PASSPHRASE:"
        echo "   → Copiar de: .github/secrets/secrets.env"
        echo ""
        echo "   PPA_NAME:"
        echo "   → Valor: $PPA_NAME"
        echo ""
        echo "   GPG_PRIVATE_KEY:"
        echo "   → Copiar contenido completo de: .github/secrets/private-key.asc"
    fi
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Configuración completada!${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}IMPORTANTE:${NC}"
echo "• Los archivos en .github/secrets/ contienen información sensible"
echo "• NO los subas a Git (ya están en .gitignore)"
echo "• Guárdalos en un lugar seguro como respaldo"
echo ""
echo -e "${GREEN}Próximo paso:${NC}"
echo "Probar el workflow en GitHub con:"
echo ""
echo "  git checkout -b test/ppa-workflow"
echo "  git add .github/workflows/"
echo "  git commit -m 'feat: add PPA workflow'"
echo "  git push origin test/ppa-workflow"
echo "  git tag v0.0.1-test"
echo "  git push origin v0.0.1-test"
echo ""
