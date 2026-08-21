# ============================================================
#  MEXA — Verificación de la selección de idioma por voz
#
#  Prueba el bug real: "English" pronunciado EN INGLÉS no se
#  reconocía, porque el único modelo Vosk era español.
#
#  No necesita micrófono ni humano: sintetiza cada respuesta con
#  la voz Piper del idioma correspondiente (en_US para el inglés,
#  es_MX para el español) y se la da a los mismos recognizers con
#  gramática cerrada que usa MEXA en producción.
#
#  OJO CON EL AUDIO LIMPIO: con TTS de estudio el modelo español
#  solito ya acertaba. El bug sólo aparece en condiciones de museo
#  (micrófono lejano, ruido de sala), donde el viejo pipeline oía
#  "web" en vez de "inglés". Por eso cada caso se prueba DOS veces:
#  limpio y degradado. Sin la versión degradada, este test pasaba
#  incluso con el código roto.
#
#  Correr con:  python3 -m tests.test_idioma
# ============================================================

import audioop
import io
import os
import random
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vosk import KaldiRecognizer
from piper.config import SynthesisConfig
from piper.voice import PiperVoice

from modulos.modulo_audio import (_GRAMATICA_IDIOMA, _VOSK_RATE, _cargar_modelo,
                                  decidir_idioma, modelo_disponible)

_VOCES = {
    "es": "media/tts/es_MX-claude-high.onnx",
    "en": "media/tts/en_US-lessac-high.onnx",
}

# (texto, voz_que_lo_pronuncia, idioma_esperado)
CASOS = [
    ("English",  "en", "en"),   # ← el bug reportado
    ("Spanish",  "en", "es"),
    ("español",  "es", "es"),
    ("inglés",   "es", "en"),
    ("English",  "es", "en"),   # angloparlante con acento mexicano
]

_RUIDO    = 0.06   # amplitud del ruido blanco (fracción de fondo de escala)
_GANANCIA = 0.5    # atenuación por distancia al micrófono

# Piper es ESTOCÁSTICO por defecto (VITS inyecta ruido en duración y
# timbre): la misma frase suena distinta en cada corrida y el test se
# vuelve intermitente. Con ruido en cero la síntesis es reproducible
# bit a bit. La variabilidad realista la aporta _degradar(), que sí
# controlamos con semilla fija.
_SINTESIS_DETERMINISTA = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0,
                                         length_scale=1.0)

_cache_voz: dict[str, PiperVoice] = {}


def _sintetizar(texto: str, voz: str) -> bytes:
    """Devuelve PCM 16-bit mono a 16 kHz, listo para Vosk."""
    if voz not in _cache_voz:
        _cache_voz[voz] = PiperVoice.load(_VOCES[voz])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        _cache_voz[voz].synthesize_wav(texto, wav, syn_config=_SINTESIS_DETERMINISTA)
    buf.seek(0)
    with wave.open(buf, "rb") as wav:
        pcm, rate, ancho = wav.readframes(wav.getnframes()), wav.getframerate(), wav.getsampwidth()
    if rate != _VOSK_RATE:
        import audioop
        pcm, _ = audioop.ratecv(pcm, ancho, 1, rate, _VOSK_RATE, None)
    return pcm


def _degradar(pcm: bytes) -> bytes:
    """Simula el micrófono de la exhibición: volumen bajo + ruido de sala.

    Determinista (semilla fija) para que el test no sea intermitente."""
    pcm = audioop.mul(pcm, 2, _GANANCIA)
    n = len(pcm) // 2
    random.seed(7)
    amp = int(32767 * _RUIDO)
    sucio = [max(-32768, min(32767, m + random.randint(-amp, amp)))
             for m in struct.unpack(f"<{n}h", pcm)]
    return struct.pack(f"<{n}h", *sucio)


def _reconocer(pcm: bytes) -> dict[str, str]:
    """Corre los dos modelos con gramática cerrada sobre el mismo audio."""
    import json
    textos = {}
    for idioma, gramatica in _GRAMATICA_IDIOMA.items():
        if not modelo_disponible(idioma):
            continue
        rec = KaldiRecognizer(_cargar_modelo(idioma), _VOSK_RATE, gramatica)
        rec.AcceptWaveform(pcm)
        textos[idioma] = json.loads(rec.FinalResult()).get("text", "").strip()
    return textos


def main() -> int:
    """Contrato del test, por severidad:

    CRÍTICO  → eligió el idioma EQUIVOCADO, o falló en audio limpio.
               Arranca la visita entera en el idioma que no era.
    TOLERADO → no decidió (None) en audio degradado. Es el camino de
               reintento que `_seleccionar_idioma` ya contempla: MEXA
               repregunta y el visitante repite. Cuesta 3 segundos.

    La distinción no es para maquillar el rojo: es que equivocarse y
    repreguntar tienen costos distintos, y el diseño elige repreguntar.
    """
    criticos, tolerados, total = [], [], 0
    for texto, voz, esperado in CASOS:
        limpio = _sintetizar(texto, voz)
        for condicion, pcm in (("limpio", limpio), ("degradado", _degradar(limpio))):
            obtenido = decidir_idioma(_reconocer(pcm))
            total += 1
            caso = f"'{texto}' en voz '{voz}' [{condicion}] → esperado {esperado}, obtenido {obtenido}"
            if obtenido == esperado:
                estado = "PASA"
            elif obtenido is None and condicion == "degradado":
                estado = "TOLERA"; tolerados.append(caso)
            else:
                estado = "CRÍTICO"; criticos.append(caso)
            print(f"{estado:8} {caso}\n")

    print(f"{total - len(criticos) - len(tolerados)}/{total} exactos, "
          f"{len(tolerados)} tolerados (repregunta), {len(criticos)} críticos")
    for c in tolerados:
        print(f"  TOLERADO: {c}")
    for c in criticos:
        print(f"  CRÍTICO:  {c}")
    return 1 if criticos else 0


if __name__ == "__main__":
    sys.exit(main())
