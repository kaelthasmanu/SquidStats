#!/usr/bin/env python3
"""
Script de prueba para el sistema de notificaciones con deduplicación
"""

from database.database import Notification, get_session
from services.notifications import add_notification, get_all_notifications


def test_deduplication():
    print("=" * 60)
    print("TEST DE DEDUPLICACIÓN DE NOTIFICACIONES")
    print("=" * 60)

    # Limpiar notificaciones de prueba anteriores
    db = get_session()
    db.query(Notification).filter(
        Notification.message.like("Prueba de deduplicación%")
    ).delete()
    db.commit()
    db.close()

    print("\n1. Agregando la misma notificación 3 veces...")

    # Agregar la misma notificación 3 veces
    results = []
    for i in range(3):
        result = add_notification(
            notification_type="info",
            message="Prueba de deduplicación de notificaciones",
            source="system",
            deduplicate_hours=1,
        )
        if result:
            results.append(result)
            print(
                f"   {i + 1}. Notificación procesada - count: {result['count']}, id: {result['id']}"
            )

    # Verificar que solo hay 1 notificación con count=3
    db = get_session()
    notifications = (
        db.query(Notification)
        .filter(Notification.message.like("Prueba de deduplicación%"))
        .all()
    )

    print("\n2. Verificación:")
    print(f"   Total de registros en BD: {len(notifications)}")

    if len(notifications) == 1:
        notif = notifications[0]
        print("   ✓ Deduplicación funcionando correctamente")
        print(f"   ✓ ID: {notif.id}")
        print(f"   ✓ Contador de repeticiones: {notif.count}")
        print(f"   ✓ Mensaje: {notif.message}")
        print(f"   ✓ Hash: {notif.message_hash[:16]}...")
    else:
        print(
            f"   ✗ Error: se crearon {len(notifications)} notificaciones en lugar de 1"
        )

    db.close()

    # Limpiar
    db = get_session()
    db.query(Notification).filter(
        Notification.message.like("Prueba de deduplicación%")
    ).delete()
    db.commit()
    db.close()

    print("\n3. ✓ Notificaciones de prueba eliminadas")
    print("=" * 60)


def test_pagination():
    print("\n" + "=" * 60)
    print("TEST DE PAGINACIÓN")
    print("=" * 60)

    # Obtener notificaciones con paginación
    result = get_all_notifications(page=1, per_page=5)

    print("\n1. Página 1 (5 por página):")
    print(f"   Total de notificaciones: {result['pagination']['total_notifications']}")
    print(f"   Total de páginas: {result['pagination']['total_pages']}")
    print(f"   Notificaciones no leídas: {result['unread_count']}")
    print(f"   Notificaciones en esta página: {len(result['notifications'])}")

    if result["notifications"]:
        print("\n2. Primeras notificaciones:")
        for i, notif in enumerate(result["notifications"][:3], 1):
            print(f"   {i}. [{notif['type']}] {notif['message'][:50]}...")
            print(
                f"      Fuente: {notif['source']}, Count: {notif['count']}, Leída: {notif['read']}"
            )

    print("=" * 60)


if __name__ == "__main__":
    test_deduplication()
    test_pagination()
    print("\n✓ Todas las pruebas completadas\n")
