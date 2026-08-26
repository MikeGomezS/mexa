# ============================================================
#  MEXA — Verificación del UMBRAL DE VOZ ADAPTATIVO
#
#  El VAD viejo comparaba la energía del micrófono contra un
#  número FIJO (300 RMS) calibrado en un cuarto tranquilo. Un
#  número fijo mide VOLUMEN, no voz, y no sobrevive al cambio de
#  sala: en una expo ruidosa el murmullo de fondo ya supera 300,
#  así que el VAD nunca cierra y Vosk transcribe ruido; y un
#  visitante que habla bajito no llega a 300, así que MEXA queda
#  sorda. Los dos modos de falla son del MISMO número.
#
#  Este test enfrenta TRES detectores sobre EXACTAMENTE el mismo
#  audio, en cinco salas y con dos volúmenes de voz:
#    - umbral FIJO 300 (el viejo),
#    - umbral ADAPTATIVO (energía, relativo al ruido medido),
#    - Silero VAD NEURONAL (decide por forma espectral).
#  No necesita micrófono: arma la línea de tiempo (ruido → habla
#  → ruido) con voz Piper real y ruido de sala determinista, y se
#  la da chunk a chunk a cada detector, con reloj simulado.
#
#  ES EL TEST QUE FIJA LAS CONSTANTES DEL VAD, y cada sala mata
#  una comodidad distinta del propio test:
#    - "expo con picos" fija `_FACTOR_UMBRAL` en 3.0. Con ruido
#      blanco parejo ganaba 1.8; con risas y carritos, cada pico
#      reinicia la cuenta de silencio y el VAD nunca cierra.
#    - "expo con voces" fija `_FACTOR_ENERGIA_NEURAL` en 2.0.
#      Contra murmullo de gente, Silero SOLO queda PEGADO —peor
#      que el umbral de energía— porque el murmullo ES voz.
#  Si alguien toca esos factores, que lo justifique acá.
#
#  OJO — LO QUE NINGÚN UMBRAL ARREGLA: cuando la voz llega al
#  micrófono MÁS DÉBIL que el ruido de la sala, no hay número que
#  la rescate; la información ya no está en la señal. Esos casos
#  se reportan como LÍMITE, no como falla, y son exactamente el
#  argumento del array de micrófonos (que separa por dirección,
#  no por volumen). Un test que los pintara de verde estaría
#  mintiendo sobre lo que este cambio puede dar.
#
#  LÍMITE QUE ESTE CAMBIO NO CRUZA: un pico de sala MÁS FUERTE
#  que el umbral sigue pareciendo voz, porque un VAD de energía
#  sólo sabe de volumen. Ahí se acaba lo que un número puede
#  hacer y empieza el trabajo de un VAD neuronal o de un array.
#
#  Correr con:  python3 tests/test_umbral_adaptativo.py
#  (NO con `python3 -m tests.…`: hay un paquete `tests` instalado
#   en site-packages que tapa a esta carpeta en esta máquina.)
# ============================================================

import io
import math
import os
import random
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audioop

from piper.config import SynthesisConfig
from piper.voice import PiperVoice

# Se importa `modulos.vad` y NO `modulos.modulo_audio` a propósito: el
# VAD no necesita Vosk, y importar el módulo de audio cargaría 200 MB de
# modelo para un test que no decodifica una sola palabra.
from modulos.vad import (_MIN_HABLA_SEG, _SILENCIO_SEG, DetectorVoz,
                         DetectorVozNeural, piso_desde_muestras, quitar_dc,
                         umbral_desde_piso, vad_neural_disponible)

_VOZ = "media/tts/es_MX-claude-high.onnx"

_RATE = 16000   # el VAD ve el audio YA remuestreado, igual que en producción

# En producción se leen chunks de 4096 muestras a 44.1 kHz (~93 ms) y se
# remuestrean a 16 kHz antes de llegar al VAD. El chunk que ve el VAD es
# ese mismo tramo, más corto en muestras: 4096 × 16000/44100 ≈ 1486.
# Se replica el número exacto porque de él depende cuántas ventanas de
# 512 muestras (32 ms) le tocan a Silero por chunk.
_CHUNK_TEST = int(4096 * _RATE / 44100)

_SILENCIO_PREVIO_S    = 2.0   # sala sola antes de que el visitante hable
_SILENCIO_POSTERIOR_S = 4.0   # margen para que el VAD tenga tiempo de cortar

# Piper es estocástico por defecto; con ruido en cero la síntesis es
# reproducible bit a bit y el test deja de ser intermitente.
_SINTESIS_DETERMINISTA = SynthesisConfig(noise_scale=0.0, noise_w_scale=0.0,
                                         length_scale=1.0)

_UMBRAL_FIJO_VIEJO = 300      # el número que este cambio reemplaza

# El iTalk-02 real mete este offset continuo (mediana medida sobre 4 s).
# Va en TODAS las escenas para que el test no trabaje con un micrófono
# más limpio que el que MEXA tiene de verdad: el DC no molesta a Vosk,
# pero le come 16% del margen al VAD si nadie lo saca.
_DC_MICROFONO = 250

# (nombre, RMS de fondo, RMS de los picos o None, tipo de ruido)
#
# LAS DOS ÚLTIMAS SALAS SON LAS QUE FIJAN LAS CONSTANTES, y cada una
# desarma una comodidad distinta del test:
#
#  - "expo con picos" mata los factores de energía bajos. Un ruido
#    blanco PAREJO casi no varía de chunk a chunk, así que cualquier
#    umbral apenas por encima del fondo lo esquiva y el test regala
#    factores chicos. Con risas y carritos, cada pico reinicia la cuenta
#    de silencio y el VAD queda PEGADO.
#
#  - "expo con voces" mata los umbrales de probabilidad bajos. El ruido
#    blanco es un adversario FÁCIL para una red: espectralmente es lo más
#    distinto de la voz que existe, así que Silero lo rechaza sin
#    esfuerzo y parece invencible a −11 dB de SNR. Pero el ruido real de
#    un pabellón es GENTE HABLANDO, que espectralmente ES voz. Ahí la
#    forma del espectro ya no distingue nada y lo único que separa al
#    visitante del stand de al lado es que está MÁS CERCA — o sea,
#    energía. Esta sala es la que obliga al detector a usar las dos cosas.
_SALAS = [
    ("sala silenciosa",  40, None,  "blanco"),  # el cuarto donde se calibró el 300
    ("sala normal",     250, None,  "blanco"),  # gente conversando a unos metros
    ("expo ruidosa",    900, None,  "blanco"),  # pabellón WRO en hora pico
    ("expo con picos",  900, 2600,  "blanco"),  # lo mismo, pero con risas y golpes
    ("expo con voces",  900, None,  "voces"),   # murmullo de gente: el caso real
    ("expo imposible", 3000, None,  "blanco"),  # el techo: sala que ya no debería subir más
]

# Frases ajenas con las que se fabrica el murmullo de fondo (babble):
# varias voces superpuestas y desfasadas dejan de ser inteligibles y se
# vuelven exactamente el ruido de un pabellón lleno.
_FRASES_AJENAS = [
    "el próximo equipo pasa a la mesa de jueces en cinco minutos",
    "mirá lo que hace ese robot cuando llega al final de la línea",
    "no encuentro el cargador y la batería está por quedarse sin nada",
    "buenos días a todos los participantes de la competencia",
]

_PICO_CADA_S = 1.2   # cada cuánto irrumpe un pico de sala
_PICO_DURA_S = 0.4   # cuánto dura

# (nombre, RMS al que llega la voz al micrófono)
_VOCES = [
    ("voz normal", 3500),   # visitante hablándole de frente a MEXA
    ("voz baja",    250),   # visitante tímido, o un niño, o desde lejos
]

_FRASE = "cuéntame sobre los mayas"

_cache_voz: dict[str, PiperVoice] = {}


def _sintetizar(texto: str) -> bytes:
    """Devuelve PCM 16-bit mono a 16 kHz de la frase dicha por Piper."""
    if _VOZ not in _cache_voz:
        _cache_voz[_VOZ] = PiperVoice.load(_VOZ)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        _cache_voz[_VOZ].synthesize_wav(texto, wav, syn_config=_SINTESIS_DETERMINISTA)
    buf.seek(0)
    with wave.open(buf, "rb") as wav:
        pcm, rate, ancho = wav.readframes(wav.getnframes()), wav.getframerate(), wav.getsampwidth()
    if rate != _RATE:
        pcm, _ = audioop.ratecv(pcm, ancho, 1, rate, _RATE, None)
    return pcm


def _a_rms(pcm: bytes, objetivo: int) -> bytes:
    """Escala el PCM para que llegue al micrófono con ese RMS."""
    actual = audioop.rms(pcm, 2)
    return audioop.mul(pcm, 2, objetivo / actual) if actual else pcm


def _babble(muestras: int, rms: int, desfase: int) -> bytes:
    """Murmullo de sala: varias voces ajenas superpuestas y desfasadas.

    Es el ruido que Silero NO puede rechazar por forma espectral, porque
    ES voz. Determinista: mismas frases, mismos desfases, misma semilla."""
    voces = [_sintetizar(f) for f in _FRASES_AJENAS]
    mezcla = b"\x00\x00" * muestras
    for k, voz in enumerate(voces):
        # Cada voz entra en un punto distinto del bucle y se repite hasta
        # cubrir el tramo pedido.
        salto = (desfase + k * 7919) % (len(voz) // 2)   # 7919 primo: desfases dispares
        tira  = (voz[salto * 2:] + voz * (1 + muestras * 2 // len(voz)))[:muestras * 2]
        mezcla = audioop.add(mezcla, tira, 2)
    return _a_rms(mezcla, rms)


def _ruido(muestras: int, rms: int, rms_pico: int | None,
           semilla: int, desfase: int = 0) -> bytes:
    """Ruido de sala con el RMS pedido, determinista.

    Ruido uniforme en [-a, a] tiene RMS a/√3, así que a = rms·√3. Si hay
    `rms_pico`, cada `_PICO_CADA_S` irrumpe un pico que dura
    `_PICO_DURA_S`. `desfase` mantiene los picos alineados a lo largo de
    los tres tramos de la escena, como si fueran una sola sala."""
    random.seed(semilla)
    periodo = int(_PICO_CADA_S * _RATE)
    ancho   = int(_PICO_DURA_S * _RATE)
    base    = int(rms * math.sqrt(3))
    pico    = int((rms_pico or rms) * math.sqrt(3))

    vals = []
    for i in range(muestras):
        en_pico = rms_pico and ((i + desfase) % periodo) < ancho
        amp     = pico if en_pico else base
        vals.append(max(-32768, min(32767, random.randint(-amp, amp))))
    return struct.pack(f"<{muestras}h", *vals)


def _escena(rms_sala: int, rms_pico: int | None, tipo: str,
            rms_voz: int) -> tuple[bytes, float, float]:
    """Arma ruido → habla+ruido → ruido. Devuelve (pcm, inicio, fin) del habla."""
    voz     = _a_rms(_sintetizar(_FRASE), rms_voz)
    n_previo, n_voz = int(_SILENCIO_PREVIO_S * _RATE), len(voz) // 2
    n_post  = int(_SILENCIO_POSTERIOR_S * _RATE)

    def sala(n, semilla, desfase):
        return (_babble(n, rms_sala, desfase) if tipo == "voces"
                else _ruido(n, rms_sala, rms_pico, semilla, desfase))

    previo  = sala(n_previo, 11, 0)
    durante = sala(n_voz,    22, n_previo)
    post    = sala(n_post,   33, n_previo + n_voz)

    pcm = previo + audioop.add(voz, durante, 2) + post
    inicio = _SILENCIO_PREVIO_S
    return audioop.bias(pcm, 2, _DC_MICROFONO), inicio, inicio + (n_voz / _RATE)


def _correr(pcm: bytes, detector) -> tuple[bool, float | None]:
    """Le pasa la escena al detector chunk a chunk con reloj simulado.

    El reloj es simulado y NO el del sistema: así el test mide la regla,
    no la velocidad de la máquina donde corre.

    Devuelve (detectó voz, segundo en que decidió cortar o None)."""
    ancho = _CHUNK_TEST * 2
    for i in range(0, len(pcm) - ancho, ancho):
        ahora = (i / 2) / _RATE
        # Mismo acondicionamiento que hace `_escuchar()` en producción.
        if detector.observar(quitar_dc(pcm[i:i + ancho]), ahora):
            return detector.hubo_voz, ahora
    return detector.hubo_voz, None


def _veredicto(detecto: bool, corto_en: float | None, fin_habla: float) -> str:
    """Traduce el comportamiento del VAD al modo de falla que produce."""
    if not detecto:
        return "SORDO"      # el visitante habló y MEXA no se enteró
    if corto_en is None:
        return "PEGADO"     # nunca cerró: se come el timeout y transcribe ruido
    if corto_en < fin_habla:
        return "CORTO"      # truncó al visitante a mitad de frase
    if corto_en - fin_habla > _SILENCIO_SEG + 0.5:
        return "LENTO"      # cerró tarde: silencios incómodos en la visita
    return "OK"


def main() -> int:
    """Contrato del test, por severidad:

    CRÍTICO  → el detector que está EN PRODUCCIÓN (el neuronal si está
               instalado, el adaptativo si no) se comporta peor que el que
               reemplaza, o queda PEGADO — que es transcribir ruido como si
               fuera una pregunta y contestarle a nadie delante del jurado.
    LÍMITE   → falla porque la voz llega al micrófono igual o más débil que
               el ruido de la sala. Con un micrófono mono eso no lo arregla
               ningún detector: hace falta separar por dirección (array).

    La distinción importa: si contamos los LÍMITE como fallas propias,
    vamos a seguir tocando constantes para arreglar algo que no vive
    en el software.
    """
    hay_neural = vad_neural_disponible()
    if not hay_neural:
        print("\n[!] Silero VAD no está instalado (falta media/vad/silero_vad.onnx):")
        print("    se compara sólo umbral fijo vs adaptativo.\n")

    criticos, limites, total = [], [], 0

    print(f"{'sala':<16} {'voz':<11} {'umbral':>13}   "
          f"{'fijo':<8} {'adaptativo':<11} {'neuronal':<9}")
    print("-" * 76)

    for nombre_sala, rms_sala, rms_pico, tipo in _SALAS:
        for nombre_voz, rms_voz in _VOCES:
            pcm, _, fin_habla = _escena(rms_sala, rms_pico, tipo, rms_voz)

            # El adaptativo mide la sala igual que `calibrar_ruido_ambiente`:
            # sobre el silencio previo, con MEXA callada.
            ancho     = _CHUNK_TEST * 2
            previo    = pcm[:int(_SILENCIO_PREVIO_S * _RATE) * 2]
            muestras  = [audioop.rms(quitar_dc(previo[i:i + ancho]), 2)
                         for i in range(0, len(previo) - ancho, ancho)]
            piso      = piso_desde_muestras(muestras)
            adaptativo = umbral_desde_piso(piso)

            v_fijo = _veredicto(*_correr(pcm, DetectorVoz(umbral=_UMBRAL_FIJO_VIEJO)),
                                fin_habla=fin_habla)
            v_adap = _veredicto(*_correr(pcm, DetectorVoz(umbral=adaptativo)),
                                fin_habla=fin_habla)
            v_neur = (_veredicto(*_correr(pcm, DetectorVozNeural(piso=piso)),
                                 fin_habla=fin_habla)
                      if hay_neural else "—")

            # Se juzga al que realmente va a correr en la exhibición.
            v_produccion = v_neur if hay_neural else v_adap
            v_anterior   = v_adap if hay_neural else v_fijo

            total += 1
            caso = (f"{nombre_sala} + {nombre_voz} "
                    f"(ruido {rms_sala}{f'/{rms_pico}' if rms_pico else ''}, "
                    f"voz {rms_voz}) → fijo {_UMBRAL_FIJO_VIEJO}: {v_fijo} | "
                    f"adaptativo {adaptativo}: {v_adap} | neuronal: {v_neur}")

            if v_produccion == "OK":
                estado = "PASA"
            elif rms_voz <= rms_sala:
                estado = "LÍMITE"; limites.append(caso)
            elif v_produccion == "PEGADO" or v_anterior == "OK":
                estado = "CRÍTICO"; criticos.append(caso)
            else:
                estado = "LÍMITE"; limites.append(caso)

            print(f"{nombre_sala:<16} {nombre_voz:<11} "
                  f"{_UMBRAL_FIJO_VIEJO:>5} → {adaptativo:<5} "
                  f"{v_fijo:<8} {v_adap:<11} {v_neur:<9} {estado}")

    print("-" * 76)
    print(f"{total - len(criticos) - len(limites)}/{total} OK, "
          f"{len(limites)} en el límite del hardware, {len(criticos)} críticos\n")
    print(f"(umbral = piso de ruido × factor, acotado; "
          f"habla mínima {_MIN_HABLA_SEG}s, corte tras {_SILENCIO_SEG}s de silencio)\n")
    for c in limites:
        print(f"  LÍMITE:  {c}")
    for c in criticos:
        print(f"  CRÍTICO: {c}")
    return 1 if criticos else 0


if __name__ == "__main__":
    sys.exit(main())
