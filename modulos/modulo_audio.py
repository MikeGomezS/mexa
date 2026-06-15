# ============================================================
#  MEXA — Módulo 01: Captura de Audio (Speech-to-Text)
#  Motor principal: Vosk (100% offline, español)
#  Librería: vosk, pyaudio
#  Instalar: pip install vosk pyaudio
#  Modelo: modelo_vosk_es/ (vosk-model-small-es-0.42)
# ============================================================

import audioop
import json
import os
import time
import pyaudio
from vosk import Model, KaldiRecognizer

_MODELO_DIR  = os.path.join(os.path.dirname(__file__), "..", "modelo_vosk_es")
_VOSK_RATE   = 16000   # Vosk siempre necesita 16 kHz
_CHUNK       = 4096

_SILENCIO_UMBRAL = 300   # RMS mínimo para considerar que hay voz (ajustar según mic)
_SILENCIO_SEG    = 1.5   # segundos de silencio continuo para dejar de escuchar
_MIN_HABLA_SEG   = 0.3   # segundos mínimos de habla antes de activar el VAD

_model:       Model | None         = None
_audio:       pyaudio.PyAudio | None = None
_dev_index:   int | None           = None
_native_rate: int | None           = None
_stream:      pyaudio.Stream | None = None


def _cargar_modelo():
    global _model
    if _model is None:
        print("[AUDIO] Cargando modelo Vosk...")
        _model = Model(_MODELO_DIR)
        print("[AUDIO] Modelo Vosk cargado.")
    return _model


def _cargar_audio():
    global _audio
    if _audio is None:
        _audio = pyaudio.PyAudio()
    return _audio


def _buscar_microfono_usb(pa: pyaudio.PyAudio) -> tuple[int, int]:
    """Devuelve (device_index, native_rate) del primer micrófono USB disponible."""
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0 and "USB" in info["name"]:
            return i, int(info["defaultSampleRate"])
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            return i, int(info["defaultSampleRate"])
    raise RuntimeError("[AUDIO] No se encontró ningún micrófono.")


def _obtener_dispositivo() -> tuple[int, int]:
    """Devuelve el dispositivo cacheado; solo escanea la primera vez."""
    global _dev_index, _native_rate
    if _dev_index is None:
        pa = _cargar_audio()
        _dev_index, _native_rate = _buscar_microfono_usb(pa)
        print(f"[AUDIO] Micrófono: índice {_dev_index}, {_native_rate} Hz")
    return _dev_index, _native_rate


def _obtener_stream() -> pyaudio.Stream:
    """Devuelve el stream persistente; lo crea si no existe o si se cerró."""
    global _stream
    dev_index, native_rate = _obtener_dispositivo()
    pa = _cargar_audio()
    if _stream is None or not _stream.is_active():
        if _stream is not None:
            try:
                _stream.close()
            except Exception:
                pass
        _stream = pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=native_rate,
            input=True,
            input_device_index=dev_index,
            frames_per_buffer=_CHUNK,
        )
        print("[AUDIO] Stream abierto.")
    return _stream


def _vaciar_buffer(stream: pyaudio.Stream) -> None:
    """Descarta frames acumulados durante TTS o silencio previo."""
    try:
        n = stream.get_read_available()
        while n > 0:
            stream.read(min(n, _CHUNK), exception_on_overflow=False)
            n = stream.get_read_available()
    except Exception:
        pass


# Precarga al importar para evitar latencia en la primera escucha
_cargar_modelo()


def escuchar_pregunta(timeout=6) -> str:
    """
    Escucha por el micrófono USB y regresa el texto detectado (offline).
    El stream se mantiene abierto entre llamadas para eliminar la latencia
    de apertura. El buffer se vacía antes de escuchar para descartar audio
    acumulado durante la reproducción de TTS.
    Si el stream se corrompe, se recrea automáticamente en la siguiente llamada.
    """
    global _stream

    recognizer = KaldiRecognizer(_cargar_modelo(), _VOSK_RATE)
    _, native_rate = _obtener_dispositivo()

    try:
        stream = _obtener_stream()
        _vaciar_buffer(stream)
    except Exception as e:
        print(f"[AUDIO] Error al preparar stream: {e}")
        return ""

    print("[AUDIO] Escuchando...")
    limite          = time.time() + timeout
    texto           = ""
    resample_state  = None
    habla_inicio:   float | None = None
    silencio_inicio: float | None = None

    try:
        while time.time() < limite:
            try:
                data = stream.read(_CHUNK, exception_on_overflow=False)
            except OSError:
                _stream = None  # se recreará en la próxima llamada
                break

            # VAD: calcular energía antes de remuestrear
            rms  = audioop.rms(data, 2)
            ahora = time.time()
            if rms >= _SILENCIO_UMBRAL:
                if habla_inicio is None:
                    habla_inicio = ahora
                silencio_inicio = None
            elif habla_inicio and (ahora - habla_inicio) >= _MIN_HABLA_SEG:
                if silencio_inicio is None:
                    silencio_inicio = ahora
                elif ahora - silencio_inicio >= _SILENCIO_SEG:
                    break  # silencio prolongado → dejar de escuchar

            if native_rate != _VOSK_RATE:
                data, resample_state = audioop.ratecv(
                    data, 2, 1, native_rate, _VOSK_RATE, resample_state
                )
            if recognizer.AcceptWaveform(data):
                resultado = json.loads(recognizer.Result())
                texto = resultado.get("text", "").strip()
                if texto:
                    break
        if not texto:
            resultado = json.loads(recognizer.FinalResult())
            texto = resultado.get("text", "").strip()
    except Exception as e:
        print(f"[AUDIO] Error durante escucha: {e}")

    if texto:
        print(f"[AUDIO] Texto detectado: {texto}")
    else:
        print("[AUDIO] No se detectó voz.")
    return texto
