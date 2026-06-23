"""
Verificación en hardware del LAZO DE ACERCAMIENTO con cámara de MEXA.

Replica la lógica de main.py:acercarse_a_usuario() aislando el subsistema bajo
prueba (cámara + motores): no carga audio/IA/TTS, arranca rápido y no se traba.

ESTRATEGIA (dos fases):
  1. FASE VISUAL: centra y avanza usando el tamaño de la cara como proxy de
     distancia, hasta que la cara se PIERDE. Como la cámara está inclinada y MEXA
     es bajo, al acercarse mucho (~1.0m) la cara se RECORTA por arriba del cuadro
     y YuNet deja de verla. Esa pérdida ES la señal de "ya estoy cerca".
  2. EMPUJE CIEGO FINAL: si la cara se perdió ESTANDO CERCA Y CENTRADA (último
     tamaño >= UMBRAL_CARA_CERCA y al centro), MEXA avanza a ciegas
     AVANCE_CIEGO_FINAL_S para cerrar el último tramo (~0.7m). Si la cara se
     perdió LEJOS o descentrada, NO empuja (la persona se fue) y aborta.

Las constantes son COPIA de main.py — trasladá el valor ganador a main.py
(esa es la fuente de verdad del flujo).

USO (MEXA en el piso con espacio libre adelante; parate a la distancia del PIR):
  python3 tests/calibrar_acercamiento.py

Calibrar AVANCE_CIEGO_FINAL_S: mirá dónde queda MEXA tras el empuje ciego y
ajustá los segundos hasta que frene a ~0.7m del visitante.
Ctrl+C frena en cualquier momento.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_motores import iniciar_motores, mover_por_tiempo, detener
from modulos.modulo_camara import iniciar_camara, localizar_cara, apagar_camara

# --- COPIA de las constantes de main.py (fuente de verdad: main.py) ----------
# OJO: timeout SUBIDO a 30s para el experimento; en main.py es 12.0 — no trasladar.
ACERCAMIENTO_TIMEOUT_S  = 30.0
# Techo de seguridad ALTO a propósito: la visión casi nunca lo alcanza porque la
# cara se recorta antes (~25%). Sirve solo como corte si por geometría rara la
# cara llegara a verse enorme. El freno real lo da la pérdida de cara + empuje.
TAMANO_CARA_OBJETIVO    = 0.40
PULSO_AVANCE_S          = 0.6
PULSO_GIRO_S            = 0.25
MAX_MISSES_ACERCAMIENTO = 6
SETTLE_S                = 0.35   # respiro anti-blur tras cada pulso
# Empuje ciego final: cuánto avanza a ciegas tras perder la cara por cercanía.
UMBRAL_CARA_CERCA       = 0.20   # último tamaño mínimo para confiar en que el
                                 # recorte es por estar cerca (no porque se fue).
AVANCE_CIEGO_FINAL_S    = 10.0   # segundos de empuje ciego (CALIBRAR a ~0.7m).


def acercarse_a_usuario():
    """Fase visual + empuje ciego final. Espejo de main.py:acercarse_a_usuario."""
    fin = time.time() + ACERCAMIENTO_TIMEOUT_S
    misses = 0
    primera_cara = True
    ult_tamano = 0.0
    ult_posicion = "centro"
    while time.time() < fin:
        lectura = localizar_cara()
        if lectura is None:
            misses += 1
            if misses >= MAX_MISSES_ACERCAMIENTO:
                # Cara perdida: ¿por cercanía (recorte) o porque se fue?
                cerca = ult_tamano >= UMBRAL_CARA_CERCA
                centrada = ult_posicion == "centro"
                if cerca and centrada:
                    print(f"[CAL] Cara perdida ESTANDO CERCA (últ={ult_tamano:.0%}, "
                          f"centro) -> recorte. Empuje ciego {AVANCE_CIEGO_FINAL_S}s.")
                    mover_por_tiempo("adelante", AVANCE_CIEGO_FINAL_S)
                    print("[CAL] Empuje ciego terminado (MEXA frenó). ÉXITO.")
                else:
                    print(f"[CAL] Cara perdida LEJOS/descentrada (últ={ult_tamano:.0%}, "
                          f"{ult_posicion}) -> NO empujo, abort.")
                break
            continue
        misses = 0
        posicion, tamano = lectura
        ult_tamano, ult_posicion = tamano, posicion
        if primera_cara:
            print(f"[CAL] Acercamiento: primera cara en pos={posicion}, "
                  f"tamaño={tamano:.0%}.")
            primera_cara = False
        else:
            print(f"[CAL]   tick: pos={posicion}, tamaño={tamano:.0%}")
        if tamano >= TAMANO_CARA_OBJETIVO:
            print(f"[CAL] Techo de seguridad (cara={tamano:.0%}), freno.")
            break
        if posicion == "izquierda":
            mover_por_tiempo("izquierda", PULSO_GIRO_S)
        elif posicion == "derecha":
            mover_por_tiempo("derecha", PULSO_GIRO_S)
        else:
            mover_por_tiempo("adelante", PULSO_AVANCE_S)
        time.sleep(SETTLE_S)  # asentar antes de la próxima lectura (anti-blur)
    else:
        print("[CAL] Acercamiento: TIMEOUT (no perdió ni alcanzó la cara a tiempo).")
    detener()


def main() -> None:
    print("[CAL] Iniciando motores y cámara...")
    iniciar_motores()
    iniciar_camara()
    time.sleep(1)  # dejar asentar el autofocus
    print(f"[CAL] techo={TAMANO_CARA_OBJETIVO:.0%}, timeout={ACERCAMIENTO_TIMEOUT_S}s, "
          f"umbral_cerca={UMBRAL_CARA_CERCA:.0%}, ciego={AVANCE_CIEGO_FINAL_S}s.")
    print("[CAL] Parate frente a MEXA. Arranca en 3s...")
    time.sleep(3)
    try:
        t0 = time.time()
        acercarse_a_usuario()
        print(f"[CAL] Duración total: {time.time() - t0:.1f}s.")
    except KeyboardInterrupt:
        print("\n[CAL] Ctrl+C — frenando.")
    finally:
        detener()
        apagar_camara()
        print("[CAL] STOP + cámara apagada. Fin.")


if __name__ == "__main__":
    main()
