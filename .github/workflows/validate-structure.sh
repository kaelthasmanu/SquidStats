#!/bin/bash
set -e

echo "=== 🔍 Validando estructura del proyecto para empaquetado ==="
echo ""

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Contador de errores
ERRORS=0

# Verificar archivos necesarios
echo "📁 Verificando archivos principales..."
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
        echo -e "${GREEN}✓${NC} $file"
    else
        echo -e "${RED}✗${NC} $file NO ENCONTRADO"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "📦 Verificando directorios..."
DIRS=(
    "static"
    "templates"
    "utils"
)

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo -e "${GREEN}✓${NC} $dir/"
    else
        echo -e "${RED}✗${NC} $dir/ NO ENCONTRADO"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "🐍 Validando sintaxis Python..."
PYTHON_FILES=("app.py" "config.py")
for file in "${PYTHON_FILES[@]}"; do
    if python3 -m py_compile "$file" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $file - sintaxis correcta"
    else
        echo -e "${RED}✗${NC} $file - error de sintaxis"
        ERRORS=$((ERRORS + 1))
    fi
done

echo ""
echo "📋 Validando requirements.txt..."
if [ -f "requirements.txt" ]; then
    DEPS=$(wc -l < requirements.txt)
    echo -e "${GREEN}✓${NC} $DEPS dependencias encontradas"
    echo ""
    echo "Dependencias principales:"
    grep -E "^(Flask|SQLAlchemy|psutil)" requirements.txt || echo "  (ninguna)"
else
    echo -e "${RED}✗${NC} requirements.txt no encontrado"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "🔧 Verificando workflow de GitHub Actions..."
if [ -f ".github/workflows/create-ppa.yml" ]; then
    echo -e "${GREEN}✓${NC} Workflow encontrado"
    
    # Verificar sintaxis YAML si yamllint está instalado
    if command -v yamllint &> /dev/null; then
        if yamllint -d relaxed .github/workflows/create-ppa.yml 2>/dev/null; then
            echo -e "${GREEN}✓${NC} Sintaxis YAML válida"
        else
            echo -e "${YELLOW}⚠${NC} Advertencias de sintaxis YAML (revisar manualmente)"
        fi
    else
        echo -e "${YELLOW}⚠${NC} yamllint no instalado (instalar con: pip3 install yamllint)"
    fi
else
    echo -e "${RED}✗${NC} Workflow no encontrado"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "📝 Simulando creación de estructura Debian..."
TEMP_DIR=$(mktemp -d)
mkdir -p "$TEMP_DIR/debian"
mkdir -p "$TEMP_DIR/debian/source"

# Simular archivos debian
cat > "$TEMP_DIR/debian/control" << EOF
Source: squidstats
Section: web
Priority: optional
Maintainer: Test <test@test.com>

Package: squidstats
Architecture: all
Description: Test package
 Test description
EOF

cat > "$TEMP_DIR/debian/rules" << 'EOF'
#!/usr/bin/make -f
%:
	dh $@
EOF

chmod +x "$TEMP_DIR/debian/rules"

if [ -f "$TEMP_DIR/debian/control" ] && [ -x "$TEMP_DIR/debian/rules" ]; then
    echo -e "${GREEN}✓${NC} Estructura Debian básica creada correctamente"
else
    echo -e "${RED}✗${NC} Error creando estructura Debian"
    ERRORS=$((ERRORS + 1))
fi

rm -rf "$TEMP_DIR"

echo ""
echo "================================================"
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ Validación completada sin errores${NC}"
    echo ""
    echo "Siguiente paso: Probar con act o Docker"
    echo "  → act -j build-deb --secret-file .github/workflows/.secrets"
    exit 0
else
    echo -e "${RED}❌ Se encontraron $ERRORS errores${NC}"
    echo ""
    echo "Por favor, corrige los errores antes de continuar"
    exit 1
fi
