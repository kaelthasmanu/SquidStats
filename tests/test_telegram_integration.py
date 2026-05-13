#!/usr/bin/env python3
"""
Integration tests for the Telegram notification service.
All configuration is read from the database via telegram_config_service.
Run: pytest tests/test_telegram_integration.py -v
"""

import asyncio
import sys
from pathlib import Path

import pytest

# Add the project root to path so imports work when executed directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from services.notifications.telegram_config_service import load_config  # noqa: E402
from services.notifications.telegram_integration import (  # noqa: E402
    initialize_telegram_service,
    send_security_alert_telegram,
    send_system_alert_telegram,
    send_telegram_notification,
    send_user_activity_alert_telegram,
    telegram_health_check,
)
from services.notifications.telegram_service import (  # noqa: E402
    NotificationPriority,
    get_telegram_service,
    parse_http_proxy_url,
)


def print_separator(title=""):
    """Imprimir separador visual"""
    print("\n" + "=" * 60)
    if title:
        print(f"  {title}")
        print("=" * 60)
    print()


def check_configuration():
    """Verify Telegram configuration from the database."""
    print_separator("Verificación de Configuración")

    cfg = load_config()

    print(f"TELEGRAM_ENABLED: {cfg['enabled']}")
    print(
        f"TELEGRAM_API_ID: {'✓ Configurado' if cfg.get('api_id') else '✗ No configurado'}"
    )
    print(
        f"TELEGRAM_API_HASH: {'✓ Configurado' if cfg.get('api_hash') else '✗ No configurado'}"
    )
    print(
        f"TELEGRAM_BOT_TOKEN: {'✓ Configurado' if cfg.get('bot_token') else '✗ No configurado'}"
    )
    print(
        f"TELEGRAM_PHONE: {'✓ Configurado' if cfg.get('phone') else '✗ No configurado'}"
    )
    print(f"TELEGRAM_SESSION_NAME: {cfg.get('session_name')}")
    recipients = cfg.get("recipients", [])
    print(f"TELEGRAM_RECIPIENTS: {recipients if recipients else '✗ No configurado'}")

    if not cfg["enabled"]:
        print(
            "\n⚠️ Telegram deshabilitado — actívalo desde Admin → Telegram Configuration"
        )
        return False

    if not cfg.get("api_id") or not cfg.get("api_hash"):
        print("\n❌ Faltan credenciales de API")
        print("   Obtén tus credenciales en: https://my.telegram.org/apps")
        return False

    if not cfg.get("bot_token") and not cfg.get("phone"):
        print("\n❌ Falta BOT_TOKEN o PHONE")
        print("   Configura bot_token o phone desde el panel de administración")
        return False

    if not cfg.get("recipients") or not any(r.strip() for r in cfg["recipients"]):
        print("\n❌ Faltan destinatarios")
        print("   Configura los destinatarios desde Admin → Telegram Configuration")
        return False

    print("\n✅ Configuración completa")
    return True


def _require_telegram_config():
    """Skip the test if Telegram is not configured in the DB."""
    cfg = load_config()
    if not cfg.get("enabled") or not cfg.get("api_id") or not cfg.get("api_hash"):
        pytest.skip(
            "Telegram not configured in DB — set via Admin → Telegram Configuration"
        )
    return cfg


@pytest.mark.asyncio
async def test_connection():
    """Probar conexión a Telegram"""
    print_separator("Test de Conexión")

    cfg = _require_telegram_config()

    try:
        service = get_telegram_service(
            api_id=int(cfg["api_id"]),
            api_hash=cfg["api_hash"],
            bot_token=cfg.get("bot_token") or None,
            phone=cfg.get("phone") or None,
            session_name=cfg.get("session_name") or "squidstats_bot",
            enabled=True,
        )

        print("Conectando a Telegram...")
        await service.connect()
        print("✅ Conexión establecida")

        print("\nObteniendo información de la cuenta...")
        health = await service.health_check()

        print("\n📊 Estado del servicio:")
        print(f"   Habilitado: {health['enabled']}")
        print(f"   Conectado: {health['connected']}")
        print(f"   Modo Bot: {health['bot_mode']}")
        print(f"   Sesión: {health['session']}")

        if health["connected"]:
            print(f"   User ID: {health.get('user_id', 'N/A')}")
            print(f"   Username: {health.get('username', 'N/A')}")
            print("\n✅ Test de conexión exitoso")
        else:
            error = health.get("error", "Unknown error")
            print(f"\n❌ No se pudo conectar: {error}")
            return False

        await service.disconnect()
        return True

    except Exception as e:
        print(f"\n❌ Error en test de conexión: {e}")
        import traceback

        traceback.print_exc()
        return False


@pytest.mark.asyncio
async def test_send_basic_notification():
    """Probar envío de notificación básica"""
    print_separator("Test de Notificación Básica")

    cfg = _require_telegram_config()
    recipients = cfg.get("recipients", [])
    if not recipients:
        pytest.skip("No recipients configured in DB")

    try:
        service = get_telegram_service()
        await service.connect()

        recipient = recipients[0]

        print(f"Enviando notificación de prueba a: {recipient}")

        success = await service.send_notification(
            recipient=recipient,
            message="🧪 Test de notificación desde SquidStats\n\nSi recibes este mensaje, la integración funciona correctamente.",
            priority=NotificationPriority.NORMAL,
            source="Test Suite",
        )

        if success:
            print("✅ Notificación enviada exitosamente")
        else:
            print("❌ No se pudo enviar la notificación")

        await service.disconnect()
        return success

    except Exception as e:
        print(f"❌ Error enviando notificación: {e}")
        import traceback

        traceback.print_exc()
        return False


@pytest.mark.asyncio
async def test_priority_notifications():
    """Probar notificaciones con diferentes prioridades"""
    print_separator("Test de Prioridades")

    cfg = _require_telegram_config()
    recipients = cfg.get("recipients", [])
    if not recipients:
        pytest.skip("No recipients configured in DB")

    try:
        service = get_telegram_service()
        await service.connect()

        recipient = recipients[0]

        priorities = [
            (NotificationPriority.LOW, "Información de baja prioridad"),
            (NotificationPriority.NORMAL, "Notificación estándar"),
            (NotificationPriority.HIGH, "Advertencia importante"),
            (NotificationPriority.CRITICAL, "¡Alerta crítica!"),
        ]

        for priority, message in priorities:
            print(f"Enviando {priority.name}...")
            await service.send_notification(
                recipient=recipient,
                message=message,
                priority=priority,
                source="Priority Test",
            )
            await asyncio.sleep(1)  # Evitar rate limiting

        print("✅ Todas las prioridades enviadas")
        await service.disconnect()
        return True

    except Exception as e:
        print(f"❌ Error en test de prioridades: {e}")
        return False


@pytest.mark.asyncio
async def test_formatted_notifications():
    """Probar notificaciones con datos extra"""
    print_separator("Test de Mensajes Formateados")

    cfg = _require_telegram_config()
    recipients = cfg.get("recipients", [])
    if not recipients:
        pytest.skip("No recipients configured in DB")

    try:
        service = get_telegram_service()
        await service.connect()

        recipient = recipients[0]

        print("Enviando notificación con metadata...")
        await service.send_notification(
            recipient=recipient,
            message="Alerta del sistema detectada",
            priority=NotificationPriority.HIGH,
            source="System Monitor",
            extra_data={
                "CPU": "85%",
                "RAM": "7.2 GB / 16 GB",
                "Disco": "45.3 GB disponibles",
                "Uptime": "5 días, 3 horas",
            },
        )

        print("✅ Notificación formateada enviada")
        await service.disconnect()
        return True

    except Exception as e:
        print(f"❌ Error en test de formato: {e}")
        return False


def test_integration_wrapper():
    """Probar wrapper de integración (funciones síncronas)"""
    print_separator("Test de Wrapper de Integración")

    try:
        # Inicializar servicio
        print("Inicializando servicio de Telegram...")
        if not initialize_telegram_service():
            print(
                "⚠️ Telegram no está configurado o está deshabilitado en este entorno de pruebas"
            )
            pytest.skip("Telegram integration not configured")
        print("✅ Servicio inicializado")

        # Health check
        print("\nVerificando estado...")
        health = telegram_health_check()
        print(f"Estado: {health}")

        if not health.get("connected"):
            print("⚠️ No conectado - algunas funciones no estarán disponibles")

        # Enviar notificación genérica
        print("\nEnviando notificación genérica...")
        success1 = send_telegram_notification(
            notification_type="info",
            message="Test de integración wrapper",
            source="Integration Test",
        )
        print(f"Resultado: {'✅ Enviado' if success1 else '❌ Fallo'}")

        # Enviar alerta de seguridad
        print("\nEnviando alerta de seguridad...")
        success2 = send_security_alert_telegram(
            alert_type="Acceso sospechoso detectado",
            details={
                "IP": "192.168.1.100",
                "Usuario": "test_user",
                "Timestamp": "2026-01-17 15:00:00",
            },
        )
        print(f"Resultado: {'✅ Enviado' if success2 else '❌ Fallo'}")

        # Enviar alerta del sistema
        print("\nEnviando alerta del sistema...")
        success3 = send_system_alert_telegram(
            alert_message="Uso elevado de recursos detectado",
            metrics={"CPU": "92%", "Memoria": "14.8 GB / 16 GB", "Temperatura": "78°C"},
        )
        print(f"Resultado: {'✅ Enviado' if success3 else '❌ Fallo'}")

        # Enviar alerta de actividad de usuario
        print("\nEnviando alerta de actividad de usuario...")
        success4 = send_user_activity_alert_telegram(
            username="john_doe",
            activity_data={
                "Requests": "1,234",
                "Datos descargados": "45.3 GB",
                "Sitios únicos": "87",
            },
        )
        print(f"Resultado: {'✅ Enviado' if success4 else '❌ Fallo'}")

        all_success = all([success1, success2, success3, success4])

        if all_success:
            print("\n✅ Todos los tests del wrapper exitosos")
        else:
            print("\n⚠️ Algunos tests fallaron")

        assert all_success, "Al menos un test del wrapper falló"

    except Exception as e:
        print(f"\n❌ Error en test de wrapper: {e}")
        import traceback

        traceback.print_exc()
        pytest.fail(f"Error en test de wrapper: {e}")


async def run_async_tests():
    """Ejecutar tests asíncronos"""
    results = []

    # Test de conexión
    results.append(await test_connection())
    await asyncio.sleep(2)

    # Test de notificación básica
    results.append(await test_send_basic_notification())
    await asyncio.sleep(2)

    # Test de prioridades
    results.append(await test_priority_notifications())
    await asyncio.sleep(2)

    # Test de formato
    results.append(await test_formatted_notifications())

    return results


def test_proxy_parsing():
    """Test parsing de URLs de proxy HTTP"""
    print_separator("🧪 Test de Parsing de Proxy")

    test_cases = [
        # (input, expected_output_keys)
        ("", None),
        ("http://proxy.example.com:8080", ["proxy_type", "addr", "port"]),
        (
            "http://user:pass@proxy.example.com:8080",
            ["proxy_type", "addr", "port", "username", "password"],
        ),
        ("https://proxy.example.com:8080", None),  # Solo HTTP soportado
        ("invalid-url", None),
    ]

    all_passed = True

    for i, (proxy_url, expected_keys) in enumerate(test_cases, 1):
        try:
            result = parse_http_proxy_url(proxy_url)

            if expected_keys is None:
                if result is None:
                    print(f"✅ Test {i}: '{proxy_url}' → None (correcto)")
                else:
                    print(f"❌ Test {i}: '{proxy_url}' → {result} (esperaba None)")
                    all_passed = False
            else:
                if result and all(key in result for key in expected_keys):
                    print(f"✅ Test {i}: '{proxy_url}' → {result}")
                else:
                    print(
                        f"❌ Test {i}: '{proxy_url}' → {result} (faltan keys: {expected_keys})"
                    )
                    all_passed = False

        except Exception as e:
            print(f"❌ Test {i}: Error parsing '{proxy_url}': {e}")
            all_passed = False

    if all_passed:
        print("\n✅ Todos los tests de proxy pasaron")
    else:
        print("\n❌ Algunos tests de proxy fallaron")

    assert all_passed, "El parsing de proxy falló en uno o más casos"


def main():
    """Función principal"""
    print_separator("🧪 Test de Integración de Telegram")

    # Verificar configuración
    if not check_configuration():
        print("\n❌ Configuración incompleta. Corrige los errores y vuelve a intentar.")
        sys.exit(1)

    # Test de parsing de proxy
    proxy_test_passed = test_proxy_parsing()

    # Ejecutar tests asíncronos
    print("\n🚀 Iniciando tests asíncronos...")
    async_results = asyncio.run(run_async_tests())

    # Ejecutar tests síncronos (wrapper)
    print("\n🚀 Iniciando tests de wrapper...")
    sync_result = True
    try:
        test_integration_wrapper()
    except AssertionError as e:
        print(f"\n❌ Test de wrapper falló: {e}")
        sync_result = False
    except Exception as e:
        print(f"\n❌ Error inesperado en el test de wrapper: {e}")
        import traceback

        traceback.print_exc()
        sync_result = False

    # Resumen
    print_separator("📊 Resumen de Tests")

    tests = [
        ("Parsing de Proxy", proxy_test_passed),
        ("Conexión", async_results[0] if len(async_results) > 0 else False),
        ("Notificación básica", async_results[1] if len(async_results) > 1 else False),
        ("Prioridades", async_results[2] if len(async_results) > 2 else False),
        ("Formato", async_results[3] if len(async_results) > 3 else False),
        ("Wrapper de integración", sync_result),
    ]

    for test_name, result in tests:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")

    total = len(tests)
    passed = sum(1 for _, result in tests if result)

    print(f"\n📈 Resultados: {passed}/{total} tests exitosos")

    if passed == total:
        print(
            "\n🎉 ¡Todos los tests pasaron! La integración de Telegram está funcionando correctamente."
        )
        return 0
    else:
        print("\n⚠️ Algunos tests fallaron. Revisa los logs para más detalles.")
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️ Test interrumpido por el usuario")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Error fatal: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
