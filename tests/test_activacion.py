# ============================================================
#  MEXA — Verificación de la palabra de activación (wake word)
#
#  Un wake word se juzga por sus FALSOS POSITIVOS, no por sus
#  aciertos. MEXA vive en una sala con gente hablando todo el
#  día: despertarse de más es peor que no despertarse, porque
#  arranca sola frente a alguien que ni la estaba mirando.
#
#  Por eso este test mide tres cosas:
#    1. que las frases de activación despierten (en ambos idiomas)
#    2. que la charla normal de museo NO despierte
#    3. que un modelo no fuerce un despertar con voz del OTRO idioma
#
#  Este test ya pagó su costo: con gramática cerrada en el despertar,
#  "vamos a la otra sala" se decodificaba como "comenzamos" y MEXA se
#  despertaba sola. Por eso el wake word escucha vocabulario abierto.
#
#  Correr con:  python3 tests/test_activacion.py
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

from piper.config import SynthesisConfig
from piper.voice import PiperVoice

from modulos.dialogo import _ACTIVACION, _PALABRAS_ACTIVACION, _dijo
from modulos.modulo_audio import _VOSK_RATE, _cargar_modelo, modelo_disponible

_VOCES = {
    "es": "media/tts/es_MX-claude-high.onnx",
    "en": "media/tts/en_US-lessac-high.onnx",
}
_RUIDO    = 0.06   # ruido de sala
_GANANCIA = 0.5    # atenuación por distancia al micrófono

# (frase, voz, debe_despertar)
CASOS = [
    # 1. Deben despertar
    ("comencemos",                    "es", True),
    ("comenzar",                      "es", True),
    ("let's begin",                   "en", True),
    ("begin the tour",                "en", True),
    ("I'm ready",                     "en", True),
    # 2. Charla de museo: NO deben despertar
    ("let's go",                      "en", False),   # ← lo que casi agregamos
    ("let's go to the next room",     "en", False),
    ("come on let's go",              "en", False),
    ("where is the exit",             "en", False),
    ("look at this one",              "en", False),
    ("vamos a la otra sala",          "es", False),
    ("mira esta pirámide",            "es", False),
    ("qué bonito museo",              "es", False),
    # 3. Cruce de idiomas: voz inglesa contra el modelo español y viceversa
    ("the beginning of the empire",   "en", False),
    ("comenzaron a construir",        "es", False),
    # 4. Vecindario de "begin": la clave suelta es la más floja del set,
    #    así que se la estresa con lo que más se le parece. La frontera
    #    de palabra (\b) es lo único que separa "begin" de "begins".
    ("the tour begins at noon",       "en", False),
    ("the video is about to begin",   "en", False),
    ("we should begin with the mayas","en", False),
    ("beginners are welcome here",    "en", False),
    # 5. Vecindario de "I'm ready"
    ("are you ready to go",           "en", False),
    ("the kids are ready",            "en", False),
]

# Piper es ESTOCÁSTICO por defecto (VITS inyecta ruido en duración y
# timbre): la misma frase suena distinta en cada corrida y el test se
# vuelve intermitente. Con ruido en cero la síntesis es reproducible
# bit a bit. La variabilidad realista la aporta _degradar(), que sí
# controlamos con semilla fija.
_SINTESIS_DETERMINISTA = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0,
                                         length_scale=1.0)

_cache: dict[str, PiperVoice] = {}


def _sintetizar(texto: str, voz: str) -> bytes:
    if voz not in _cache:
        _cache[voz] = PiperVoice.load(_VOCES[voz])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        _cache[voz].synthesize_wav(texto, wav, syn_config=_SINTESIS_DETERMINISTA)
    buf.seek(0)
    with wave.open(buf, "rb") as wav:
        pcm, rate, ancho = wav.readframes(wav.getnframes()), wav.getframerate(), wav.getsampwidth()
    if rate != _VOSK_RATE:
        pcm, _ = audioop.ratecv(pcm, ancho, 1, rate, _VOSK_RATE, None)
    return pcm


def _degradar(pcm: bytes) -> bytes:
    """Micrófono lejano + ruido de sala. Determinista (semilla fija)."""
    pcm = audioop.mul(pcm, 2, _GANANCIA)
    n = len(pcm) // 2
    random.seed(7)
    amp = int(32767 * _RUIDO)
    sucio = [max(-32768, min(32767, m + random.randint(-amp, amp)))
             for m in struct.unpack(f"<{n}h", pcm)]
    return struct.pack(f"<{n}h", *sucio)


def _despierta(pcm: bytes) -> tuple[bool, dict[str, str]]:
    """Replica esperar_activacion() sobre audio dado, sin micrófono."""
    import json
    from vosk import KaldiRecognizer
    textos = {}
    for idioma in _ACTIVACION:
        if not modelo_disponible(idioma):
            continue
        rec = KaldiRecognizer(_cargar_modelo(idioma), _VOSK_RATE)
        rec.AcceptWaveform(pcm)
        textos[idioma] = json.loads(rec.FinalResult()).get("text", "").strip()
    return any(_dijo(t, _PALABRAS_ACTIVACION) for t in textos.values()), textos


def main() -> int:
    """Contrato del test, por severidad:

    CRÍTICO  → despertó cuando NO debía (falso positivo), o no despertó
               con audio limpio. Un falso positivo es el error caro:
               MEXA gira y arranca su presentación sola, frente a alguien
               que ni la estaba mirando.
    TOLERADO → no despertó con audio degradado. El visitante repite la
               frase. Molesto, no vergonzoso.

    Un wake word se juzga por sus falsos positivos. Los falsos negativos
    los arregla el usuario repitiendo; los falsos positivos, nadie.
    """
    criticos, tolerados, total = [], [], 0
    for frase, voz, esperado in CASOS:
        limpio = _sintetizar(frase, voz)
        for condicion, pcm in (("limpio", limpio), ("degradado", _degradar(limpio))):
            obtenido, textos = _despierta(pcm)
            total += 1
            oido = " | ".join(f"{i}:{t or '-'}" for i, t in textos.items())
            caso = (f"{frase!r} [{condicion}] despierta={obtenido} "
                    f"(esperado {esperado})  oído: {oido}")
            if obtenido == esperado:
                estado = "PASA"
            elif obtenido and not esperado:
                estado = "CRÍTICO"; criticos.append(caso)   # falso positivo, siempre grave
            elif condicion == "degradado":
                estado = "TOLERA"; tolerados.append(caso)   # no despertó con ruido fuerte
            else:
                estado = "CRÍTICO"; criticos.append(caso)   # no despertó ni en limpio
            print(f"{estado:8} {caso}")

    print(f"\n{total - len(criticos) - len(tolerados)}/{total} exactos, "
          f"{len(tolerados)} tolerados, {len(criticos)} críticos")
    for c in tolerados:
        print(f"  TOLERADO: {c}")
    for c in criticos:
        print(f"  CRÍTICO:  {c}")
    return 1 if criticos else 0


if __name__ == "__main__":
    sys.exit(main())
