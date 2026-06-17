"""
Prueba del camino COMPLETO de la cámara Arducam Módulo 3 (IMX708) de MEXA:

    Picamera2 (puerto CSI) -> modulo_camara.capturar_frame()
      -> detectar_cara() / posicion_cara()

Valida en TRES etapas, de menor a mayor exigencia:
  1) ENUMERACIÓN: que la cámara arranque (cam != None tras iniciar_camara()).
  2) CAPTURA:     que entregue un frame válido (array con forma esperada).
  3) DETECCIÓN:   polling en vivo de cara + posición, imprimiendo cada CAMBIO
                  de estado con cuenta regresiva. Ponete frente a la cámara.

Si la etapa 1 falla, el problema es de HARDWARE/CABLE, no del código:
  rpicam-hello --list-cameras        -> debe listar el imx708
  dmesg | grep -iE "imx708|rp1-cfe"  -> debe aparecer rp1-cfe

Ejecutar desde la raíz:  python3 tests/test_camara.py [segundos]
Por defecto corre 30s la etapa de detección.
"""

import os
import sys
import time

# Permite importar el paquete `modulos` al correr este test desde tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_camara import (
    iniciar_camara,
    capturar_frame,
    detectar_cara,
    posicion_cara,
    apagar_camara,
)
# Se importa el módulo (no `cam` por valor): `cam` es un global que
# iniciar_camara() reasigna, así que hay que leerlo como camara.cam.
import modulos.modulo_camara as camara


def etapa_enumeracion() -> bool:
    """Etapa 1: arranca la cámara y confirma que quedó enumerada."""
    print("[TEST] Etapa 1/3 — ENUMERACIÓN: iniciando cámara...")
    iniciar_camara()
    if camara.cam is None:
        print("[TEST] ✗ La cámara NO enumeró (cam=None).")
        print("[TEST]   El sensor no llegó al kernel. Revisá el HARDWARE:")
        print("[TEST]   - rpicam-hello --list-cameras   (debe listar imx708)")
        print("[TEST]   - dmesg | grep -iE 'imx708|rp1-cfe'")
        print("[TEST]   - cable FFC: ¿el de 22 pines de la Pi 5?, ¿orientación?, ¿palanca cerrada?")
        return False
    print("[TEST] ✓ Cámara enumerada y arrancada.")
    return True


def etapa_captura() -> bool:
    """Etapa 2: captura un frame y valida su forma."""
    print("[TEST] Etapa 2/3 — CAPTURA: tomando un frame...")
    frame = capturar_frame()
    if frame is None:
        print("[TEST] ✗ capturar_frame() devolvió None pese a estar enumerada.")
        return False
    print(f"[TEST] ✓ Frame capturado. Forma: {frame.shape} (alto, ancho, canales).")
    return True


def etapa_deteccion(dur: int) -> None:
    """Etapa 3: polling en vivo de cara + posición durante `dur` segundos."""
    print(f"[TEST] Etapa 3/3 — DETECCIÓN: probando {dur}s.")
    print("[TEST] Ponete frente a la cámara. Movete a los lados para ver la posición.")
    print("[TEST] Quedate fuera de cuadro -> 'sin cara'.\n")

    cambios = 0
    prev = None
    fin = time.time() + dur
    try:
        while time.time() < fin:
            frame = capturar_frame()
            hay = detectar_cara(frame)
            pos = posicion_cara(frame) if hay else None

            estado_actual = (hay, pos)
            if estado_actual != prev and prev is not None:
                cambios += 1
            prev = estado_actual

            restante = int(fin - time.time())
            if hay:
                estado = f"CARA <-- pos: {pos or '?':9s}"
            else:
                estado = "sin cara"
            print(f"\r  [{restante:3d}s restantes]  {estado:28s}  (cambios: {cambios})",
                  end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[TEST] Ctrl+C detectado.")
    finally:
        print(f"\n[TEST] Fin detección. Total de cambios de estado: {cambios}.")


def main() -> None:
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    print("[TEST] === Prueba de cámara Arducam Módulo 3 (IMX708) ===")

    try:
        if not etapa_enumeracion():
            return
        if not etapa_captura():
            return
        etapa_deteccion(dur)
    finally:
        apagar_camara()
        print("[TEST] Listo.")


if __name__ == "__main__":
    main()
