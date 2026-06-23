"""
Calibración del RETROCESO de MEXA (volver al punto de partida).

MEXA registra el camino mientras se acerca y luego lo DESHACE en orden
inverso. El avance y la reversa NO son simétricos (inercia, patinaje, el
motor rinde distinto en reversa), así que el retroceso necesita calibrarse:
ajustás `factor_duracion` hasta que MEXA termine sobre su marca de origen.

Este script usa el camino REAL de producción (RegistroCamino -> retroceder,
vía modulo_motores -> conexion_arduino): primero MEXA recorre un trayecto
de IDA conocido y registrado, y después lo retrocede. Vos medís cuánto se
desvía del origen.

USO (MEXA en el PISO, espacio libre, motores alimentados, Arduino por USB):
  python3 tests/calibrar_retroceso.py recto              # ida: avanza 3s
  python3 tests/calibrar_retroceso.py recto 4            # ida: avanza 4s
  python3 tests/calibrar_retroceso.py giro               # ida: avanza+gira+avanza (forma de L)
  python3 tests/calibrar_retroceso.py recto 3 1.15       # con factor_duracion=1.15

METODOLOGÍA (calibrá en este orden, una variable a la vez):
  1. EMPEZÁ con 'recto' y factor=1.0. Marcá dónde están las ruedas ANTES.
     Tras el retroceso, medí cuántos cm le faltaron (corto) o se pasó (largo).
  2. Si quedó CORTO -> subí el factor (probá 1.1, 1.2...). Si se PASÓ -> bajalo.
     Repetí 'recto' hasta que vuelva sobre la marca. Anotá ese factor: ese es
     el que pasás a retroceder(camino, factor_duracion=...) en main.py.
  3. RECIÉN AHÍ probá 'giro' con ese factor, para ver el error angular (los
     giros son la parte menos simétrica). Si el rumbo final queda torcido,
     el problema es el PULSO de giro, no el factor lineal.

Hay 3s de cuenta regresiva antes de la IDA y antes del RETROCESO.
Seguridad: al terminar SIEMPRE manda STOP. Ctrl+C también frena.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_motores import (iniciar_motores, mover_adelante,
                                     mover_por_tiempo, detener)
from modulos.conexion_arduino import cerrar_conexion
from modulos.registro_camino import RegistroCamino, retroceder

# Mismo pulso de giro que usa el lazo de acercamiento en main.py.
PULSO_GIRO_S = 0.25


def _cuenta_regresiva(que):
    print(f"[CAL] {que} en...")
    for n in (3, 2, 1):
        print(f"[CAL]   {n}...")
        time.sleep(1)


def _ida_recto(segundos):
    """Trayecto de ida recto: avanza `segundos` (avance continuo, como en
    el lazo cuando la cara está centrada)."""
    print(f"[CAL] >>> IDA: avanzar {segundos:.1f}s en línea recta.")
    mover_adelante()
    time.sleep(segundos)
    detener()


def _ida_giro(segundos):
    """Trayecto de ida en forma de L: avanza, gira a la derecha un pulso,
    y vuelve a avanzar. Ejercita la inversión de giro (R -> L)."""
    mitad = segundos / 2
    print(f"[CAL] >>> IDA (L): avanzar {mitad:.1f}s, girar derecha "
          f"{PULSO_GIRO_S:.2f}s, avanzar {mitad:.1f}s.")
    mover_adelante()
    time.sleep(mitad)
    detener()
    mover_por_tiempo("derecha", PULSO_GIRO_S)
    mover_adelante()
    time.sleep(mitad)
    detener()


def main():
    modo = sys.argv[1] if len(sys.argv) > 1 else None
    if modo not in ("recto", "giro"):
        print(__doc__)
        return

    segundos = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    factor = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

    print("[CAL] Conectando al Arduino...")
    iniciar_motores()

    print(f"[CAL] Modo={modo}, ida={segundos:.1f}s, factor_duracion={factor:.2f}.")
    print("[CAL] >>> MARCÁ la posición de las ruedas AHORA: ese es el ORIGEN.")
    print("[CAL]     MEXA debería volver EXACTAMENTE acá tras el retroceso.")

    registro = RegistroCamino()
    registro.iniciar()  # engancha la capa serial: anota cada comando de la ida

    try:
        _cuenta_regresiva("IDA")
        if modo == "recto":
            _ida_recto(segundos)
        else:
            _ida_giro(segundos)

        registro.finalizar()
        eventos = registro.eventos
        print(f"[CAL] Ida terminada. Camino registrado: {eventos}")

        _cuenta_regresiva("RETROCESO (deshacer la ida)")
        tramos = retroceder(eventos, factor_duracion=factor)
        print(f"[CAL] Retroceso terminado. Tramos ejecutados: {tramos}")
        print("[CAL] >>> MEDÍ ahora la desviación respecto del ORIGEN:")
        print("[CAL]     - distancia que le FALTÓ (corto) o se PASÓ (largo) en cm")
        print("[CAL]     - error de RUMBO (cuántos grados quedó torcido)")
    except KeyboardInterrupt:
        print("\n[CAL] Ctrl+C — frenando.")
    finally:
        detener()
        time.sleep(0.2)  # que el último 'S' salga por el serial antes de cerrar
        cerrar_conexion()
        print("[CAL] STOP enviado. Fin.")


if __name__ == "__main__":
    main()
