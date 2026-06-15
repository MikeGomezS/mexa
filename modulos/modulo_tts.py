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

    chunk_dur = _VOL_CHUNK / 2 / sample_rate  # segundos reales por chunk
    for i in range(0, len(pcm_data), _VOL_CHUNK):
        _enviar_volumen(audioop.rms(pcm_data[i:i + _VOL_CHUNK], 2))
        time.sleep(chunk_dur)

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


def hablar_stream(oraciones) -> None:
    """Reproduce un iterable de oraciones solapando síntesis y reproducción.
    Mientras la oración N se escucha, la N+1 ya se está sintetizando en background.
    Elimina el silencio entre oraciones en respuestas de IA."""
    from .modulo_brazos import animar, parar
    _CENTINELA = object()
    wav_queue: queue.Queue = queue.Queue(maxsize=2)

    def _sintetizar() -> None:
        try:
            for oracion in oraciones:
                if not oracion:
                    continue
                idioma = _detectar_idioma(oracion)
                voz    = _cargar_voz(idioma)
                buf = io.BytesIO()
                with wave.open(buf, "wb") as wf:
                    voz.synthesize_wav(oracion, wf)
                wav_bytes = buf.getvalue()
                buf2 = io.BytesIO(wav_bytes)
                with wave.open(buf2, "rb") as r:
                    sample_rate = r.getframerate()
                    pcm_data    = r.readframes(r.getnframes())
                wav_queue.put((wav_bytes, pcm_data, sample_rate))
        except Exception as e:
            print(f"[TTS] Error en síntesis stream: {e}")
        finally:
            wav_queue.put(_CENTINELA)

    threading.Thread(target=_sintetizar, daemon=True).start()

    animar()
    try:
        idx = 0
        while True:
            item = wav_queue.get()
            if item is _CENTINELA:
                break
            wav_bytes, pcm_data, sample_rate = item
            ruta = f"/tmp/mexa_stream_{idx % 2}.wav"
            idx += 1
            with open(ruta, "wb") as f:
                f.write(wav_bytes)
            _reproducir_con_volumen(ruta, pcm_data, sample_rate)
    finally:
        parar()


def hablar_despedida():
    time.sleep(3)
    hablar("Fue un placer compartir cultura contigo. ¡Hasta pronto!")


def hablar_no_entendio():
    hablar("No escuché bien. ¿Puedes repetir tu pregunta, por favor?")
