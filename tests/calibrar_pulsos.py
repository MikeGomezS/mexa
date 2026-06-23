"""
Calibración de PULSOS de movimiento de MEXA tras cambiar las llantas.

Dispara UN pulso de duración exacta (la misma que usa el lazo de
acercamiento por cámara en main.py) para que midas en el piso:
  - AVANCE: cuántos cm avanza MEXA en un pulso de PULSO_AVANCE_S.
  - GIRO:   cuántos grados gira MEXA en un pulso de PULSO_GIRO_S.

Con esos números ajustás las constantes en main.py:
  TAMANO_CARA_OBJETIVO, PULSO_AVANCE_S, PULSO_GIRO_S.

USO (MEXA en el PISO, espacio libre alrededor):
  python3 tests/calibrar_pulsos.py avance          # usa PULSO_AVANCE_S de main.py
  python3 tests/calibrar_pulsos.py giro            # usa PULSO_GIRO_S de main.py
  python3 tests/calibrar_pulsos.py avance 0.6      # override de duración (segundos)
  python3 tests/calibrar_pulsos.py giro 0.4

Marcá la posición de una rueda ANTES del pulso, mirá dónde queda DESPUÉS,
y medís. Repetí variando la duración hasta que el avance/giro por pulso sea
el que querés. Hay 3s de cuenta regresiva antes de cada disparo.

Seguridad: al terminar SIEMPRE manda STOP. Ctrl+C también frena.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_motores import iniciar_motores, mover_por_tiempo, detener

# Valores actuales en main.py (referencia para el default).
PULSO_AVANCE_S = 0.4
PULSO_GIRO_S = 0.25


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("avance", "giro"):
        print(__doc__)
        return

    tipo = sys.argv[1]
    if tipo == "avance":
        direccion = "adelante"
        dur = PULSO_AVANCE_S
        que_medir = "cuántos CM avanzó MEXA"
    else:  # giro
        direccion = "derecha"  # mismo comando 'R' que usa el lazo para centrar
        dur = PULSO_GIRO_S
        que_medir = "cuántos GRADOS giró MEXA"

    if len(sys.argv) >= 3:
        try:
            dur = float(sys.argv[2])
        except ValueError:
            print(f"[CAL] Duración inválida: {sys.argv[2]!r}")
            return

    print(f"[CAL] Conectando al Arduino...")
    iniciar_motores()

    print(f"[CAL] PULSO de {tipo.upper()} = {dur:.2f}s (dirección: {direccion}).")
    print(f"[CAL] Marcá la posición de una rueda AHORA. Medí después {que_medir}.")
    for n in (3, 2, 1):
        print(f"[CAL] Disparando en {n}...")
        time.sleep(1)

    try:
        print(f"[CAL] >>> PULSO {direccion} {dur:.2f}s")
        mover_por_tiempo(direccion, dur)
        print("[CAL] Pulso terminado (MEXA ya frenó). Medí el desplazamiento.")
    except KeyboardInterrupt:
        print("\n[CAL] Ctrl+C — frenando.")
    finally:
        detener()
        time.sleep(0.2)
        print("[CAL] STOP enviado. Fin.")


if __name__ == "__main__":
    main()
