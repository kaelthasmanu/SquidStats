#!/usr/bin/env python3
"""
Pruebas unitarias para el sistema de notificaciones
"""

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.database import Notification, get_session
from services.notifications import (
    _check_duplicate_notification,
    _generate_message_hash,
    _get_unread_count,
    add_notification,
    delete_all_notifications,
    delete_notification,
    get_all_notifications,
    mark_notifications_read,
)


class TestNotificationsDatabase(unittest.TestCase):
    """Pruebas para el sistema de notificaciones en la base de datos"""

    @classmethod
    def setUpClass(cls):
        """Configuración inicial para todas las pruebas"""
        # Asegurar que usamos una base de datos de prueba
        os.environ["DATABASE_STRING_CONNECTION"] = "test_notifications.db"

    def setUp(self):
        """Configuración antes de cada prueba"""
        # Limpiar todas las notificaciones antes de cada prueba
        delete_all_notifications()

    def tearDown(self):
        """Limpieza después de cada prueba"""
        # Limpiar todas las notificaciones después de cada prueba
        delete_all_notifications()

    @classmethod
    def tearDownClass(cls):
        """Limpieza final después de todas las pruebas"""
        # Eliminar el archivo de base de datos de prueba si existe
        db_file = "test_notifications.db"
        if os.path.exists(db_file):
            os.remove(db_file)

    def test_generate_message_hash(self):
        """Prueba la generación de hash para mensajes"""
        message = "Test notification"
        source = "test"
        notification_type = "info"

        hash1 = _generate_message_hash(message, source, notification_type)
        hash2 = _generate_message_hash(message, source, notification_type)

        # Los hashes deben ser idénticos para el mismo contenido
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA256 produce 64 caracteres hex

        # Hash diferente para mensaje diferente
        hash3 = _generate_message_hash("Different message", source, notification_type)
        self.assertNotEqual(hash1, hash3)

    def test_add_notification(self):
        """Prueba agregar una notificación simple"""
        result = add_notification(
            notification_type="info",
            message="Test notification",
            icon="fa-test",
            source="test",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "info")
        self.assertEqual(result["message"], "Test notification")
        self.assertEqual(result["icon"], "fa-test")
        self.assertEqual(result["source"], "test")
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["read"])

    def test_add_notification_deduplication(self):
        """Prueba la deduplicación de notificaciones"""
        # Agregar la misma notificación 3 veces
        result1 = add_notification(
            notification_type="warning",
            message="Duplicate test",
            source="test",
            deduplicate_hours=1,
        )

        result2 = add_notification(
            notification_type="warning",
            message="Duplicate test",
            source="test",
            deduplicate_hours=1,
        )

        result3 = add_notification(
            notification_type="warning",
            message="Duplicate test",
            source="test",
            deduplicate_hours=1,
        )

        # Debe haber solo 1 registro en la BD
        all_notifs = get_all_notifications()
        self.assertEqual(len(all_notifs["notifications"]), 1)

        # El count debe ser 3
        self.assertEqual(result3["count"], 3)

        # Los IDs deben ser el mismo
        self.assertEqual(result1["id"], result2["id"])
        self.assertEqual(result2["id"], result3["id"])

    def test_add_notification_different_types_no_duplicate(self):
        """Prueba que notificaciones con diferentes tipos no se deduplican"""
        result1 = add_notification(
            notification_type="info",
            message="Same message",
            source="test",
        )

        result2 = add_notification(
            notification_type="warning",
            message="Same message",
            source="test",
        )

        # Deben ser diferentes IDs
        self.assertNotEqual(result1["id"], result2["id"])

        # Debe haber 2 registros
        all_notifs = get_all_notifications()
        self.assertEqual(len(all_notifs["notifications"]), 2)

    def test_add_notification_different_sources_no_duplicate(self):
        """Prueba que notificaciones con diferentes fuentes no se deduplican"""
        result1 = add_notification(
            notification_type="info",
            message="Same message",
            source="system",
        )

        result2 = add_notification(
            notification_type="info",
            message="Same message",
            source="squid",
        )

        # Deben ser diferentes IDs
        self.assertNotEqual(result1["id"], result2["id"])

        # Debe haber 2 registros
        all_notifs = get_all_notifications()
        self.assertEqual(len(all_notifs["notifications"]), 2)

    def test_get_all_notifications(self):
        """Prueba obtener todas las notificaciones"""
        # Agregar varias notificaciones
        add_notification("info", "Test 1", source="test")
        add_notification("warning", "Test 2", source="test")
        add_notification("error", "Test 3", source="test")

        result = get_all_notifications()

        self.assertEqual(len(result["notifications"]), 3)
        self.assertEqual(result["unread_count"], 3)
        self.assertIn("pagination", result)

    def test_get_all_notifications_pagination(self):
        """Prueba la paginación de notificaciones"""
        # Agregar 25 notificaciones
        for i in range(25):
            add_notification("info", f"Test {i}", source="test")

        # Primera página (20 por página por defecto)
        page1 = get_all_notifications(page=1, per_page=10)
        self.assertEqual(len(page1["notifications"]), 10)
        self.assertEqual(page1["pagination"]["current_page"], 1)
        self.assertEqual(page1["pagination"]["total_pages"], 3)
        self.assertTrue(page1["pagination"]["has_next"])
        self.assertFalse(page1["pagination"]["has_prev"])

        # Segunda página
        page2 = get_all_notifications(page=2, per_page=10)
        self.assertEqual(len(page2["notifications"]), 10)
        self.assertTrue(page2["pagination"]["has_next"])
        self.assertTrue(page2["pagination"]["has_prev"])

        # Tercera página
        page3 = get_all_notifications(page=3, per_page=10)
        self.assertEqual(len(page3["notifications"]), 5)
        self.assertFalse(page3["pagination"]["has_next"])
        self.assertTrue(page3["pagination"]["has_prev"])

    def test_mark_notifications_read(self):
        """Prueba marcar notificaciones como leídas"""
        # Agregar notificaciones
        n1 = add_notification("info", "Test 1", source="test")
        n2 = add_notification("info", "Test 2", source="test")

        # Verificar que todas están sin leer
        result = get_all_notifications()
        self.assertEqual(result["unread_count"], 2)

        # Marcar 2 como leídas
        marked = mark_notifications_read([n1["id"], n2["id"]])
        self.assertEqual(marked, 2)

        # Verificar contador
        result = get_all_notifications()
        self.assertEqual(result["unread_count"], 1)

    def test_delete_notification(self):
        """Prueba eliminar una notificación específica"""
        # Agregar notificaciones
        n1 = add_notification("info", "Test 1", source="test")
        add_notification("info", "Test 2", source="test")

        # Eliminar una
        deleted = delete_notification(n1["id"])
        self.assertTrue(deleted)

        # Verificar que solo queda 1
        result = get_all_notifications()
        self.assertEqual(len(result["notifications"]), 1)

        # Intentar eliminar una que no existe
        deleted = delete_notification(99999)
        self.assertFalse(deleted)

    def test_delete_all_notifications(self):
        """Prueba eliminar todas las notificaciones"""
        # Agregar varias notificaciones
        add_notification("info", "Test 1", source="test")
        add_notification("info", "Test 2", source="test")
        add_notification("info", "Test 3", source="test")

        # Verificar que hay 3
        result = get_all_notifications()
        self.assertEqual(len(result["notifications"]), 3)

        # Eliminar todas
        deleted = delete_all_notifications()
        self.assertEqual(deleted, 3)

        # Verificar que no hay ninguna
        result = get_all_notifications()
        self.assertEqual(len(result["notifications"]), 0)

    def test_check_duplicate_notification(self):
        """Prueba la función de verificación de duplicados"""
        db = get_session()
        try:
            message = "Test duplicate check"
            message_hash = _generate_message_hash(message, "test", "info")

            # No debe haber duplicados inicialmente
            duplicate = _check_duplicate_notification(db, message_hash, hours=1)
            self.assertIsNone(duplicate)

            # Agregar una notificación
            notification = Notification(
                type="info",
                message=message,
                message_hash=message_hash,
                icon="fa-test",
                source="test",
                read=0,
                count=1,
                created_at=datetime.now(),
            )
            db.add(notification)
            db.commit()

            # Ahora debe encontrar el duplicado
            duplicate = _check_duplicate_notification(db, message_hash, hours=1)
            self.assertIsNotNone(duplicate)
            self.assertEqual(duplicate.message, message)

        finally:
            db.close()

    def test_check_duplicate_notification_expired(self):
        """Prueba que no se encuentren duplicados fuera del rango de tiempo"""
        db = get_session()
        try:
            message = "Old notification"
            message_hash = _generate_message_hash(message, "test", "info")

            # Agregar una notificación antigua (más de 24 horas)
            old_notification = Notification(
                type="info",
                message=message,
                message_hash=message_hash,
                icon="fa-test",
                source="test",
                read=0,
                count=1,
                created_at=datetime.now() - timedelta(hours=25),
            )
            db.add(old_notification)
            db.commit()

            # No debe encontrar duplicados en las últimas 24 horas
            duplicate = _check_duplicate_notification(db, message_hash, hours=24)
            self.assertIsNone(duplicate)

            # Pero sí debe encontrarlo en las últimas 48 horas
            duplicate = _check_duplicate_notification(db, message_hash, hours=48)
            self.assertIsNotNone(duplicate)

        finally:
            db.close()

    def test_get_unread_count(self):
        """Prueba obtener el contador de notificaciones sin leer"""
        db = get_session()
        try:
            # Inicialmente debe ser 0
            count = _get_unread_count(db)
            self.assertEqual(count, 0)

            # Agregar notificaciones sin leer
            for i in range(5):
                notification = Notification(
                    type="info",
                    message=f"Test {i}",
                    message_hash=_generate_message_hash(f"Test {i}", "test", "info"),
                    icon="fa-test",
                    source="test",
                    read=0,
                    count=1,
                    created_at=datetime.now(),
                )
                db.add(notification)
            db.commit()

            # Debe haber 5 sin leer
            count = _get_unread_count(db)
            self.assertEqual(count, 5)

            # Marcar 2 como leídas
            db.query(Notification).filter(
                Notification.message.in_(["Test 0", "Test 1"])
            ).update({"read": 1}, synchronize_session=False)
            db.commit()

            # Debe haber 3 sin leer
            count = _get_unread_count(db)
            self.assertEqual(count, 3)

        finally:
            db.close()

    def test_notification_ordering(self):
        """Prueba que las notificaciones se ordenen por fecha de creación descendente"""
        # Agregar notificaciones con pequeños retrasos
        add_notification("info", "First", source="test")
        add_notification("info", "Second", source="test")
        add_notification("info", "Third", source="test")

        result = get_all_notifications()
        notifications = result["notifications"]

        # La más reciente debe ser "Third"
        self.assertEqual(notifications[0]["message"], "Third")
        self.assertEqual(notifications[1]["message"], "Second")
        self.assertEqual(notifications[2]["message"], "First")

    def test_notification_sources(self):
        """Prueba diferentes fuentes de notificaciones"""
        sources = ["system", "squid", "security", "users", "git"]

        for source in sources:
            add_notification("info", f"Test from {source}", source=source)

        result = get_all_notifications()
        self.assertEqual(len(result["notifications"]), len(sources))

        # Verificar que todas las fuentes están presentes
        notification_sources = [n["source"] for n in result["notifications"]]
        for source in sources:
            self.assertIn(source, notification_sources)

    def test_notification_types(self):
        """Prueba diferentes tipos de notificaciones"""
        types = ["info", "warning", "error", "success"]

        for ntype in types:
            add_notification(ntype, f"Test {ntype}", source="test")

        result = get_all_notifications()
        self.assertEqual(len(result["notifications"]), len(types))

        # Verificar que todos los tipos están presentes
        notification_types = [n["type"] for n in result["notifications"]]
        for ntype in types:
            self.assertIn(ntype, notification_types)

    @patch("services.notifications.socketio")
    def test_socketio_emission_new_notification(self, mock_socketio):
        """Prueba que se emita evento de Socket.IO para nueva notificación"""
        add_notification("info", "Test socketio", source="test")

        # Debe haber emitido el evento
        mock_socketio.emit.assert_called_once()
        args = mock_socketio.emit.call_args

        self.assertEqual(args[0][0], "new_notification")
        self.assertIn("notification", args[0][1])
        self.assertIn("unread_count", args[0][1])

    @patch("services.notifications.socketio")
    def test_socketio_emission_updated_notification(self, mock_socketio):
        """Prueba que se emita evento de Socket.IO para notificación actualizada"""
        # Primera notificación
        add_notification("info", "Test update", source="test")
        mock_socketio.reset_mock()

        # Duplicado (debe actualizar)
        add_notification("info", "Test update", source="test")

        # Debe haber emitido evento de actualización
        mock_socketio.emit.assert_called_once()
        args = mock_socketio.emit.call_args

        self.assertEqual(args[0][0], "notification_updated")
        self.assertIn("notification", args[0][1])
        self.assertIn("unread_count", args[0][1])


class TestNotificationHelpers(unittest.TestCase):
    """Pruebas para funciones auxiliares de notificaciones"""

    def test_default_icon_assignment(self):
        """Prueba que se asignen iconos por defecto según el tipo"""
        from services.notifications import get_default_icon

        self.assertEqual(get_default_icon("info"), "fa-info-circle")
        self.assertEqual(get_default_icon("warning"), "fa-exclamation-triangle")
        self.assertEqual(get_default_icon("error"), "fa-times-circle")
        self.assertEqual(get_default_icon("success"), "fa-check-circle")
        self.assertEqual(get_default_icon("unknown"), "fa-bell")


if __name__ == "__main__":
    unittest.main(verbosity=2)
