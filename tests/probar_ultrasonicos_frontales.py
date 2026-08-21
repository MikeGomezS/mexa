"""
Prueba de HARDWARE de los ultrasónicos FRONTALES de MEXA.

Responde dos preguntas, en este orden:
  1. ¿Están conectados y midiendo?  (¿llegan líneas 'DIST:'?)
  2. ¿A qué número hay que poner DISTANCIA_OBJETIVO_CM?

POR QUÉ HAY QUE MANDAR 'F' PARA MEDIR: el firmware mide al frente SÓLO
mientras hay un avance activo. Es deliberado — cada pulseIn bloquea el
loop, y medir cuando MEXA está quieta sólo la haría más lenta en atender
el serial. Efecto lateral útil: aunque los motores no giren (falla
eléctrica), el Arduino igual mide, así que este script valida los
SENSORES por separado del problema de los motores.

SEGURIDAD: ELEVÁ el robot con las ruedas en el aire. Este script manda
'F' de verdad. Al salir (Ctrl+C o fin) SIEMPRE manda 'S'.

CÓMO CALIBRAR:
  Parate frente a MEXA con una cinta métrica. Corré el script, mirá la
  columna `cm` y comparala con la distancia real. Cuando coincidan,
  elegí a qué distancia querés que MEXA se pare a conversar y poné ese
  número en modulos/navegacion.py -> DISTANCIA_OBJETIVO_CM.

  Si la columna dice siempre 999: el sensor no ve nada. Revisá TRIG/ECHO
  (frontal DER D53/D52, frontal IZQ D51/D50) y hacia dónde APUNTAN.
  Si dice siempre '--': no llega ni una línea 'DIST:' — el firmware
  cargado es el viejo, o el avance no arrancó.

Ejecutar desde la raíz del proyecto:
  python3 tests/probar_ultrasonicos_frontales.py [segundos]
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.conexion_arduino import (iniciar_conexion, cerrar_conexion,
                                      distancia_frontal_cm, freno_por_persona,
                                      reiniciar_frente)
from modulos.modulo_motores import mover_adelante, detener
from modulos.navegacion import DISTANCIA_OBJETIVO_CM
from modulos.telemetria import SIN_ECO_CM

DURACION_S = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
INTERVALO_S = 0.2   # cada cuánto se imprime (no cada cuánto se mide)


def main():
    print("=" * 60)
    print("  MEXA — Ultrasónicos FRONTALES (distancia a la persona)")
    print("=" * 60)
    print("  SEGURIDAD: el robot va a recibir 'F'. Ruedas EN EL AIRE.")
    print(f"  Objetivo configurado: DISTANCIA_OBJETIVO_CM = {DISTANCIA_OBJETIVO_CM:.0f}cm")
    print(f"  Duración: {DURACION_S:.0f}s.  Ctrl+C para cortar antes.")
    print("-" * 60)

    if iniciar_conexion() is None:
        print("Sin conexión con el Arduino. Nada que medir.")
        return 1

    reiniciar_frente()
    mover_adelante()
    fin = time.monotonic() + DURACION_S
    lecturas = 0
    try:
        while time.monotonic() < fin:
            frenado = freno_por_persona()
            if frenado is not None:
                print(f"  !! El Arduino FRENÓ SOLO a {frenado:.0f}cm "
                      f"(reflejo de seguridad del firmware).")
                break

            distancia = distancia_frontal_cm()
            if distancia is None:
                estado = "  --   (sin lectura fresca)"
            elif distancia >= SIN_ECO_CM:
                estado = " 999   (nada dentro del alcance)"
            else:
                lecturas += 1
                marca = "<= OBJETIVO" if distancia <= DISTANCIA_OBJETIVO_CM else ""
                estado = f"{distancia:6.1f} cm  {marca}"
            print(f"  cm: {estado}")
            sys.stdout.flush()
            time.sleep(INTERVALO_S)
    except KeyboardInterrupt:
        print("\n  Cortado por el usuario.")
    finally:
        detener()
        print("-" * 60)
        if lecturas:
            print(f"  {lecturas} lectura(s) con eco: los frontales ANDAN.")
            print("  Ahora compará los cm con la cinta métrica y ajustá")
            print("  DISTANCIA_OBJETIVO_CM en modulos/navegacion.py.")
        else:
            print("  NINGUNA lectura con eco. Revisá, en este orden:")
            print("   1. ¿Cargaste el firmware nuevo? (banner: '4 ultrasonicos')")
            print("   2. Cableado frontal DER D53/D52, IZQ D51/D50 (TRIG/ECHO).")
            print("   3. ¿Hacia dónde apuntan? Tienen que ver el torso, no el piso.")
        cerrar_conexion()
    return 0


if __name__ == "__main__":
    sys.exit(main())
