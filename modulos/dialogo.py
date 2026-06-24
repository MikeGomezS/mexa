# ============================================================
#  MEXA — Diálogo: máquina de estados de la interacción
#
#  Todo lo que pasa con UN visitante: elegir idioma, ofrecer
#  civilizaciones, reproducir el video y el ciclo de preguntas
#  con IA. Cada interacción termina devolviendo un `Resultado`
#  que le dice a `ciclo_principal` qué hacer después.
# ============================================================

import re
import time
from enum import Enum, auto

from .modulo_audio     import escuchar_pregunta
from .modulo_ia        import (generar_respuesta_stream, limpiar_historial,
                               establecer_idioma)
from .modulo_tts       import hablar, hablar_stream
from .modulo_motores   import orientarse_a_usuario
from .modulo_camara    import posicion_cara
from .modulo_proyector import mostrar_segun_tema, cambiar_expresion, reproducir_video
from . import contenido


# ── Configuración ────────────────────────────────────────────
TIEMPO_ESPERA_USUARIO = 30   # segundos antes de despedirse si no habla
INTENTOS_MAX          = 3    # intentos de escuchar antes de despedirse


class Resultado(Enum):
    """Qué debe hacer ciclo_principal cuando termina una interacción."""
    APAGAR    = auto()   # el visitante dijo "terminar": apagar MEXA
    ESPERAR   = auto()   # se fue / dijo "adios": retroceder y esperar al próximo
    REINICIAR = auto()   # dijo "empecemos de nuevo": reiniciar la charla en el lugar


# ── Comandos de voz ──────────────────────────────────────────
# Frases que disparan acciones de control. Se matchean por PALABRA
# COMPLETA (ver _dijo), nunca por subcadena: así "bueno" no dispara
# "no", ni el nombre del robot dispara un reinicio.
_PALABRAS_APAGAR  = {"terminar", "terminemos"}  # apaga MEXA por completo
_PALABRAS_SALIDA  = {"adios", "adiós", "bye", "hasta luego", "no", "no gracias", "nada", "ninguna"}
# Reinicio en el lugar: frases INTENCIONALES, nunca el nombre del robot ("mexa")
# ni palabras comunes ("mesa"), que disparaban falsos positivos al ser nombrado.
_PALABRAS_REINICIO = {"empecemos de nuevo", "empecemos", "empezar de nuevo", "reiniciar"}


def _dijo(frase: str, claves: set[str]) -> bool:
    """True si `frase` contiene alguna `clave` como PALABRA(S) completas.

    Tokeniza y normaliza la frase, luego busca cada clave con límites de
    palabra (\\b). Evita el footgun del match por subcadena: "no" ya no se
    dispara dentro de "bueno"/"conocían", y soporta claves multi-palabra
    como "hasta luego" o "empecemos de nuevo"."""
    secuencia = " ".join(re.findall(r"\w+", frase.lower()))
    return any(re.search(rf"\b{re.escape(clave)}\b", secuencia) for clave in claves)


def _seleccionar_idioma() -> str:
    """Pregunta el idioma preferido y retorna 'es' o 'en'."""
    cambiar_expresion("pensando")
    hablar("Hi, I am MEXA. Would you prefer Spanish or English?")
    for _ in range(INTENTOS_MAX):
        cambiar_expresion("escuchando")
        resp = escuchar_pregunta(timeout=8)
        if resp:
            r = resp.lower()
            if any(k in r for k in ("english", "inglés", "ingles")):
                return "en"
            if any(k in r for k in ("español", "espanol", "spanish")):
                return "es"
        cambiar_expresion("hablando")
        hablar("Please say 'español' or 'English'.")
    return "es"


def _ciclo_preguntas(f: dict) -> Resultado:
    """
    Escucha y responde preguntas, usando las frases del idioma elegido (f).
    Retorna Resultado.APAGAR    → terminar programa (se dijo "terminar")
            Resultado.ESPERAR   → volver a esperar PIR (se dijo "adios" u otra salida)
            Resultado.REINICIAR → reiniciar la interacción (se dijo "empecemos de nuevo")
    """
    tiempo_ultimo = time.time()
    intentos_sin_respuesta = 0

    while True:
        if time.time() - tiempo_ultimo > TIEMPO_ESPERA_USUARIO:
            cambiar_expresion("hablando")
            time.sleep(3)
            hablar(f["despedida"])
            return Resultado.ESPERAR

        cambiar_expresion("escuchando")
        pregunta = escuchar_pregunta(timeout=8)

        if not pregunta:
            intentos_sin_respuesta += 1
            if intentos_sin_respuesta >= INTENTOS_MAX:
                cambiar_expresion("hablando")
                time.sleep(3)
                hablar(f["despedida"])
                return Resultado.ESPERAR
            cambiar_expresion("hablando")
            hablar(f["no_entendio"])
            continue

        intentos_sin_respuesta = 0
        tiempo_ultimo = time.time()

        if _dijo(pregunta, _PALABRAS_REINICIO):
            return Resultado.REINICIAR

        if _dijo(pregunta, _PALABRAS_APAGAR):
            cambiar_expresion("hablando")
            time.sleep(3)
            hablar(f["despedida"])
            return Resultado.APAGAR

        if _dijo(pregunta, _PALABRAS_SALIDA):
            cambiar_expresion("hablando")
            time.sleep(3)
            hablar(f["despedida"])
            return Resultado.ESPERAR

        cambiar_expresion("pensando")
        mostrar_segun_tema(pregunta)
        cambiar_expresion("hablando")
        hablar_stream(generar_respuesta_stream(pregunta))


def ciclo_interaccion() -> Resultado:
    """
    Flujo completo con un visitante.
    Retorna Resultado.APAGAR    → terminar el programa (se dijo "terminar")
            Resultado.ESPERAR   → volver a esperar a un visitante (PIR)
            Resultado.REINICIAR → reiniciar la interacción de inmediato
    """
    limpiar_historial()
    orientarse_a_usuario(posicion_cara())

    # 0. Selección de idioma
    idioma = _seleccionar_idioma()
    establecer_idioma(idioma)
    f = contenido.FRASES[idioma]

    nombres_disp = (
        contenido.NOMBRES_DISPONIBLES if idioma == "es"
        else [contenido.NOMBRES_EN[n] for n in contenido.NOMBRES_DISPONIBLES]
    )
    oferta = ", ".join(nombres_disp)

    # 1. Presentación y oferta de civilizaciones
    cambiar_expresion("hablando")
    hablar(f["saludo_civ"].format(oferta=oferta))

    # 2. Escuchar la elección (con reintentos)
    video_info = None
    intentos = 0
    while video_info is None and intentos < INTENTOS_MAX:
        cambiar_expresion("escuchando")
        eleccion = escuchar_pregunta(timeout=10)
        if eleccion:
            video_info = contenido.detectar_civilizacion(eleccion, idioma)
            if video_info is None:
                intentos += 1
                cambiar_expresion("hablando")
                hablar(f["no_reconocio"].format(oferta=oferta))
        else:
            intentos += 1
            cambiar_expresion("hablando")
            hablar(f["no_entendio"])

    if video_info is None:
        cambiar_expresion("hablando")
        time.sleep(3)
        hablar(f["despedida"])
        return Resultado.ESPERAR

    ruta_video, nombre_civ_es = video_info
    nombre_civ = contenido.NOMBRES_EN[nombre_civ_es] if idioma == "en" else nombre_civ_es

    # 3. Reproducir el video en el idioma seleccionado
    cambiar_expresion("hablando")
    hablar(f["intro_video"].format(nombre=nombre_civ))
    reproducir_video(ruta_video)

    # 5. Preguntar si tienen dudas
    time.sleep(3)
    cambiar_expresion("hablando")
    hablar(f["post_video"].format(nombre=nombre_civ))

    # 6 y 7. Ciclo de preguntas con IA + despedida. Propaga el Resultado.
    return _ciclo_preguntas(f)
