# AGENTS.md

Este repositorio es una aplicación Flask para monitoreo y análisis de logs de Squid llamada SquidStats. Los agentes de IA deben trabajar de forma conservadora, respetando la arquitectura existente y evitando cambios innecesarios.

## Principios generales

- No ejecutar, crear ni modificar tests salvo que el usuario lo pida explícitamente.
- No asumir que hay que añadir tests como parte de la corrección. En este proyecto, la prioridad es mantener la lógica y la arquitectura.
- Mantener cambios mínimos y enfocados en la causa real del problema.
- Respetar el estilo y patrón del proyecto antes de proponer refactors grandes.
- Preferir soluciones reutilizando servicios y utilidades ya existentes.
- No introducir dependencias nuevas salvo que sean estrictamente necesarias y estén justificadas.

## Arquitectura del proyecto

La estructura está dividida por capas y debe mantenerse así:

- `app.py`: factory de la app, configuración global, registro de blueprints y inicialización de servicios.
- `routes/`: blueprints de Flask. Aquí van las rutas y la entrada HTTP. Deben ser delgadas, sin lógica de negocio pesada.
- `services/`: lógica de negocio de cada dominio (auth, notifications, scheduler, quota, security, squid, system, etc.). Esta es la capa principal para funcionalidades.
- `database/`: modelos, acceso a datos y utilidades de base de datos.
- `parsers/`: parsing de logs y extracción de datos.
- `templates/` y `static/`: vista y assets frontend.
- `config.py`: configuración central.
- `utils/`: helpers reutilizables.

Reglas clave:

- Las rutas no deben contener lógica compleja de negocio.
- Los servicios deben encapsular la lógica y reutilización.
- Los cambios de esquema deben considerar migraciones y compatibilidad con Alembic.
- No mezclar responsabilidades entre capas.
- Si se añade una funcionalidad nueva, conviene integrarla en la capa adecuada y no improvisar lógica en vistas ni en rutas.

## Reglas de codificación

- Mantener nombres, estilo y estructura coherentes con los archivos del mismo módulo.
- Cargar configuraciones desde `config.py` y variables de entorno, no hardcodear valores de entorno ni secretos.
- Mantener seguridad: autenticación, CSRF, sesiones, validación de entrada y manejo de errores sin exponer detalles innecesarios.
- Respetar el sistema de logs actual (`loguru`) y no introducir logging ruidoso o redundante.
- Respetar la i18n del proyecto (`flask_babel`, `translations/`) si toca UI textual.
- Si se toca el frontend o plantillas (`templates/`, `static/`), mantener compatibilidad con Babel: no introducir texto visible hardcodeado sin marcarlo para traducción; revisar `translations/` y los patrones existentes antes de editar texto visible.
- Escribir comentarios, nombres de variables, funciones, mensajes de logs y textos técnicos en inglés salvo que el usuario exija otra cosa explícitamente. El proyecto debe mantener coherencia idiomática en el código.
- Si cambia comportamiento de configuración o arranque, revisar `app.py` y los servicios asociados antes de alterar más.

## Antes de editar

1. Leer el archivo exacto y el patrón de módulos similares antes de tocar el código.
2. Identificar si la corrección pertenece a `routes`, `services`, `database`, `parsers` o `utils`.
3. Hacer el cambio más pequeño posible.
4. Mantener compatibilidad con el resto de la aplicación.
5. Si hay que cambiar una estructura de datos, revisar si se necesita actualización de migraciones o modelos.

## Qué evitar

- Refactors grandes sin necesidad.
- Renombrar símbolos sin un motivo claro.
- Añadir lógica de negocio dentro de `routes`.
- Hacer llamadas directas a la base de datos desde vistas o controladores.
- Introducir SQL ad-hoc sin seguir el estilo del proyecto.
- Cambiar configuración global o startup de la app por comodidad.
- Añadir código temporal, debug o prints de diagnóstico en producción.
- Cambiar templates o estilos sin necesidad.

## Verificación permitida

- Si el usuario no pide tests, no ejecutar tests.
- La verificación recomendada es de tipo ligera y orientada a validar que el código sigue siendo importable o que el módulo no rompe la app.
- En general, preferir comprobaciones sintácticas o importaciones relevantes sobre ejecución de suites completas.

## Cuando se requiera una modificación estructural

- Hacerlo con la mínima superficie posible.
- Revisar si existe un patrón similar ya implementado en otros módulos.
- Integrar la solución con la capa adecuada y documentar el cambio si afecta arquitectura o despliegue.

## Instrucción final

Actúa como un agente cuidadoso para SquidStats: minimalista, respetuoso de la arquitectura, sin añadir tests por defecto y siempre priorizando la estabilidad del proyecto sobre la creatividad.
