# ============================================================
#  MEXA — Módulo 01: Captura de Audio (Speech-to-Text)
#  Motor principal: Vosk (100% offline, bilingüe es/en)
#  Librería: vosk, pyaudio
#  Instalar: pip install vosk pyaudio
#  Modelos: modelo_vosk_es/ (vosk-model-small-es-0.42)
#           modelo_vosk_en/ (vosk-model-small-en-us-0.15)
#
#  POR QUÉ DOS MODELOS: el modelo español no tiene los fonemas
#  /ɪ/ ni /ʃ/. Con audio de estudio todavía alinea "English"
#  (/ˈɪŋɡlɪʃ/) contra su entrada léxica, pronunciada a la española
#  (/eŋˈglis/) — pero es un match forzado, sin margen. En la
#  exhibición, con micrófono lejano y ruido de sala, ese margen
#  desaparece y decodifica cualquier cosa (medido: "web").
#  Un oído español no escucha inglés; hay que darle a cada idioma
#  el oído correcto. Ver tests/test_idioma.py.
# ============================================================

import audioop
import json
import os
import time

import pyaudio
from vosk import Model, KaldiRecognizer

from . import vad
from .vad import crear_detector, quitar_dc, registrar_ruido, umbral_actual

_BASE_DIR = os.path.dirname(__file__)
_MODELOS_DIR = {
    "es": os.path.join(_BASE_DIR, "..", "modelo_vosk_es"),
    "en": os.path.join(_BASE_DIR, "..", "modelo_vosk_en"),
}
_VOSK_RATE   = 16000   # Vosk siempre necesita 16 kHz
_CHUNK       = 4096

# El VAD vive en modulos/vad.py: cuándo hay voz es una decisión con su
# propio modelo y sus propias constantes, y no depende de PyAudio.

# ── Gramáticas cerradas para la pregunta de idioma ───────────
# Una pregunta CERRADA merece un grafo CERRADO: en vez de elegir
# entre ~300 mil palabras, el decodificador elige entre 3. Cada
# modelo recibe sólo las palabras que sabe pronunciar. "[unk]" es
# la válvula de escape de Vosk cuando el audio no matchea ninguna.
_GRAMATICA_IDIOMA = {
    "es": '["espanol", "ingles", "[unk]"]',
    "en": '["spanish", "english", "[unk]"]',
}
# Qué idioma implica cada palabra reconocida, sin importar en qué
# idioma se dijo: quien dice "spanish" quiere español.
_PALABRA_A_IDIOMA = {
    "espanol": "es", "spanish": "es",
    "ingles":  "en", "english": "en",
}

_modelos:     dict[str, Model]     = {}
_audio:       pyaudio.PyAudio | None = None
_dev_index:   int | None           = None
_native_rate: int | None           = None
_stream:      pyaudio.Stream | None = None


def _cargar_modelo(idioma: str = "es") -> Model:
    """Devuelve el modelo Vosk del idioma, cargándolo la primera vez.

    Los modelos se cachean por idioma: cargar uno cuesta ~1 s y ~200 MB
    de RAM, así que se paga una sola vez por ejecución."""
    if idioma not in _modelos:
        ruta = _MODELOS_DIR[idioma]
        if not os.path.isdir(ruta):
            raise FileNotFoundError(
                f"[AUDIO] Falta el modelo Vosk '{idioma}' en {ruta}. "
                f"Descargalo de https://alphacephei.com/vosk/models y "
                f"descomprimilo con ese nombre de carpeta."
            )
        print(f"[AUDIO] Cargando modelo Vosk '{idioma}'...")
        _modelos[idioma] = Model(ruta)
        print(f"[AUDIO] Modelo Vosk '{idioma}' cargado.")
    return _modelos[idioma]


def modelo_disponible(idioma: str) -> bool:
    """True si el modelo de ese idioma está instalado en disco."""
    return idioma in _MODELOS_DIR and os.path.isdir(_MODELOS_DIR[idioma])


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


def calibrar_ruido_ambiente(segundos: float = 1.5) -> int:
    """Mide el ruido de la sala donde está MEXA y fija el umbral de voz.

    Llamar al arrancar, con MEXA CALLADA y sin nadie hablándole: lo que se
    mida acá es lo que MEXA va a considerar silencio. Si alguien habla
    durante la medición el piso queda alto y MEXA arranca dura de oído;
    no es grave —la ventana móvil lo corrige sola en las primeras
    escuchas— pero conviene calibrar en paz.

    Devuelve el umbral resultante. Si el micrófono falla, deja el que
    había: no poder medir la sala no es motivo para no escuchar.
    """
    try:
        stream = _obtener_stream()
        _vaciar_buffer(stream)
        _, native_rate = _obtener_dispositivo()
    except Exception as e:
        print(f"[AUDIO] No se pudo calibrar el ruido ({e}); umbral {umbral_actual()}.")
        return umbral_actual()

    # Se mide sobre el audio YA REMUESTREADO, que es exactamente el que
    # va a ver el VAD. Medir a 44.1 kHz y decidir a 16 kHz sería comparar
    # el ruido contra una regla distinta de la que lo va a juzgar.
    muestras, estado = [], None
    limite = time.time() + segundos
    try:
        while time.time() < limite:
            data = stream.read(_CHUNK, exception_on_overflow=False)
            if native_rate != _VOSK_RATE:
                data, estado = audioop.ratecv(data, 2, 1, native_rate,
                                              _VOSK_RATE, estado)
            muestras.append(audioop.rms(quitar_dc(data), 2))
    except Exception as e:
        print(f"[AUDIO] Calibración interrumpida ({e}).")

    registrar_ruido(muestras)
    print(f"[AUDIO] Ruido de sala: {int(vad.piso_actual())} RMS "
          f"({len(muestras)} chunks) → umbral de energía {umbral_actual()}")
    return umbral_actual()


# Precarga el modelo español al importar para evitar latencia en la
# primera escucha. El inglés se carga bajo demanda (sólo si hay un
# visitante que lo elige), para no pagar RAM ni arranque de más.
_cargar_modelo("es")


def _escuchar(timeout: float, recognizers: dict[str, KaldiRecognizer]) -> dict[str, str]:
    """Captura audio del micrófono y lo decodifica con VARIOS recognizers a la vez.

    Es el motor común: lee el stream una sola vez y alimenta el mismo
    chunk a cada recognizer, así todos oyen EXACTAMENTE el mismo audio.
    El VAD (modulos/vad.py) decide cuándo el visitante dejó de hablar,
    con el ruido de sala medido hasta este momento como referencia.

    Retorna {clave: texto} con el resultado final de cada recognizer.
    """
    global _stream

    _, native_rate = _obtener_dispositivo()

    try:
        stream = _obtener_stream()
        _vaciar_buffer(stream)
    except Exception as e:
        print(f"[AUDIO] Error al preparar stream: {e}")
        return {clave: "" for clave in recognizers}

    detector       = crear_detector()
    limite         = time.time() + timeout
    resample_state = None
    print(f"[AUDIO] Escuchando... (ruido de sala {int(vad.piso_actual())} RMS, "
          f"VAD: {detector})")

    try:
        while time.time() < limite:
            try:
                data = stream.read(_CHUNK, exception_on_overflow=False)
            except OSError:
                _stream = None  # se recreará en la próxima llamada
                break

            # Remuestrear PRIMERO: el VAD y Vosk tienen que oír exactamente
            # la misma señal, y Silero sólo trabaja a 16 kHz.
            if native_rate != _VOSK_RATE:
                data, resample_state = audioop.ratecv(
                    data, 2, 1, native_rate, _VOSK_RATE, resample_state
                )
            # El offset DC del micrófono se saca ACÁ y no en la calibración
            # sola: piso y decisión tienen que medirse sobre la MISMA señal
            # o el umbral queda 19% alto. Ver vad.quitar_dc().
            data = quitar_dc(data)

            if detector.observar(data, time.time()):
                break

            for rec in recognizers.values():
                rec.AcceptWaveform(data)
    except Exception as e:
        print(f"[AUDIO] Error durante escucha: {e}")

    # La sala se re-mide con lo que acabamos de oír: así el umbral de la
    # PRÓXIMA escucha ya conoce el ruido de ahora, no el de hace una hora.
    registrar_ruido(detector.muestras)
    if not detector.hubo_voz:
        print(f"[AUDIO] Nadie habló: nada pasó el VAD ({detector}).")

    textos = {}
    for clave, rec in recognizers.items():
        try:
            textos[clave] = json.loads(rec.FinalResult()).get("text", "").strip()
        except Exception:
            textos[clave] = ""
    return textos


def escuchar_pregunta(timeout=6, idioma: str = "es") -> str:
    """
    Escucha por el micrófono USB y regresa el texto detectado (offline),
    usando el modelo Vosk del `idioma` indicado.
    El stream se mantiene abierto entre llamadas para eliminar la latencia
    de apertura. El buffer se vacía antes de escuchar para descartar audio
    acumulado durante la reproducción de TTS.
    Si el stream se corrompe, se recrea automáticamente en la siguiente llamada.
    """
    if not modelo_disponible(idioma):
        idioma = "es"   # degradación: sin modelo del idioma, se oye en español

    recognizer = KaldiRecognizer(_cargar_modelo(idioma), _VOSK_RATE)
    texto = _escuchar(timeout, {"principal": recognizer})["principal"]

    if texto:
        print(f"[AUDIO] Texto detectado ({idioma}): {texto}")
    else:
        print("[AUDIO] No se detectó voz.")
    return texto


def escuchar_multilingue(timeout: float, idiomas,
                         gramaticas: dict[str, str] | None = None) -> dict[str, str]:
    """Escucha UNA vez y decodifica en varios idiomas a la vez.

    Devuelve {idioma: texto_oído}, saltando los idiomas sin modelo instalado.
    `gramaticas` (opcional) restringe cada idioma a un set cerrado de frases.

    CUÁNDO USAR GRAMÁTICA CERRADA: sólo cuando ya SABÉS que lo dicho es una
    de las opciones — típicamente porque MEXA acabó de hacer una pregunta
    cerrada ("¿español o inglés?"). Ahí forzar al decodificador es justo lo
    que querés.

    CUÁNDO NO: para un wake word. Ahí el 99% del audio NO es una frase de
    activación, y la gramática le saca al modelo la posibilidad de decir
    "esto fue otra cosa"; "[unk]" no alcanza como válvula de escape. Medido
    en tests/test_activacion.py: con gramática cerrada, "vamos a la otra
    sala" se decodificaba como "comenzamos" y despertaba a MEXA.

    Devuelve un dict y NO un texto concatenado a propósito: pegar las
    salidas de dos modelos puede fabricar coincidencias que nadie dijo
    (el español aporta "let's", el inglés "begin", y aparece un
    "let's begin" fantasma). Cada texto se evalúa por separado.
    """
    gramaticas = gramaticas or {}
    recognizers = {}
    for i in idiomas:
        if not modelo_disponible(i):
            continue
        modelo = _cargar_modelo(i)
        recognizers[i] = (KaldiRecognizer(modelo, _VOSK_RATE, gramaticas[i])
                          if i in gramaticas else
                          KaldiRecognizer(modelo, _VOSK_RATE))
    return _escuchar(timeout, recognizers) if recognizers else {}


def escuchar_idioma(timeout=8) -> str | None:
    """Escucha la respuesta a "¿español o inglés?" y retorna 'es', 'en' o None.

    Corre los DOS modelos sobre el mismo audio, cada uno con una gramática
    cerrada que sólo contiene las palabras que ese modelo sabe pronunciar:
    el español decide entre "espanol"/"ingles", el inglés entre
    "spanish"/"english". Así nadie tiene que decodificar fonemas que no
    tiene, y no hace falta comparar confianzas entre modelos distintos
    (son escalas incomparables).

    Se decide por CONTENIDO, no por puntaje:
      - los dos coinciden, o sólo uno reconoce algo → ese idioma
      - se contradicen, o ninguno reconoce nada     → None (repreguntar)

    Ante la duda devuelve None a propósito: repreguntar es barato,
    arrancar la visita entera en el idioma equivocado no lo es.
    """
    idiomas = [i for i in _GRAMATICA_IDIOMA if modelo_disponible(i)]
    recognizers = {
        i: KaldiRecognizer(_cargar_modelo(i), _VOSK_RATE, _GRAMATICA_IDIOMA[i])
        for i in idiomas
    }
    if not recognizers:
        return None

    return decidir_idioma(_escuchar(timeout, recognizers))


def decidir_idioma(textos: dict[str, str]) -> str | None:
    """Traduce lo que oyó cada modelo a un idioma, o None si no hay consenso.

    Función PURA: sin micrófono ni estado. Es la regla de decisión aislada
    para poder verificarla con audio grabado (ver tests/test_idioma.py).
    """
    votos = set()
    for modelo, texto in textos.items():
        print(f"[AUDIO] Idioma — modelo '{modelo}' oyó: {texto or '(nada)'}")
        votos.update(_PALABRA_A_IDIOMA[p] for p in texto.split() if p in _PALABRA_A_IDIOMA)

    if len(votos) == 1:
        elegido = votos.pop()
        print(f"[AUDIO] Idioma elegido: {elegido}")
        return elegido

    print("[AUDIO] Idioma ambiguo o no reconocido.")
    return None
