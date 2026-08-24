# ============================================================
#  MEXA — Diálogo: máquina de estados de la interacción
#
#  Todo lo que pasa con UN visitante: elegir idioma, ofrecer
#  civilizaciones, reproducir el video y el ciclo de preguntas
#  con IA. Cada interacción termina devolviendo un `Resultado`
#  que le dice a `ciclo_principal` qué hacer después.
# ============================================================

import json
import re
import time
from enum import Enum, auto

from .modulo_audio     import (escuchar_pregunta, escuchar_idioma,
                               escuchar_multilingue)
from .modulo_ia        import (generar_respuesta_stream, limpiar_historial,
                               establecer_idioma)
from .modulo_tts       import hablar, hablar_stream
from .modulo_motores   import orientarse_a_usuario
from .modulo_camara    import posicion_cara, reiniciar_objetivo
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
_PALABRAS_APAGAR  = {"terminar", "terminemos", "shut down", "shutdown", "power off"}
_PALABRAS_SALIDA  = {"adios", "adiós", "bye", "goodbye", "hasta luego", "see you",
                     "no", "no gracias", "no thanks", "nada", "nothing", "ninguna", "none"}
# Reinicio en el lugar: frases INTENCIONALES, nunca el nombre del robot ("mexa")
# ni palabras comunes ("mesa"), que disparaban falsos positivos al ser nombrado.
_PALABRAS_REINICIO = {"empecemos de nuevo", "empecemos", "empezar de nuevo", "reiniciar",
                      "start over", "start again", "restart"}
# Frases para DESPERTAR a MEXA del reposo, por idioma. El criterio es que
# sean REALES, distintivas e INTENCIONALES: nadie las dice de casualidad al
# pasar. Por eso NO está "let's go", por más natural que suene — medido, se
# dispara en 3 de 5 frases de museo, y justo en las peores ("let's go to the
# next room"), o sea despertaría a MEXA cuando el visitante se está YENDO.
# Ver tests/test_activacion.py.
_ACTIVACION = {
    "es": {"comencemos", "comenzar", "comenzamos", "comienza"},
    # NO poner "begin" suelta. La frontera de palabra la protege de
    # "begins"/"beginning"/"beginners", pero no de la palabra usada tal
    # cual en medio de una frase, que en inglés es de lo más común.
    # Medido: "the video is about to begin" y "we should begin with the
    # mayas" la disparaban — y las dos son cosas que se dicen justamente
    # en una sala con videos sobre los mayas.
    # Tampoco "start the tour": el modelo la oye "toward the tour" en
    # limpio y "the tour" degradada, así que nunca matchea.
    "en": {"let's begin", "begin the tour", "i'm ready"},
}
_PALABRAS_ACTIVACION = set().union(*_ACTIVACION.values())
# El despertar se escucha con VOCABULARIO ABIERTO, no con gramática cerrada.
# Probamos lo segundo y salió peor: al restringir el grafo a las frases de
# activación, el decodificador queda obligado a elegir una y "vamos a la otra
# sala" se volvía "comenzamos". La gramática cerrada sirve cuando la respuesta
# ES una de las opciones (la pregunta de idioma); acá casi nunca lo es.


def _normalizar(texto: str) -> str:
    """Minúsculas y sólo palabras, separadas por un espacio.

    Se aplica IGUAL a la frase oída y a la clave buscada. Si sólo se
    normaliza un lado, las claves con apóstrofo nunca matchean: la frase
    "let's begin" se tokeniza como "let s begin", así que buscar la clave
    literal "let's begin" falla en silencio para siempre."""
    return " ".join(re.findall(r"\w+", texto.lower()))


def _dijo(frase: str, claves: set[str]) -> bool:
    """True si `frase` contiene alguna `clave` como PALABRA(S) completas.

    Normaliza ambos lados y busca cada clave con límites de palabra (\\b).
    Evita el footgun del match por subcadena: "no" ya no se dispara dentro
    de "bueno"/"conocían", y soporta claves multi-palabra como "hasta
    luego" o "empecemos de nuevo"."""
    secuencia = _normalizar(frase)
    return any(re.search(rf"\b{re.escape(_normalizar(clave))}\b", secuencia)
               for clave in claves)


def esperar_activacion() -> None:
    """Reposo por voz: bloquea hasta oír una frase de activación.

    Escucha en bucle con los DOS modelos Vosk en paralelo, cada uno con la
    gramática cerrada de su idioma, e ignora todo lo demás. Es el estado
    dormido entre visitantes: MEXA no detecta ni se mueve hasta que alguien
    la despierta, en español o en inglés. Como sólo se escucha acá (no
    durante la charla), no choca con el resto de los comandos de voz.

    Escucha con vocabulario ABIERTO a propósito: acá el visitante casi
    siempre está diciendo cualquier otra cosa, y el modelo necesita poder
    decodificarla como lo que es en vez de forzarla contra una frase de
    activación. Ver tests/test_activacion.py."""
    print("[DIALOGO] MEXA en reposo. Decí 'comencemos' / \"let's begin\" para activarla.")
    while True:
        textos = escuchar_multilingue(timeout=8, idiomas=_ACTIVACION.keys())
        if any(_dijo(t, _PALABRAS_ACTIVACION) for t in textos.values()):
            print("[DIALOGO] Activada por voz.")
            return


def _seleccionar_idioma() -> str:
    """Pregunta el idioma preferido y retorna 'es' o 'en'.

    NO matchea texto: delega en `escuchar_idioma`, que corre los dos
    modelos Vosk con gramática cerrada sobre el mismo audio. Buscar
    "english" en la salida del modelo español era frágil: ese modelo no
    tiene los fonemas /ɪ/ ni /ʃ/, y con el ruido real de la exhibición
    la pronunciación inglesa se le desarmaba."""
    cambiar_expresion("pensando")
    hablar("Hi, I am MEXA. Would you prefer Spanish or English?")
    for _ in range(INTENTOS_MAX):
        cambiar_expresion("escuchando")
        idioma = escuchar_idioma(timeout=8)
        if idioma:
            return idioma
        cambiar_expresion("hablando")
        hablar("Please say 'español' or 'English'.")
    return "es"   # museo en México: ante la duda, español


def _ciclo_preguntas(f: dict, idioma: str) -> Resultado:
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
        pregunta = escuchar_pregunta(timeout=8, idioma=idioma)

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
    # MEXA acaba de moverse: el objetivo enganchado durante el acercamiento
    # quedó anclado a coordenadas de ANTES del avance. Se suelta para que el
    # voto de posicion_cara() vuelva a elegir a quien tiene ahora en frente.
    reiniciar_objetivo()
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
    #
    # Se oye con los DOS modelos sobre el MISMO audio, cada uno con la
    # gramática cerrada de las palabras que sabe pronunciar. Dos razones:
    #
    #  1. El nombre de una civilización es un NOMBRE PROPIO, y el visitante
    #     lo dice como le sale. "Olmecas", "Toltecas" y "Mixteca" viven en el
    #     léxico español y en el inglés NO existen: sin el oído español, un
    #     visitante que elige inglés no puede pedirlas jamás.
    #  2. La gramática cerrada sube los aciertos de 19/72 a 46/72 y sostiene
    #     el reconocimiento cuando entra ruido de sala.
    #
    # `detectar_civilizacion_multi` exige que los modelos no se contradigan
    # antes de dar la elección por buena.
    gramaticas = {i: json.dumps(g)
                  for i, g in contenido.GRAMATICA_CIVILIZACIONES.items()}
    video_info = None
    intentos = 0
    while video_info is None and intentos < INTENTOS_MAX:
        cambiar_expresion("escuchando")
        textos = escuchar_multilingue(10, list(gramaticas), gramaticas)
        video_info = contenido.detectar_civilizacion_multi(textos, idioma)
        if video_info is None:
            intentos += 1
            cambiar_expresion("hablando")
            # Distinguir "no oí nada" de "oí algo que no era una civilización":
            # al visitante le sirve saber si tiene que hablar más fuerte o
            # elegir otra cosa.
            hablar(f["no_entendio"] if not any(textos.values())
                   else f["no_reconocio"].format(oferta=oferta))

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
    return _ciclo_preguntas(f, idioma)
