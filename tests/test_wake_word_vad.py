# ============================================================
#  MEXA — ¿SOBREVIVE EL WAKE WORD AL VAD?
#
#  POR QUÉ EXISTE ESTE TEST: tests/test_activacion.py mide si Vosk
#  RECONOCE las frases de activación, pero le da el PCM directo a
#  los recognizers — nunca pasa por `_escuchar()` ni por el VAD.
#  Cuando se cambió el detector de voz, el camino de despertar
#  —la puerta de entrada de toda la visita— quedó sin cubrir.
#
#  LO QUE SE TEME, concretamente: el VAD corta la escucha 1.5 s
#  después de que alguien deja de hablar. En una sala con murmullo,
#  el murmullo mismo puede abrir y cerrar una escucha ANTES de que
#  el visitante diga "comencemos". Y entre escucha y escucha
#  `_vaciar_buffer()` TIRA el audio acumulado: medido, 219 ms
#  (97 ms de FinalResult sobre 8 s + 122 ms de crear los dos
#  recognizers). Un "comencemos" que arranque ahí pierde su primera
#  sílaba y MEXA no se despierta.
#
#  CÓMO SE AÍSLA LA VARIABLE: cada caso se decodifica DOS veces
#  sobre el mismo audio — una por el camino real (bucle de
#  `esperar_activacion` con VAD y huecos) y otra dándole todo el
#  PCM directo a los recognizers, sin VAD. Si el control reconoce
#  y el camino real no, la culpa es del VAD. Si el control tampoco,
#  es el reconocedor o la relación señal-ruido, y este test no
#  tiene nada que decir al respecto. Sin ese control, cualquier
#  falla de Vosk se leería como una falla del VAD.
#
#  No necesita micrófono: un stream falso sirve la línea de tiempo
#  y mueve un reloj simulado, así el test mide la REGLA y no la
#  velocidad de la máquina donde corre.
#
#  Correr con:  python3 -m tests.test_wake_word_vad
# ============================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audioop
import json

from vosk import KaldiRecognizer

import modulos.modulo_audio as audio
import modulos.vad as vad
from modulos.dialogo import _PALABRAS_ACTIVACION, _dijo
from modulos.modulo_audio import _VOSK_RATE, _cargar_modelo, modelo_disponible

from tests.test_umbral_adaptativo import (_DC_MICROFONO, _SALAS, _a_rms,
                                          _babble, _ruido, _sintetizar)

# Medido en esta Pi: FinalResult sobre 8 s (97 ms) + crear los dos
# recognizers nuevos (122 ms). Es audio real que el micrófono capta y
# que `_vaciar_buffer()` descarta antes de la escucha siguiente.
_HUECO_S = 0.219

_FRASE     = "comencemos"   # el wake word en español
_RMS_VOZ   = 3500           # visitante de frente: por encima de TODAS las salas
_TIMEOUT   = 8              # el mismo que usa esperar_activacion()
_ESCUCHAS_MAX = 4           # cuántas vueltas del bucle se simulan

# Dónde arranca el wake word dentro de la línea de tiempo. Dos
# posiciones a propósito: una temprana (cae dentro de la primera
# escucha) y una tardía (puede caer después de que el VAD haya cortado,
# o justo en el hueco entre escuchas).
_ARRANQUES_S = (1.0, 4.5)

_COLA_S = 10.0   # ruido después del wake word, para que el bucle siga


class _Reloj:
    """Reloj simulado: lo mueve el stream, no el sistema operativo."""

    def __init__(self):
        self.ahora = 0.0

    def time(self) -> float:
        return self.ahora

    def avanzar(self, segundos: float) -> None:
        self.ahora += segundos


class _StreamFalso:
    """Micrófono de mentira: sirve la línea de tiempo y mueve el reloj.

    Cumple sólo lo que `_escuchar()` le pide: read, is_active y
    get_read_available. Nada más — un doble no tiene que ser un
    micrófono, tiene que ser lo que el código bajo prueba consume.
    """

    def __init__(self, pcm: bytes, reloj: _Reloj):
        self.pcm, self.reloj, self.pos = pcm, reloj, 0

    def read(self, n, exception_on_overflow=False) -> bytes:
        ancho = n * 2
        data  = self.pcm[self.pos:self.pos + ancho]
        self.pos += ancho
        if len(data) < ancho:                       # se acabó la escena
            data += b"\x00\x00" * ((ancho - len(data)) // 2)
        self.reloj.avanzar(n / _VOSK_RATE)
        return data

    def is_active(self) -> bool:
        return True

    def get_read_available(self) -> int:
        return 0

    def descartar(self, segundos: float) -> None:
        """El audio que se pierde entre escucha y escucha."""
        self.pos += int(segundos * _VOSK_RATE) * 2
        self.reloj.avanzar(segundos)

    @property
    def agotado(self) -> bool:
        return self.pos >= len(self.pcm)


def _escena(rms_sala: int, rms_pico, tipo: str, arranque_s: float) -> bytes:
    """Ruido de sala con el wake word encima, empezando en `arranque_s`."""
    voz = _a_rms(_sintetizar(_FRASE), _RMS_VOZ)
    n_voz = len(voz) // 2
    n_antes = int(arranque_s * _VOSK_RATE)
    n_total = n_antes + n_voz + int(_COLA_S * _VOSK_RATE)

    sala = (_babble(n_total, rms_sala, 0) if tipo == "voces"
            else _ruido(n_total, rms_sala, rms_pico, semilla=11))

    # La voz se suma sobre la sala, en su lugar de la línea de tiempo.
    silencio = b"\x00\x00" * n_antes
    cola     = b"\x00\x00" * (n_total - n_antes - n_voz)
    # Con el offset DC del micrófono real: `_escuchar()` lo saca solo.
    return audioop.bias(audioop.add(sala, silencio + voz + cola, 2),
                        2, _DC_MICROFONO)


def _recognizers(idiomas):
    return {i: KaldiRecognizer(_cargar_modelo(i), _VOSK_RATE) for i in idiomas}


def _control_sin_vad(pcm: bytes, idiomas) -> str:
    """Decodifica TODO el audio sin VAD: el máximo que Vosk puede dar acá.

    Es la vara contra la que se mide el camino real. Si acá no aparece el
    wake word, ningún VAD lo podía salvar."""
    salida = []
    for idioma, rec in _recognizers(idiomas).items():
        rec.AcceptWaveform(pcm)
        salida.append(json.loads(rec.FinalResult()).get("text", "").strip())
    return " | ".join(salida)


def _camino_real(pcm: bytes, idiomas, piso: float) -> tuple[bool, int, str]:
    """Simula el bucle de `esperar_activacion()` sobre esa línea de tiempo.

    Devuelve (despertó, en qué escucha, qué se oyó en total)."""
    reloj  = _Reloj()
    stream = _StreamFalso(pcm, reloj)

    # El VAD arranca con la sala ya calibrada, como después de
    # `calibrar_ruido_ambiente()` en el arranque real.
    vad._ventana_piso.clear()
    vad._piso_ruido = piso

    originales = (audio.time, audio._obtener_stream,
                  audio._obtener_dispositivo, audio._vaciar_buffer)
    audio.time                 = reloj
    audio._obtener_stream      = lambda: stream
    audio._obtener_dispositivo = lambda: (0, _VOSK_RATE)
    audio._vaciar_buffer       = lambda s: s.descartar(_HUECO_S)
    try:
        oido = []
        for intento in range(1, _ESCUCHAS_MAX + 1):
            textos = audio.escuchar_multilingue(timeout=_TIMEOUT, idiomas=idiomas)
            oido.extend(t for t in textos.values() if t)
            if any(_dijo(t, _PALABRAS_ACTIVACION) for t in textos.values()):
                return True, intento, " | ".join(oido) or "(nada)"
            if stream.agotado:
                break
        return False, intento, " | ".join(oido) or "(nada)"
    finally:
        (audio.time, audio._obtener_stream,
         audio._obtener_dispositivo, audio._vaciar_buffer) = originales


def main() -> int:
    """Contrato del test, por severidad:

    CRÍTICO  → el control SIN VAD reconoce el wake word y el camino real
               NO. Eso es el VAD comiéndose el despertar: MEXA se queda
               dormida con el visitante hablándole de frente.
    LÍMITE   → el control tampoco lo reconoce. La culpa es del
               reconocedor o de la relación señal-ruido, no del VAD; este
               test no opina de eso (para eso está test_activacion.py).

    La voz está a 3500 RMS en TODAS las salas —por encima del ruido
    incluso en la peor— justamente para que ninguna falla se pueda
    excusar con "es que no se oía".
    """
    idiomas = [i for i in ("es", "en") if modelo_disponible(i)]
    if not idiomas:
        print("[!] No hay modelos Vosk instalados.")
        return 1

    criticos, limites, total = [], [], 0
    print(f"wake word '{_FRASE}' a {_RMS_VOZ} RMS, hueco entre escuchas {_HUECO_S*1000:.0f} ms\n")
    print(f"{'sala':<17} {'arranque':>9}  {'sin VAD':<9} {'con VAD':<20}")
    print("-" * 62)

    for nombre_sala, rms_sala, rms_pico, tipo in _SALAS:
        for arranque in _ARRANQUES_S:
            pcm = _escena(rms_sala, rms_pico, tipo, arranque)

            control  = _control_sin_vad(pcm, idiomas)
            sin_vad  = _dijo(control, _PALABRAS_ACTIVACION)

            # El piso que tendría MEXA tras calibrar esa sala.
            piso = vad.piso_desde_muestras(
                [audioop.rms(pcm[i:i + 8192], 2)
                 for i in range(0, int(arranque * _VOSK_RATE) * 2 - 8192, 8192)]
            ) if arranque >= 0.5 else float(rms_sala)

            desperto, escucha, oido = _camino_real(pcm, idiomas, piso)

            total += 1
            caso = (f"{nombre_sala} + wake word en t={arranque}s → "
                    f"sin VAD: {'lo reconoce' if sin_vad else 'no lo reconoce'} | "
                    f"con VAD: {'despertó' if desperto else 'NO despertó'} "
                    f"(oyó: {oido})")

            if desperto:
                estado = "PASA"
            elif sin_vad:
                estado = "CRÍTICO"; criticos.append(caso)
            else:
                estado = "LÍMITE"; limites.append(caso)

            print(f"{nombre_sala:<17} {arranque:>8}s  "
                  f"{'sí' if sin_vad else 'no':<9} "
                  f"{('sí, escucha ' + str(escucha)) if desperto else 'NO':<20} {estado}")

    print("-" * 62)
    print(f"{total - len(criticos) - len(limites)}/{total} despertaron, "
          f"{len(limites)} no llegan ni sin VAD, {len(criticos)} críticos\n")
    for c in limites:
        print(f"  LÍMITE:  {c}")
    for c in criticos:
        print(f"  CRÍTICO: {c}")
    return 1 if criticos else 0


if __name__ == "__main__":
    sys.exit(main())
