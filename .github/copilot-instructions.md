# Copilot instructions for SquidStats

Este repositorio es una aplicación Flask para análisis y monitorización de logs de Squid. Sigue las reglas del proyecto y no improvises cambios fuera de la arquitectura actual.

## Reglas obligatorias

- No ejecutar ni crear tests salvo que el usuario lo solicite explícitamente.
- No añadir tests como parte de la corrección por defecto.
- No hacer refactors grandes ni renombrados masivos sin necesidad.
- Respetar la separación de responsabilidades: rutas, servicios, base de datos, parsers, utilidades y vistas.
- Mantener la lógica de negocio en `services/` y no en `routes/`.
- Mantener la app Flask y el registro de blueprints en `app.py` y `routes/__init__.py`.
- Revisar modelos y migraciones antes de tocar la base de datos.
- Mantener compatibilidad con la configuración central (`config.py`), variables de entorno y seguimientos de logs.
- No introducir secretos, URLs hardcodeadas ni configuración local en código.
- Mantener la seguridad actual: autenticación, CSRF, sesiones y validación de entrada.
- Si se toca el frontend, respetar el estilo de `templates/` y `static/` y no romper la UI existente.
- Si se modifica texto visible o templates, mantener la internacionalización con Flask-Babel (`translations/`, `flask_babel`): no hardcodear cadenas de UI sin rutinas de traducción y revisar el patrón existente antes de cambiar texto visible.
- Mantener comentarios, nombres de variables, funciones y mensajes técnicos en inglés salvo que el usuario exija otra cosa explícitamente.

## Arquitectura esperada

- `routes/`: endpoints HTTP y blueprints.
- `services/`: lógica de negocio por dominio.
- `database/`: acceso a datos, modelos y migraciones.
- `parsers/`: lógica de parseo de logs.
- `templates/` y `static/`: presentación.
- `utils/`: helpers transversales.
- `app.py`: arranque y configuración global.

## Workflow sugerido

1. Analizar el issue o el bug y localizar el módulo real.
2. Leer el archivo y patrones similares antes de editar.
3. Hacer una corrección mínima y específica.
4. Verificar sintaxis o importabilidad si es necesario, pero sin correr la suite completa sin pedirlo.
5. Informar de los cambios y si hay dependencias o riesgos de migración.

## Qué evitar

- Cambios de arquitectura improvisados.
- Lógica de negocio mezclada en vistas o rutas.
- SQL directo o accesos a DB en componentes de presentación.
- Logging excesivo o depuración que no se quede en producción.
- Hardcodear valores del entorno o configuración local.
- Cambios visuales no relacionados con el problema.

## Estilo de trabajo

Actúa como un agente conservador, de bajo riesgo y alineado con el diseño actual del proyecto. Prioriza correcciones estables, legibles y consistentes sobre soluciones "elegantes" que rompan la estructura del código.
