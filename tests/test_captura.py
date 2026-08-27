"""
Contrato de la captura de audio por PipeWire (modulos/captura.py).

QUÉ CUBRE Y POR QUÉ. MEXA dejó de leer el micrófono con PyAudio sobre
ALSA y ahora lo lee de un `pw-record`, para que la captura entre al
servidor de sonido y el cancelador de eco pueda restarle lo que MEXA
misma está diciendo. Ese cambio mueve la lectura de una librería que
entrega bloques completos a un PIPE, que no garantiza nada de eso.

Un pipe rompe tres supuestos que el código de arriba da por ciertos:

  1. read(n) puede devolver MENOS de lo pedido. Si se acepta el trozo
     corto, los chunks quedan de largo variable y TODAS las constantes de
     tiempo del VAD se corren sin que nada avise. Es la falla más cara
     porque no se ve: MEXA simplemente empieza a cortar frases mal.
  2. El productor puede morirse. Con PyAudio eso era un OSError; sobre un
     pipe es un read vacío, que parecería silencio eterno. MEXA quedaría
     sorda pareciendo que anda.
  3. Lo que no se lee SE ACUMULA. Mientras MEXA habla nadie consume el
     pipe, así que al volver a escuchar lo primero que hay es su propia
     voz de hace dos segundos.

El test NO necesita PipeWire ni micrófono: el comando del productor se
inyecta, así que corre en cualquier máquina y siempre igual.

USO:  python3 tests/test_captura.py
"""

import os
import struct
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.captura import (ANCHO, CapturaPipeWire, elegir_nodo, NODO_AEC,
                             NODO_CRUDO, PUERTO_MIC)

# Productor de mentira: escribe una CUENTA CRECIENTE como int16, en
# bloques chicos y con pausas. Los bloques chicos fuerzan el read parcial
# que un micrófono real también produce; la cuenta creciente permite
# saber EN QUÉ PUNTO del audio estamos, que es lo que hace verificable el
# descarte de lo acumulado.
_FUENTE = """
import os, struct, sys, time
i = 0
while True:
    bloque = b"".join(struct.pack("<h", (i + k) %% 30000) for k in range(%d))
    try:
        os.write(1, bloque)
    except (BrokenPipeError, OSError):
        break
    i += %d
    time.sleep(%f)
"""


def _productor(frames_por_bloque=40, pausa=0.005):
    return [sys.executable, "-c",
            _FUENTE % (frames_por_bloque, frames_por_bloque, pausa)]


def _primer_valor(datos: bytes) -> int:
    return struct.unpack("<h", datos[:2])[0]


def _valores(datos: bytes) -> list[int]:
    return [v[0] for v in struct.iter_unpack("<h", datos)]


# ── Casos ───────────────────────────────────────────────────────

def caso_lectura_completa() -> tuple[bool, str]:
    """read(n) devuelve EXACTAMENTE n*2 bytes, aunque el pipe gotee."""
    cap = CapturaPipeWire(_productor(frames_por_bloque=7, pausa=0.002))
    try:
        for pedido in (4096, 1024, 4096):
            datos = cap.read(pedido)
            if len(datos) != pedido * ANCHO:
                return False, (f"pedí {pedido} frames ({pedido*ANCHO} bytes) "
                               f"y devolvió {len(datos)}")
        return True, "3 lecturas de largo exacto con productor a 7 frames/bloque"
    finally:
        cap.close()


def caso_continuidad() -> tuple[bool, str]:
    """Dos lecturas seguidas no pierden ni repiten muestras."""
    cap = CapturaPipeWire(_productor())
    try:
        a = _valores(cap.read(500))
        b = _valores(cap.read(500))
        juntos = a + b
        saltos = [i for i in range(1, len(juntos))
                  if (juntos[i] - juntos[i-1]) % 30000 != 1]
        if saltos:
            return False, f"{len(saltos)} discontinuidades entre lecturas"
        return True, "1000 muestras consecutivas sin huecos ni repeticiones"
    finally:
        cap.close()


def caso_descarte() -> tuple[bool, str]:
    """descartar_pendiente() tira lo viejo y deja lo que suena AHORA."""
    cap = CapturaPipeWire(_productor())
    try:
        cap.read(100)                      # arranca el flujo
        viejo = _primer_valor(cap.read(2)) # dónde estábamos
        time.sleep(0.6)                    # MEXA hablando: nadie consume
        cap.descartar_pendiente()
        nuevo = _primer_valor(cap.read(2))
        avance = (nuevo - viejo) % 30000
        if avance < 1000:
            return False, (f"tras descartar seguimos casi donde estábamos "
                           f"(avance {avance} muestras): el buffer viejo pasó")
        return True, f"descartó {avance} muestras acumuladas"
    finally:
        cap.close()


def caso_productor_muerto() -> tuple[bool, str]:
    """Si pw-record se cae, read() avisa con OSError, no con silencio.

    _escuchar() ya sabe atrapar OSError y recrear el stream. Devolver
    ceros dejaría a MEXA sorda sin que nadie se entere.
    """
    cap = CapturaPipeWire(_productor())
    try:
        cap.read(50)
        cap._proc.kill()
        cap._proc.wait()
        try:
            datos = cap.read(4096)
        except OSError:
            return True, "OSError al morir el productor, como PyAudio"
        return False, (f"devolvió {len(datos)} bytes en vez de avisar: "
                       f"MEXA quedaría sorda sin enterarse")
    finally:
        cap.close()


def caso_is_active() -> tuple[bool, str]:
    """is_active() refleja si el productor sigue vivo."""
    cap = CapturaPipeWire(_productor())
    try:
        if not cap.is_active():
            return False, "reportó inactivo con el productor vivo"
        cap._proc.kill()
        cap._proc.wait()
        if cap.is_active():
            return False, "reportó activo con el productor muerto"
        return True, "vivo → True, muerto → False"
    finally:
        cap.close()


def caso_eleccion_de_nodo() -> tuple[bool, str]:
    """Prefiere el micrófono SIN eco; degrada al crudo si el AEC no está."""
    con_aec = elegir_nodo(existe=lambda n: True,
                          entrada=lambda: [PUERTO_MIC])
    if con_aec != NODO_AEC:
        return False, f"con AEC disponible y bien cableado eligió {con_aec}"
    sin_aec = elegir_nodo(existe=lambda n: n != NODO_AEC)
    if sin_aec != NODO_CRUDO:
        return False, f"sin AEC eligió {sin_aec} en vez del micrófono crudo"
    return True, "AEC si está, crudo si no (MEXA no se queda muda)"


def caso_aec_mal_cableado_se_repara() -> tuple[bool, str]:
    """Si el AEC quedó enganchado a otro micrófono, se reconecta y se usa.

    Es la carrera de arranque: el módulo carga junto con el daemon, antes
    de que los dispositivos estén publicados, y WirePlumber lo engancha al
    dispositivo por defecto de ese instante.
    """
    estado = {"origen": ["bluez_input.AA:BB:CC:capture_MONO"]}

    def reparar():
        estado["origen"] = [PUERTO_MIC]
        return True

    nodo = elegir_nodo(existe=lambda n: True,
                       entrada=lambda: estado["origen"],
                       reparar=reparar)
    if nodo != NODO_AEC:
        return False, f"reparó el cableado pero igual eligió {nodo}"
    return True, "detecta el enganche equivocado, reconecta y usa el AEC"


def caso_aec_mal_cableado_sin_arreglo() -> tuple[bool, str]:
    """Si no se puede reparar, se lee el micrófono CRUDO. Nunca silencio.

    Este es el caso que justifica todo el chequeo: un AEC enganchado al
    dispositivo equivocado no da error, entrega CEROS. MEXA quedaría
    completamente sorda en plena exposición y nada lo avisaría.
    """
    nodo = elegir_nodo(existe=lambda n: True,
                       entrada=lambda: ["bluez_input.AA:BB:CC:capture_MONO"],
                       reparar=lambda: False)
    if nodo != NODO_CRUDO:
        return False, (f"con el AEC mal cableado y sin arreglo eligió {nodo}: "
                       f"MEXA leería silencio digital")
    return True, "cae al micrófono crudo en vez de quedarse sorda"


_CASOS = [
    ("lectura de largo exacto",    caso_lectura_completa),
    ("continuidad entre lecturas", caso_continuidad),
    ("descarte de lo acumulado",   caso_descarte),
    ("muerte del productor",       caso_productor_muerto),
    ("is_active",                  caso_is_active),
    ("elección de nodo",           caso_eleccion_de_nodo),
    ("AEC mal cableado, reparado", caso_aec_mal_cableado_se_repara),
    ("AEC mal cableado, sin arreglo", caso_aec_mal_cableado_sin_arreglo),
]


def main() -> int:
    print("\n=== CONTRATO DE LA CAPTURA POR PIPEWIRE ===\n")
    fallos = 0
    for nombre, caso in _CASOS:
        try:
            ok, detalle = caso()
        except Exception as e:
            ok, detalle = False, f"excepción: {type(e).__name__}: {e}"
        print(f"  [{'OK ' if ok else 'MAL'}] {nombre:<28} {detalle}")
        fallos += not ok

    print(f"\n  {len(_CASOS) - fallos}/{len(_CASOS)} casos en verde.")
    if fallos:
        print("  La captura NO cumple su contrato: no conectarla a MEXA.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
