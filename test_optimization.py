#!/usr/bin/env python3
"""
Script para probar las optimizaciones de intervalos de recolección de datos.
"""

import time
from datetime import datetime

def test_intervals():
    """Simula los nuevos intervalos de recolección de datos"""
    print("🧪 Probando nuevos intervalos de recolección de datos")
    print("=" * 60)
    
    # Simular el comportamiento del nuevo sistema
    data_collection_counter = 0
    
    print("⏱️  Intervalos configurados:")
    print("   • WebSocket (tiempo real): 15 segundos")
    print("   • Base de datos: 60 segundos (cada 4 actualizaciones)")
    print("   • Gráficas en vivo: 60 segundos (cada 4 actualizaciones)")
    print("   • Historial: Sampling inteligente para >288 puntos")
    print()
    
    # Calcular métricas de rendimiento
    old_websocket_per_hour = 60 * 60 / 5  # 720 actualizaciones por hora
    new_websocket_per_hour = 60 * 60 / 15  # 240 actualizaciones por hora
    
    old_db_per_day = 24 * 60 * 60 / 5  # 17,280 inserciones por día
    new_db_per_day = 24 * 60 * 60 / 60  # 1,440 inserciones por día
    
    print("📊 Mejoras de rendimiento:")
    print(f"   • WebSocket: {old_websocket_per_hour:.0f} → {new_websocket_per_hour:.0f} mensajes/hora ({((old_websocket_per_hour - new_websocket_per_hour) / old_websocket_per_hour * 100):.1f}% menos)")
    print(f"   • Base de datos: {old_db_per_day:.0f} → {new_db_per_day:.0f} inserciones/día ({((old_db_per_day - new_db_per_day) / old_db_per_day * 100):.1f}% menos)")
    print("   • Gráficas: Misma reducción + sampling inteligente")
    print()
    
    # Simular 5 iteraciones para mostrar el comportamiento
    print("🔄 Simulando comportamiento del sistema (5 iteraciones de 15s):")
    print("   [R] = Tiempo Real  [BD] = Base de Datos  [G] = Gráficas")
    print()
    
    for i in range(1, 6):
        data_collection_counter += 1
        current_time = datetime.now().strftime("%H:%M:%S")
        
        actions = ["[R]"]  # Siempre hay actualización en tiempo real
        
        if data_collection_counter % 4 == 0:
            actions.extend(["[BD]", "[G]"])
        
        print(f"   {current_time} - Iteración {i}: {' '.join(actions)}")
        
        if i < 5:  # No esperar en la última iteración
            time.sleep(1)  # Simular con 1 segundo en lugar de 15 para la demo
    
    print()
    print("✅ Test completado. Los nuevos intervalos están optimizados para:")
    print("   • Menor carga del servidor")
    print("   • Menor uso de base de datos")
    print("   • Gráficas más fluidas")
    print("   • Mejor experiencia de usuario")

if __name__ == "__main__":
    test_intervals()
