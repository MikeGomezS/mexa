"""
Prueba del camino COMPLETO de presencia (PIR) de MEXA:

    Arduino (2x PIR: D24 derecho / D22 izquierdo) -> "PRES:0/1" por serial
      -> conexion_arduino._bombear() -> modulo_sensores.detectar_persona()

Hace polling de detectar_persona() e imprime cada CAMBIO de estado con
marca de tiempo. Movete frente a cada PIR para ver "PRESENCIA: SI".

NOTA: el firmware reporta la OR de ambos PIR, así que desde la Pi NO se
distingue cuál disparó. Para probar cada uno por separado, quedate quieto
y movete SOLO frente a un PIR a la vez.

Ejecutar desde la raíz:  python3 tests/test_presencia.py [segundos]
Usa el puerto definido en modulos/config.py (ARDUINO_PUERTO).
"""

import os
import sys
import time

# Permite importar el paquete `modulos` al correr este test desde tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_sensores import iniciar_sensores, detectar_persona
from modulos.conexion_arduino import cerrar_conexion


def main() -> None:
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    print(f"[TEST] Probando presencia por {dur}s.")
    print("[TEST] Movete frente a los PIR (D24 derecho / D22 izquierdo).")

    iniciar_sensores()

    print("[TEST] OJO: el PIR necesita ~30-60s de calentamiento tras encender;")
    print("[TEST] durante ese rato puede dar falsos. Esperá un poco y luego probá.")
    print("[TEST] Quedate quieto -> debe leer 'no'. Movete -> 'SI'.\n")

    cambios = 0
    prev = None
    fin = time.time() + dur
    try:
        while time.time() < fin:
            hay = detectar_persona()
            if hay != prev and prev is not None:
                cambios += 1
            prev = hay
            restante = int(fin - time.time())
            estado = "SI  <-- PRESENCIA" if hay else "no"
            print(f"\r  [{restante:3d}s restantes]  PIR: {estado:18s}  (cambios: {cambios})",
                  end="", flush=True)
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n[TEST] Ctrl+C detectado.")
    finally:
        cerrar_conexion()
        print(f"\n[TEST] Fin. Total de cambios de estado: {cambios}.")


if __name__ == "__main__":
    main()
