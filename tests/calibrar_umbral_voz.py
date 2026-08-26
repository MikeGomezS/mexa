"""
Verificación en hardware del UMBRAL DE VOZ ADAPTATIVO de MEXA.

tests/test_umbral_adaptativo.py prueba la REGLA con audio sintético. Este
script prueba la SALA REAL: mide el ruido de fondo donde MEXA va a trabajar
y después mide cuánto llega la voz de un visitante a esa misma distancia.
Son dos números, y lo único que importa es la DISTANCIA entre ellos.

POR QUÉ HACE FALTA CORRERLO EN LA EXPO: el umbral se calcula solo, pero
nadie garantiza que la voz del visitante lo supere. Si el ruido del
pabellón sube tanto que la voz queda por debajo, no hay constante que lo
arregle — hay que acercar el micrófono o cambiarlo por un array. Este
script es la forma de enterarse ANTES de la demo y no durante.

USO (MEXA encendida y en su lugar definitivo, proyector prendido):
  python3 tests/calibrar_umbral_voz.py

Ctrl+C corta en cualquier momento.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audioop
import time

import modulos.modulo_audio as audio
import modulos.vad as vad

_MEDICION_S = 4.0   # cuánto dura cada medición


def _medir(segundos: float) -> list[int]:
    """Devuelve el RMS de cada chunk durante ese tiempo.

    Remuestrea a 16 kHz antes de medir porque es la señal que ve el VAD:
    medir a 44.1 kHz daría un ruido más alto (toda la energía por encima
    de 8 kHz, que el VAD nunca llega a oír) y un umbral inflado."""
    stream = audio._obtener_stream()
    audio._vaciar_buffer(stream)
    _, native_rate = audio._obtener_dispositivo()
    muestras, estado, fin = [], None, time.time() + segundos
    while time.time() < fin:
        data = stream.read(audio._CHUNK, exception_on_overflow=False)
        if native_rate != audio._VOSK_RATE:
            data, estado = audioop.ratecv(data, 2, 1, native_rate,
                                          audio._VOSK_RATE, estado)
        muestras.append(audioop.rms(data, 2))
    return muestras


def _informe(nombre: str, muestras: list[int]) -> None:
    ordenadas = sorted(muestras)
    p20 = ordenadas[int(0.20 * (len(ordenadas) - 1))]
    p80 = ordenadas[int(0.80 * (len(ordenadas) - 1))]
    print(f"  {nombre:<22} p20 {p20:>6}   mediana {ordenadas[len(ordenadas)//2]:>6}   "
          f"p80 {p80:>6}   pico {max(ordenadas):>6}")


def main() -> int:
    print("=" * 62)
    print("  MEXA — Calibración del umbral de voz en la sala real")
    print("=" * 62)

    input("\n1) SILENCIO. Que nadie hable. Enter para medir la sala...")
    sala = _medir(_MEDICION_S)
    _informe("ruido de sala", sala)

    piso   = vad.piso_desde_muestras(sala)
    umbral = vad.umbral_desde_piso(piso)
    print(f"\n  → piso {int(piso)} RMS × factor {vad._FACTOR_UMBRAL} = "
          f"umbral de energía {umbral}")
    if vad.vad_neural_disponible():
        print(f"  → VAD en producción: {vad.DetectorVozNeural(piso=piso)}")
    else:
        print("  → Silero NO instalado: corre el VAD de energía.")

    input("\n2) Pará donde va a estar el visitante y hablá NORMAL "
          "hasta que corte. Enter...")
    normal = _medir(_MEDICION_S)
    _informe("voz normal", normal)

    input("\n3) Ahora hablá BAJITO, como un visitante tímido. Enter...")
    bajo = _medir(_MEDICION_S)
    _informe("voz baja", bajo)

    print("\n" + "-" * 62)
    problemas = []
    for nombre, muestras in (("normal", normal), ("baja", bajo)):
        ordenadas = sorted(muestras)
        p80 = ordenadas[int(0.80 * (len(ordenadas) - 1))]
        margen = p80 / umbral if umbral else 0
        if margen >= 1.3:
            print(f"  OK       voz {nombre}: supera el umbral por {margen:.1f}×")
        elif margen >= 1.0:
            print(f"  JUSTO    voz {nombre}: apenas lo supera ({margen:.1f}×). "
                  f"Va a fallar cuando la sala suba.")
            problemas.append(nombre)
        else:
            print(f"  NO LLEGA voz {nombre}: queda por DEBAJO del umbral "
                  f"({margen:.1f}×). MEXA no la va a oír.")
            problemas.append(nombre)

    print("-" * 62)
    if not problemas:
        print("\nLa sala está bien para MEXA: hay margen entre el ruido y la voz.")
        return 0

    print("\nQUÉ HACER, en este orden (lo primero que se pueda):")
    print("  1. Acercar el micrófono al visitante. Duplicar la distancia")
    print("     cuadruplica la pérdida de señal: es la palanca más grande")
    print("     y no cuesta nada.")
    print("  2. Mover a MEXA lejos de la fuente de ruido (parlantes de otro")
    print("     stand, pasillo principal, aire acondicionado).")
    print("  3. Si el ruido no baja: con UN micrófono mono ya no queda margen.")
    print("     Silero ya está haciendo todo lo que puede hacerse sin saber")
    print("     de DÓNDE viene el sonido. El siguiente paso real es un array,")
    print("     que separa por dirección y no por volumen.")
    print("\nNO toques _FACTOR_UMBRAL ni _FACTOR_ENERGIA_NEURAL para tapar esto:")
    print("esos números están fijados por tests/test_umbral_adaptativo.py y")
    print("bajarlos devuelve el bug de quedarse PEGADO con la sala.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
