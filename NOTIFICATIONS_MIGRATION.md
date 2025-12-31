# Sistema de Notificaciones - Migración a Base de Datos

## ✅ Implementación Completada

El sistema de notificaciones ha sido migrado exitosamente de almacenamiento en memoria a base de datos.

## 🎯 Características Implementadas

### 1. **Persistencia Automática**
- La tabla `notifications` se crea automáticamente al iniciar la aplicación
- Integrada en la función `migrate_database()` existente
- No requiere scripts de migración manual

### 2. **Deduplicación Inteligente**
```python
# Ejemplo: Esta notificación no se duplicará si ocurre dentro de 1 hora
add_notification(
    notification_type='warning',
    message='Espacio en disco bajo: 2.5GB libres',
    source='system',
    deduplicate_hours=1  # Ventana de deduplicación
)
```

**Funcionamiento:**
- Se genera un hash SHA256 del mensaje + tipo + fuente
- Si existe una notificación idéntica en la ventana de tiempo:
  - ✅ NO se crea una nueva entrada
  - ✅ Se incrementa el contador `count`
  - ✅ Se actualiza `updated_at`
  - ✅ Se marca como no leída nuevamente

**Pruebas realizadas:**
```
1. Agregando la misma notificación 3 veces...
   1. Notificación procesada - count: 1, id: 16
   2. Notificación procesada - count: 2, id: 16  ← Mismo ID
   3. Notificación procesada - count: 3, id: 16  ← Mismo ID

2. Verificación:
   ✓ Total de registros en BD: 1
   ✓ Contador de repeticiones: 3
```

### 3. **Limpieza Automática**
- Se mantienen solo las 100 notificaciones más recientes
- Limpieza automática al crear nuevas notificaciones
- Previene crecimiento infinito de la base de datos

### 4. **Estructura de la Tabla**

```sql
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type VARCHAR(50) NOT NULL,         -- 'info', 'warning', 'error', 'success'
    message TEXT NOT NULL,
    message_hash VARCHAR(64) NOT NULL, -- SHA256 para deduplicación
    icon VARCHAR(100),
    source VARCHAR(50) NOT NULL,       -- 'squid', 'system', 'security', etc.
    read INTEGER DEFAULT 0,            -- 0=no leída, 1=leída
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    expires_at DATETIME,
    count INTEGER DEFAULT 1            -- Contador de repeticiones
);

-- Índices para optimización
CREATE INDEX idx_message_hash ON notifications(message_hash);
CREATE INDEX idx_source ON notifications(source);
CREATE INDEX idx_created_at ON notifications(created_at);
```

### 5. **API Actualizada**

#### Obtener Notificaciones (con paginación)
```bash
GET /api/notifications?page=1&per_page=20
```

Respuesta:
```json
{
  "unread_count": 15,
  "notifications": [...],
  "pagination": {
    "current_page": 1,
    "per_page": 20,
    "total_pages": 3,
    "total_notifications": 50,
    "has_prev": false,
    "has_next": true
  }
}
```

#### Marcar como Leídas
```bash
POST /api/notifications/mark-read
Content-Type: application/json

{
  "notification_ids": [1, 2, 3]
}
```

#### Eliminar Notificación Individual
```bash
DELETE /api/notifications/16
```

#### Eliminar Todas las Notificaciones
```bash
DELETE /api/notifications/delete-all
```

## 📊 Resultados de las Pruebas

### Test de Deduplicación
```
✓ Deduplicación funcionando correctamente
✓ 3 intentos de crear la misma notificación
✓ Solo 1 registro creado en BD
✓ Contador incrementado correctamente (count: 3)
```

### Test de Paginación
```
✓ Total de notificaciones: 15
✓ Total de páginas: 3 (5 por página)
✓ Notificaciones no leídas: 15
✓ Consultas optimizadas con índices
```

### Test de Persistencia
```
✓ Notificaciones sobreviven reinicios del servidor
✓ Datos consistentes entre sesiones
✓ Contadores preservados correctamente
```

## 🚀 Ventajas del Nuevo Sistema

### Antes (En Memoria)
- ❌ Se perdían al reiniciar el servidor
- ❌ Notificaciones duplicadas constantes
- ❌ No había límite de almacenamiento
- ❌ Sin historial persistente

### Ahora (Base de Datos)
- ✅ Persistencia completa
- ✅ Deduplicación inteligente
- ✅ Limpieza automática
- ✅ Historial completo disponible
- ✅ Contador de repeticiones
- ✅ Optimización con índices
- ✅ Paginación eficiente
- ✅ Compatible con SQLite, MySQL, PostgreSQL

## 🔧 Configuración de Deduplicación

```python
# Diferentes ventanas de tiempo según el caso

# 30 minutos para eventos frecuentes
add_notification(
    message="Log procesado",
    deduplicate_hours=0.5
)

# 1 hora (por defecto)
add_notification(
    message="Usuario conectado",
    deduplicate_hours=1
)

# 24 horas para eventos diarios
add_notification(
    message="Backup completado",
    deduplicate_hours=24
)

# Sin deduplicación
add_notification(
    message="Evento único",
    deduplicate_hours=0
)
```

## 📝 Mensajes en Español

Todos los mensajes visibles al usuario están en español:
- "El servicio Squid no está ejecutándose"
- "Espacio en disco crítico: 0.8GB libres"
- "Actividad sospechosa desde IP 192.168.1.100: 250 solicitudes/hora"
- "El usuario juan consumió 1500MB en 24h"
- etc.

## 🔄 Compatibilidad

✅ Mantiene compatibilidad con código existente
✅ Funciones antiguas siguen funcionando
✅ Socket.IO sigue emitiendo eventos en tiempo real
✅ Migración transparente y automática
✅ No requiere cambios en el frontend

## 📋 Archivos Modificados

1. **database/database.py**
   - Añadido modelo `Notification`
   - Integrado en `create_dynamic_tables()`

2. **services/notifications.py**
   - Reescrito para usar base de datos
   - Añadida lógica de deduplicación
   - Añadida limpieza automática
   - Funciones devuelven diccionarios en lugar de objetos

3. **routes/api_routes.py**
   - Añadido endpoint DELETE para notificación individual
   - Añadido endpoint DELETE para todas las notificaciones
   - Actualizado soporte de paginación

4. **migrations/create_notifications_table.py**
   - Script opcional (tabla se crea automáticamente)

5. **test_notifications.py**
   - Script de pruebas completo
   - Valida deduplicación y paginación

## ✨ Próximas Mejoras Posibles

- [ ] Filtros avanzados por tipo, fuente y rango de fechas
- [ ] Exportación de notificaciones a CSV/JSON
- [ ] Notificaciones programadas
- [ ] Webhooks para notificaciones críticas
- [ ] Dashboard de estadísticas
- [ ] Configuración de retención personalizada por fuente
