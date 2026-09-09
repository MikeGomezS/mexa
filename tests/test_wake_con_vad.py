# ============================================================
#  MEXA — ¿Cortar antes hace que se despierte sola?
#
#  POR QUÉ EXISTE, SI YA ESTÁ test_activacion.py. Ese test alimenta el
#  PCM COMPLETO directo al KaldiRecognizer: no pasa por `_escuchar` ni
#  por el VAD. Sirve para juzgar el vocabulario de activación, pero es
#  CIEGO a cuánto silencio espera MEXA antes de darse por contestada.
#
#  Y ese parámetro sí puede fabricar falsos despertares. El riesgo es
#  concreto y está documentado en dialogo.py: al recortar el audio, el
#  decodificador ve una frase INCOMPLETA. "vamos a la otra sala" cortada
#  a la mitad tiene más chances de caer en "comencemos" que entera,
#  porque le faltan las palabras que la desambiguaban.
#
#  Este test replica `_escuchar` de verdad: alimenta los recognizers
#  chunk a chunk HASTA QUE EL VAD CORTA, así Vosk ve exactamente el
#  audio truncado que vería en la sala. Después compara la espera actual
#  contra la vieja de 1.5 s.
#
#  VEREDICTO: falla si aparece un falso despertar que con 1.5 s no
#  pasaba. No despertar con audio degradado se tolera — el visitante
#  repite. Despertarse solo, no lo arregla nadie.
#
#  Tarda varios minutos: sintetiza 42 frases y las decodifica dos veces
#  con dos modelos.
#
#  Correr con:  python3 tests/test_wake_con_vad.py
# ============================================================

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vosk import KaldiRecognizer

import test_activacion as T
from modulos import vad
from modulos.dialogo import _ACTIVACION, _PALABRAS_ACTIVACION, _dijo
from modulos.modulo_audio import _VOSK_RATE, _cargar_modelo, modelo_disponible

_CHUNK      = 512     # lo que exige Silero: 32 ms a 16 kHz
_SILENCIO_VIEJO = 1.5 # el valor anterior, como referencia
_RUIDO_SALA = 140     # RMS del silencio sintético, típico de la exhibición


def _silencio(segundos: float) -> bytes:
    random.seed(11)
    return b"".join(int(random.gauss(0, _RUIDO_SALA)).to_bytes(2, "little", signed=True)
                    for _ in range(int(segundos * _VOSK_RATE)))


def _despierta(pcm: bytes, silencio: float) -> tuple[bool, dict[str, str]]:
    """Como `_escuchar`: corta donde diga el VAD y decodifica sólo hasta ahí."""
    escena = _silencio(0.4) + pcm + _silencio(3.0)
    detector = vad.crear_detector(silencio=silencio)
    recs = {i: KaldiRecognizer(_cargar_modelo(i), _VOSK_RATE)
            for i in _ACTIVACION if modelo_disponible(i)}

    for i in range(0, len(escena) - _CHUNK * 2, _CHUNK * 2):
        chunk = escena[i:i + _CHUNK * 2]
        if detector.observar(chunk, (i / 2) / _VOSK_RATE):
            break
        for rec in recs.values():
            rec.AcceptWaveform(chunk)

    textos = {clave: json.loads(rec.FinalResult()).get("text", "").strip()
              for clave, rec in recs.items()}
    return any(_dijo(t, _PALABRAS_ACTIVACION) for t in textos.values()), textos


def main() -> int:
    actual = vad._SILENCIO_SEG
    print(f"Espera actual del wake word: {actual}s (antes {_SILENCIO_VIEJO}s)\n")

    nuevos_fp, perdidos, total = [], [], 0
    for frase, voz, esperado in T.CASOS:
        limpio = T._sintetizar(frase, voz)
        for condicion, pcm in (("limpio", limpio), ("degradado", T._degradar(limpio))):
            total += 1
            viejo, _        = _despierta(pcm, _SILENCIO_VIEJO)
            nuevo, t_nuevo  = _despierta(pcm, actual)

            if nuevo and not esperado:
                estado = "CRÍTICO" if not viejo else "ya pasaba"
                if not viejo:
                    nuevos_fp.append((frase, condicion, t_nuevo))
            elif esperado and viejo and not nuevo:
                estado = "PERDIDO"
                perdidos.append((frase, condicion, t_nuevo))
            else:
                estado = "ok"
            marca = " " if viejo == nuevo else "*"
            print(f"{marca}{estado:10} {frase[:34]:36s} {condicion:10s} "
                  f"esperado={str(esperado):5s} {_SILENCIO_VIEJO}s={str(viejo):5s} "
                  f"{actual}s={str(nuevo):5s}")

    print(f"\n{total} casos pasados por el VAD real")
    print(f"Falsos despertares NUEVOS: {len(nuevos_fp)}")
    for frase, cond, textos in nuevos_fp:
        print(f"   {frase!r} [{cond}] -> {textos}")
    print(f"Despertares perdidos por truncar: {len(perdidos)}")
    for frase, cond, textos in perdidos:
        print(f"   {frase!r} [{cond}] -> {textos}")

    if nuevos_fp:
        print("\nFALLA: acortar la espera fabricó falsos despertares.")
        return 1
    print("\nTodo bien: acortar la espera no fabricó ningún falso despertar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
