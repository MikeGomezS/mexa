# ============================================================
#  MEXA — Módulo 03: Síntesis de Voz (Text-to-Speech)
#  Librería: piper-tts (voz neural, 100% offline, optimizada ARM)
#  Modelos: es_MX-claude-high (español) / en_US-lessac-high (inglés)
#  Instalar: pip install piper-tts langdetect
# ============================================================

import audioop
import hashlib
import io
import queue
import subprocess
import threading
import time
import wave
import os
from piper.voice import PiperVoice
from langdetect import detect, LangDetectException

_MODELO_DIR = os.path.join(os.path.dirname(__file__), "..", "media", "tts")
_MODELOS = {
    "es": os.path.join(_MODELO_DIR, "es_MX-claude-high.onnx"),
    "en": os.path.join(_MODELO_DIR, "en_US-lessac-high.onnx"),
}
_AUDIO_TMP = "/tmp/mexa_tts.wav"
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "media", "tts_cache")
_cache: dict[str, str] = {}  # texto → ruta wav pre-sintetizada

_voces: dict = {}

_VOL_CHUNK  = 1024   # 512 muestras int16 @ ~22050 Hz ≈ 23 ms por chunk
_VOL_ESCALA = 5000.0 # RMS típico de voz normal; bajar si la boca abre poco


def _cargar_voz(idioma: str) -> PiperVoice:
    if idioma not in _voces:
        modelo = _MODELOS.get(idioma, _MODELOS["es"])
        print(f"[TTS] Cargando voz '{idioma}'...")
        _voces[idioma] = PiperVoice.load(modelo)
        print(f"[TTS] Voz '{idioma}' cargada.")
    return _voces[idioma]


def _detectar_idioma(texto: str) -> str:
    try:
        lang = detect(texto)
        return "en" if lang == "en" else "es"
    except LangDetectException:
        return "es"


def _enviar_volumen(rms: int) -> None:
    try:
        from .modulo_proyector import enviar_volumen
        enviar_volumen(min(rms / _VOL_ESCALA, 1.0))
    except Exception:
        pass


def _reproducir_con_volumen(ruta_wav: str, pcm_data: bytes, sample_rate: int) -> None:
    """Reproduce un .wav con pw-play (PipeWire) mientras envía volumen a la cara.
    pw-play corre en un thread; el volumen se sincroniza por timing de sample rate."""
    done = threading.Event()

    def _play():
        subprocess.run(["pw-play", ruta_wav], check=False)
        done.set()

    threading.Thread(target=_play, daemon=True).start()

    # RELOJ ABSOLUTO, no sleeps encadenados. `time.sleep` siempre se pasa un
    # poco, y sumando un chunk cada 23 ms el error se acumula: medido, +3% de
    # la duración (+0.22 s en una frase de 6.7 s) que se pagaban como silencio
    # al final. Calcular el instante de cada chunk desde el arranque no acumula.
    reloj0 = time.monotonic()
    reproducido = 0.0
    for i in range(0, len(pcm_data), _VOL_CHUNK):
        trozo = pcm_data[i:i + _VOL_CHUNK]
        _enviar_volumen(audioop.rms(trozo, 2))
        reproducido += len(trozo) / 2 / sample_rate
        espera = reloj0 + reproducido - time.monotonic()
        if espera > 0:
            time.sleep(espera)

    done.wait(timeout=10.0)
    _enviar_volumen(0)  # cierra la boca al terminar


# Precarga ambas voces al importar para evitar latencia en la primera frase
_cargar_voz("es")
_cargar_voz("en")


def presintetizar(texto: str) -> None:
    """Registra el texto en caché. Si el .wav ya existe en disco lo reutiliza;
    si no, lo sintetiza y lo guarda para las próximas ejecuciones."""
    if not texto or texto in _cache:
        return
    os.makedirs(_CACHE_DIR, exist_ok=True)
    nombre = hashlib.md5(texto.encode()).hexdigest() + ".wav"
    ruta = os.path.join(_CACHE_DIR, nombre)
    if not os.path.exists(ruta):
        idioma = _detectar_idioma(texto)
        voz = _cargar_voz(idioma)
        wav_file = wave.open(ruta, "wb")
        try:
            voz.synthesize_wav(texto, wav_file)
        finally:
            wav_file.close()
        print(f"[TTS] Sintetizado: {texto[:50]}...")
    else:
        print(f"[TTS] Cargado de disco: {texto[:50]}...")
    _cache[texto] = ruta


def _hablar_espeak(texto: str, idioma: str) -> None:
    """Síntesis instantánea (reglas, sin red neuronal) vía espeak-ng.
    Latencia ~0ms vs ~2-4s de Piper — usado para respuestas dinámicas de IA."""
    voz_espeak = "es-la" if idioma == "es" else "en-us"
    try:
        proc = subprocess.run(
            ["espeak-ng", "-v", voz_espeak, "-s", "140", "--stdout", texto],
            capture_output=True, check=False,
        )
        wav_bytes = proc.stdout
        if not wav_bytes:
            return
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            sample_rate = wf.getframerate()
            pcm_data    = wf.readframes(wf.getnframes())
        with open(_AUDIO_TMP, "wb") as f:
            f.write(wav_bytes)
        _reproducir_con_volumen(_AUDIO_TMP, pcm_data, sample_rate)
    except Exception as e:
        print(f"[TTS] espeak-ng falló ({e}), usando Piper como respaldo...")
        idioma_d = _detectar_idioma(texto)
        voz = _cargar_voz(idioma_d)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voz.synthesize_wav(texto, wf)
        buf.seek(0)
        with wave.open(buf, "rb") as r:
            sample_rate = r.getframerate()
            pcm_data    = r.readframes(r.getnframes())
        buf.seek(0)
        with open(_AUDIO_TMP, "wb") as f:
            f.write(buf.getvalue())
        _reproducir_con_volumen(_AUDIO_TMP, pcm_data, sample_rate)


def hablar(texto: str) -> None:
    """Convierte texto en voz con sincronización de boca.
    Frases cacheadas (Piper): reproducción instantánea desde disco.
    Frases dinámicas (IA): espeak-ng, síntesis en ~0ms."""
    if not texto:
        return
    from .modulo_brazos import animar, parar
    print(f"[TTS] Hablando: {texto[:50]}...")
    animar()
    try:
        if texto in _cache:
            ruta = _cache[texto]
            with wave.open(ruta, "rb") as wf:
                sample_rate = wf.getframerate()
                pcm_data    = wf.readframes(wf.getnframes())
            _reproducir_con_volumen(ruta, pcm_data, sample_rate)
            return

        # Texto dinámico (respuesta de IA) → Piper
        idioma = _detectar_idioma(texto)
        voz = _cargar_voz(idioma)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            voz.synthesize_wav(texto, wf)
        wav_bytes = buf.getvalue()
        buf2 = io.BytesIO(wav_bytes)
        with wave.open(buf2, "rb") as r:
            sample_rate = r.getframerate()
            pcm_data    = r.readframes(r.getnframes())
        with open(_AUDIO_TMP, "wb") as f:
            f.write(wav_bytes)
        _reproducir_con_volumen(_AUDIO_TMP, pcm_data, sample_rate)
    finally:
        parar()


def _abrir_reproductor(sample_rate: int) -> subprocess.Popen:
    """UN pw-play que se queda abierto y come PCM crudo por stdin.

    POR QUÉ NO UNO POR ORACIÓN. Antes cada oración lanzaba su propio
    `pw-play`: proceso nuevo, stream de PipeWire nuevo, y —lo caro— una
    NEGOCIACIÓN NUEVA CON EL PARLANTE BLUETOOTH. Eso es el corte que se
    escuchaba entre frase y frase. Medido: 3 oraciones con un proceso por
    oración agregan +0.81 s de silencio; con un solo stream, +0.06 s.
    """
    return subprocess.Popen(
        ["pw-play", "--raw", f"--rate={sample_rate}", "--channels=1",
         "--format=s16", "--latency=50ms", "-"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL)


def hablar_stream(oraciones, al_hablar=None) -> None:
    """Reproduce un iterable de oraciones como UN SOLO chorro de audio.

    `al_hablar` se invoca UNA vez, en el instante en que hay audio listo y
    MEXA está por sonar — no cuando se la llama. La diferencia es todo el
    punto: consumir `oraciones` arranca el LLM, y en esta Pi el prompt tarda
    entre 5 y 25 s en procesarse. Quien llama no puede saber cuándo termina
    esa espera; esta función sí, porque es la que recibe el primer WAV.

    Sirve para que el llamador ponga cara de pensar mientras se espera y cara
    de hablar cuando se habla. NO se decide acá qué cara es: la política de
    expresiones vive en `dialogo`, y este módulo sólo avisa el evento.

    Tres cosas pasan a la vez:
      1. un hilo SINTETIZA la oración N+1 mientras se escucha la N,
      2. un hilo ESCRIBE el PCM en el único pw-play (se bloquea solo cuando
         el buffer se llena, que es justo lo que queremos),
      3. el hilo principal mueve la BOCA con un RELOJ ABSOLUTO.

    El reloj absoluto no es un detalle. Antes la boca avanzaba con
    `time.sleep(chunk_dur)` acumulando el error de cada sleep: medido, +0.22 s
    por oración (+3%), que se pagaban como silencio ANTES de la siguiente.
    Ahora cada chunk tiene su instante calculado desde el arranque, así que el
    error no se acumula por más larga que sea la respuesta.

    Si cambia el sample rate a mitad de camino (voz distinta), se cierra el
    reproductor y se abre otro: mezclar frecuencias en un stream crudo
    reproduciría a velocidad equivocada.
    """
    from .modulo_brazos import animar, parar
    _CENTINELA = object()
    wav_queue: queue.Queue = queue.Queue(maxsize=2)
    pcm_queue: queue.Queue = queue.Queue()

    def _sintetizar() -> None:
        try:
            for oracion in oraciones:
                if not oracion:
                    continue
                voz = _cargar_voz(_detectar_idioma(oracion))
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    voz.synthesize_wav(oracion, wf)
                with wave.open(io.BytesIO(buf.getvalue()), "rb") as r:
                    wav_queue.put((r.readframes(r.getnframes()), r.getframerate()))
        except Exception as e:
            print(f"[TTS] Error en síntesis stream: {e}")
        finally:
            wav_queue.put(_CENTINELA)

    def _escribir(proc: subprocess.Popen) -> None:
        """Vuelca el PCM en pw-play hasta el centinela. Se bloquea cuando el
        buffer está lleno: esa contrapresión es la que mantiene el chorro."""
        try:
            while True:
                pcm = pcm_queue.get()
                if pcm is None:
                    break
                proc.stdin.write(pcm)
            proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass

    threading.Thread(target=_sintetizar, daemon=True).start()

    animar()
    proc = escritor = None
    rate_actual = None
    reloj0 = 0.0
    reproducido = 0.0     # segundos de audio YA encolados (base del reloj)

    def _cerrar() -> None:
        nonlocal proc, escritor
        if proc is None:
            return
        pcm_queue.put(None)
        if escritor is not None:
            escritor.join(timeout=15.0)
        try:
            proc.wait(timeout=15.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        proc = escritor = None

    try:
        primero = True
        while True:
            item = wav_queue.get()
            if item is _CENTINELA:
                break
            pcm_data, sample_rate = item

            if primero:
                # ACÁ, y no antes: `wav_queue.get()` recién devuelve algo
                # cuando la primera oración está sintetizada, o sea cuando el
                # LLM terminó de pensar. Es el único instante honesto para
                # decir "ya está hablando".
                #
                # Un fallo del callback NO puede callar a MEXA: la cara es
                # decoración, el audio es el servicio. Por eso va envuelto.
                primero = False
                if al_hablar is not None:
                    try:
                        al_hablar()
                    except Exception as e:
                        print(f"[TTS] al_hablar falló (sigo hablando): {e}")

            if sample_rate != rate_actual:
                _cerrar()                      # frecuencia distinta: stream nuevo
                proc = _abrir_reproductor(sample_rate)
                escritor = threading.Thread(target=_escribir, args=(proc,), daemon=True)
                escritor.start()
                rate_actual = sample_rate
                reloj0 = time.monotonic()
                reproducido = 0.0

            pcm_queue.put(pcm_data)            # el escritor lo manda cuando puede

            for i in range(0, len(pcm_data), _VOL_CHUNK):
                _enviar_volumen(audioop.rms(pcm_data[i:i + _VOL_CHUNK], 2))
                reproducido += len(pcm_data[i:i + _VOL_CHUNK]) / 2 / sample_rate
                espera = reloj0 + reproducido - time.monotonic()
                if espera > 0:
                    time.sleep(espera)
    finally:
        _cerrar()
        _enviar_volumen(0)   # cierra la boca
        parar()

