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
    luego" o "empecemos de nuevo".

    OJO: esto pregunta si la frase CONTIENE la clave. Para las palabras de
    control de la conversación eso NO alcanza — usá `_es_respuesta`."""
    secuencia = _normalizar(frase)
    return any(re.search(rf"\b{re.escape(_normalizar(clave))}\b", secuencia)
               for clave in claves)


# Palabras que pueden sobrar alrededor de una respuesta sin cambiar lo que
# significa: cortesía y muletillas. NO se listan sustantivos ni verbos — si
# sobra contenido, entonces la frase era una pregunta y no una respuesta.
_RELLENO = {
    "gracias", "muchas", "mucha", "por", "favor", "señor", "señora",
    "thanks", "thank", "you", "please", "sir", "maam", "ma", "am",
    "ok", "okay", "bueno", "listo", "ya", "eh", "este", "mexa",
}


def _es_respuesta(frase: str, claves: set[str]) -> bool:
    """True si la frase ES esa respuesta, no si apenas la CONTIENE.

    POR QUÉ NO ALCANZA `_dijo`. MEXA pregunta "¿tienes alguna pregunta?" y
    escucha con vocabulario ABIERTO, así que lo que vuelve puede ser una
    respuesta corta o una pregunta entera. Buscar la palabra suelta confunde
    las dos cosas, y en español la confusión es constante: "¿por qué NO
    usaban la rueda?" se leía como "no tengo preguntas" y MEXA se despedía a
    mitad de la visita. "¿cuándo va a TERMINAR el video?" APAGABA el robot.

    Un "no" solo significa "no tengo preguntas". Un "no" adentro de seis
    palabras significa lo contrario: ES la pregunta. La regla, entonces: se
    saca del texto TODA clave que aparezca, y lo que queda tiene que ser
    puro relleno de cortesía. Si sobró contenido, era una pregunta.

    Las claves se sacan de la más larga a la más corta para que "no gracias"
    se consuma entera antes de que "no" le coma la mitad.

    ASIMETRÍA DE COSTOS. Irse de más es caro — MEXA abandona a alguien que
    estaba preguntando. Irse de menos es barato: contesta de más, y el
    visitante se despide o se va (lo agarra el PIR). Ante la duda, NO irse:
    por eso el relleno es corto y no incluye ni sustantivos ni verbos.
    """
    secuencia = _normalizar(frase)
    if not _dijo(secuencia, claves):
        return False
    for clave in sorted(claves, key=len, reverse=True):
        secuencia = re.sub(rf"\b{re.escape(_normalizar(clave))}\b", " ", secuencia)
    return all(palabra in _RELLENO for palabra in secuencia.split())


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
    cambiar_expresion("dormido")
    while True:
        textos = escuchar_multilingue(timeout=8, idiomas=_ACTIVACION.keys())
        if any(_dijo(t, _PALABRAS_ACTIVACION) for t in textos.values()):
            print("[DIALOGO] Activada por voz.")
            # Se despierta de golpe y enseguida queda atenta buscando a la
            # persona. El sobresalto tiene que durar POCO: sostenido deja de
            # leerse como sobresalto y pasa a leerse como cara rara.
            cambiar_expresion("sorprendido")
            time.sleep(1.2)
            cambiar_expresion("escuchando")
            return


def _seleccionar_idioma() -> str:
    """Pregunta el idioma preferido y retorna 'es' o 'en'.

    NO matchea texto: delega en `escuchar_idioma`, que corre los dos
    modelos Vosk con gramática cerrada sobre el mismo audio. Buscar
    "english" en la salida del modelo español era frágil: ese modelo no
    tiene los fonemas /ɪ/ ni /ʃ/, y con el ruido real de la exhibición
    la pronunciación inglesa se le desarmaba."""
    # Saluda CONTENTA, no pensando: es lo primero que ve cada visitante, y
    # "pensando" además tiene boca_vol=0, así que MEXA daba la bienvenida con
    # la boca congelada. Lo encontró tests/test_expresiones.py.
    cambiar_expresion("feliz")
    hablar("Hi, I am MEXA. Would you prefer Spanish or English?")
    for _ in range(INTENTOS_MAX):
        cambiar_expresion("escuchando")
        idioma = escuchar_idioma(timeout=8)
        if idioma:
            return idioma
        cambiar_expresion("confundido")
        hablar("Please say 'español' or 'English'.")
    return "es"   # museo en México: ante la duda, español


def _despedirse(f: dict, contenta: bool) -> None:
    """Se despide con la cara que corresponde a CÓMO terminó la charla.

    Contenta si el visitante se despidió; algo triste si lo dejaron hablando
    solo (silencio, sin respuestas, sin elegir civilización). Es la diferencia
    entre "chau, gracias por venir" y "bueno... me quedé sola". Un robot que
    se despide igual en los dos casos no se lee como que le importe.

    La pausa de 3 s es la de siempre: le da al visitante el tiempo de registrar
    que MEXA está por cerrar, en vez de soltarle la despedida encima."""
    cambiar_expresion("feliz" if contenta else "triste")
    time.sleep(3)
    hablar(f["despedida"])


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
            _despedirse(f, contenta=False)      # se quedó callado y se fue
            return Resultado.ESPERAR

        cambiar_expresion("escuchando")
        pregunta = escuchar_pregunta(timeout=8, idioma=idioma)

        if not pregunta:
            intentos_sin_respuesta += 1
            if intentos_sin_respuesta >= INTENTOS_MAX:
                _despedirse(f, contenta=False)  # tres veces sin oír nada
                return Resultado.ESPERAR
            cambiar_expresion("confundido")
            hablar(f["no_entendio"])
            continue

        intentos_sin_respuesta = 0
        tiempo_ultimo = time.time()

        if _es_respuesta(pregunta, _PALABRAS_REINICIO):
            return Resultado.REINICIAR

        if _es_respuesta(pregunta, _PALABRAS_APAGAR):
            _despedirse(f, contenta=True)
            return Resultado.APAGAR

        if _es_respuesta(pregunta, _PALABRAS_SALIDA):
            _despedirse(f, contenta=True)       # se despidió él: buena onda
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

    oferta = ", ".join(contenido.nombres_ofrecidos(idioma))

    # 1. Presentación y oferta de civilizaciones
    cambiar_expresion("feliz")
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
    gramaticas = contenido.gramaticas_json()
    video_info = None
    intentos = 0
    while video_info is None and intentos < INTENTOS_MAX:
        cambiar_expresion("escuchando")
        textos = escuchar_multilingue(10, list(gramaticas), gramaticas)
        video_info = contenido.detectar_civilizacion_multi(textos, idioma)
        if video_info is None:
            intentos += 1
            cambiar_expresion("confundido")
            # Distinguir "no oí nada" de "oí algo que no era una civilización":
            # al visitante le sirve saber si tiene que hablar más fuerte o
            # elegir otra cosa.
            hablar(f["no_entendio"] if not any(textos.values())
                   else f["no_reconocio"].format(oferta=oferta))

    if video_info is None:
        _despedirse(f, contenta=False)          # no llegó a elegir nada
        return Resultado.ESPERAR

    ruta_video, nombre_civ_es = video_info
    nombre_civ = contenido.NOMBRES_EN[nombre_civ_es] if idioma == "en" else nombre_civ_es

    # MEXA entendió qué eligió el visitante. Un guiño de complicidad antes de
    # entusiasmarse: necesita durar para leerse — abajo de medio segundo se lo
    # come la transición y no se ve nunca.
    cambiar_expresion("guino")
    time.sleep(0.45)

    # 3. Reproducir el video en el idioma seleccionado
    cambiar_expresion("emocionado")
    hablar(f["intro_video"].format(nombre=nombre_civ))
    reproducir_video(ruta_video)

    # 5. Preguntar si tienen dudas
    time.sleep(3)
    cambiar_expresion("feliz")
    hablar(f["post_video"].format(nombre=nombre_civ))

    # 6 y 7. Ciclo de preguntas con IA + despedida. Propaga el Resultado.
    return _ciclo_preguntas(f, idioma)
