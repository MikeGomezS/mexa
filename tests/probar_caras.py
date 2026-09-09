"""
Prueba VISUAL de las caras de MEXA: las muestra una por una en el proyector.

Usa el camino REAL (modulo_proyector.cambiar_expresion), el mismo que llama
dialogo.py, así probás exactamente lo que corre en producción — incluida la
transición animada de una expresión a la siguiente, que es lo que hay que mirar.

USO (con el proyector conectado):
  python3 tests/probar_caras.py              # recorre todas, 4 s cada una
  python3 tests/probar_caras.py feliz        # se queda en una sola
  python3 tests/probar_caras.py hablando 2   # una sola, 2 s por vuelta

En "hablando" se le manda un volumen simulado para ver la boca sincronizarse.
Ctrl+C en cualquier momento -> cierra la cara y sale.
"""

import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_proyector import (
    _desactivar_cara,
    cambiar_expresion,
    enviar_volumen,
)

# Orden del recorrido. La fuente de verdad es POSES en modulos/_cara_animada.py;
# acá van ordenadas para que se note la TRANSICIÓN entre gestos opuestos.
RECORRIDO = (
    "idle", "escuchando", "hablando", "pensando", "confundido",
    "sorprendido", "feliz", "emocionado", "guino", "triste",
    "enojado", "dormido",
)


def _mostrar(expresion: str, segundos: float) -> None:
    print(f"[PRUEBA] {expresion}")
    cambiar_expresion(expresion)

    fin = time.time() + segundos
    while time.time() < fin:
        if expresion == "hablando":
            # Envolvente de voz simulada: dos senos desfasados dan un ritmo
            # irregular parecido al del habla, no un latido mecánico.
            u = time.time() * 6.0
            v = abs(math.sin(u)) * 0.6 + abs(math.sin(u * 0.37)) * 0.4
            enviar_volumen(min(1.0, v))
        time.sleep(0.05)


def main() -> None:
    argumentos = sys.argv[1:]
    una_sola = argumentos[0] if argumentos and not argumentos[0].isdigit() else None
    segundos = float(argumentos[-1]) if argumentos and argumentos[-1].replace(".", "", 1).isdigit() else 4.0

    if una_sola and una_sola not in RECORRIDO:
        print(f"[PRUEBA] '{una_sola}' no está en el recorrido. Disponibles:")
        print("         " + ", ".join(RECORRIDO))
        return

    lista = (una_sola,) if una_sola else RECORRIDO
    print(f"[PRUEBA] {len(lista)} expresión(es), {segundos:.1f} s cada una. Ctrl+C para salir.")

    try:
        while True:
            for expresion in lista:
                _mostrar(expresion, segundos)
            if una_sola:
                continue
            print("[PRUEBA] Vuelta completa, arranca de nuevo.")
    except KeyboardInterrupt:
        print("\n[PRUEBA] Cerrando la cara...")
    finally:
        _desactivar_cara()
        print("[PRUEBA] Listo.")


if __name__ == "__main__":
    main()
