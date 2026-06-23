"""
Prueba MÍNIMA de motores: que MEXA AVANCE y luego se detenga.

Usa el camino REAL del código (modulo_motores → conexion_arduino), no serial
crudo, así probás exactamente lo que corre en producción.

USO (MEXA con motores alimentados y Arduino conectado por USB):
  python3 tests/probar_avance.py            # avanza 2s y para
  python3 tests/probar_avance.py 4          # avanza 4s y para

Ctrl+C en cualquier momento -> manda STOP y cierra.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_motores import iniciar_motores, mover_adelante, detener
from modulos.conexion_arduino import cerrar_conexion


def main() -> None:
    segundos = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0

    print("[PRUEBA] Iniciando conexión con el Arduino...")
    iniciar_motores()

    try:
        print(f"[PRUEBA] >>> AVANZAR durante {segundos}s.")
        mover_adelante()
        time.sleep(segundos)

        print("[PRUEBA] >>> DETENER.")
        detener()
    except KeyboardInterrupt:
        detener()
        print("\n[PRUEBA] Ctrl+C — STOP enviado.")
    finally:
        # Pequeña pausa para que el último 'S' salga por el serial antes de cerrar.
        time.sleep(0.2)
        cerrar_conexion()
        print("[PRUEBA] Fin.")


if __name__ == "__main__":
    main()
