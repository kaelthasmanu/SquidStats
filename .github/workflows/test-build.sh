#!/bin/bash
# Script para probar el workflow localmente y extraer el .deb

set -e

echo "🔨 Iniciando build del paquete con act..."
echo ""

# Limpiar builds anteriores
rm -f *.deb *.changes *.buildinfo 2>/dev/null || true

# Ejecutar act (ignorar error de upload artifacts que es normal)
act -j build-deb --artifact-server-path /tmp/artifacts 2>&1 | tee /tmp/act-output.log || true

# Verificar si el build fue exitoso
if grep -q "Success - Main Build Debian package" /tmp/act-output.log; then
    echo ""
    echo "✅ Build completado exitosamente!"
    echo ""
    
    # Buscar el contenedor de act
    CONTAINER=$(docker ps -a --filter "ancestor=catthehacker/ubuntu:act-22.04" --format "{{.ID}}" | head -1)
    
    if [ -n "$CONTAINER" ]; then
        echo "📦 Copiando archivos .deb del contenedor..."
        
        # Copiar archivos
        docker cp $CONTAINER:/Users/manuel/Desktop/Projects/codeSquidStats/SquidStats/squidstats_2.1-1_all.deb . 2>/dev/null || \
        docker cp $CONTAINER:/github/workspace/squidstats_2.1-1_all.deb . 2>/dev/null || \
        echo "⚠️  No se pudo copiar automáticamente. El .deb está dentro del contenedor."
        
        if [ -f "squidstats_2.1-1_all.deb" ]; then
            echo ""
            echo "🎉 ¡Paquete extraído exitosamente!"
            echo ""
            ls -lh squidstats_*.deb
            echo ""
            echo "📋 Información del paquete:"
            dpkg-deb --info squidstats_2.1-1_all.deb
            echo ""
            echo "📄 Contenido del paquete:"
            dpkg-deb --contents squidstats_2.1-1_all.deb | head -30
        fi
    else
        echo "⚠️  Contenedor no encontrado. Verifica manualmente con: docker ps -a"
    fi
else
    echo ""
    echo "❌ Build falló. Revisa el log en /tmp/act-output.log"
    echo ""
    grep -A 5 "Failure" /tmp/act-output.log | tail -10
    exit 1
fi

echo ""
echo "✅ Testing completado!"
echo ""
echo "Siguiente paso: Subir a GitHub y probar con un tag real"
echo "  git checkout -b test/ppa-workflow"
echo "  git add .github/"
echo "  git commit -m 'test: add PPA workflow'"
echo "  git push origin test/ppa-workflow"
echo "  git tag v0.0.1-test"
echo "  git push origin v0.0.1-test"
