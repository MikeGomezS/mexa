# ============================================================
#  MEXA — Contenido e internacionalización
#
#  DATOS, no lógica: el catálogo de civilizaciones (palabra clave
#  -> video por idioma), los nombres para hablar y las frases
#  fijas en español/inglés. Vive separado del flujo para que
#  `main.py` orqueste y este módulo solo describa QUÉ dice MEXA.
# ============================================================

from .modulo_proyector import CARPETA_VIDEOS
import json
import os
import re

# ── Civilizaciones disponibles ───────────────────────────────
# Cada entrada: palabra_clave → (ruta_video_es, ruta_video_en, nombre_para_hablar)
_ESP = os.path.join(CARPETA_VIDEOS, "español")
_ENG = os.path.join(CARPETA_VIDEOS, "ingles")

CIVILIZACIONES: dict[str, tuple[str, str, str]] = {
    "maya":         (_ESP + "/Mayas_esp.mp4",       _ENG + "/Mayas_eng.mp4",       "los Mayas"),
    "mayas":        (_ESP + "/Mayas_esp.mp4",       _ENG + "/Mayas_eng.mp4",       "los Mayas"),
    "azteca":       (_ESP + "/Aztecas_esp.mp4",     _ENG + "/Aztecas_eng.mp4",     "los Aztecas"),
    "aztecas":      (_ESP + "/Aztecas_esp.mp4",     _ENG + "/Aztecas_eng.mp4",     "los Aztecas"),
    "mexica":       (_ESP + "/Aztecas_esp.mp4",     _ENG + "/Aztecas_eng.mp4",     "los Aztecas"),
    "mexicas":      (_ESP + "/Aztecas_esp.mp4",     _ENG + "/Aztecas_eng.mp4",     "los Aztecas"),
    "teotihuacan":  (_ESP + "/Teotihuacan_esp.mp4", _ENG + "/Teotihuacan_eng.mp4", "Teotihuacán"),
    "teotihuacán":  (_ESP + "/Teotihuacan_esp.mp4", _ENG + "/Teotihuacan_eng.mp4", "Teotihuacán"),
    "olmeca":       (_ESP + "/Olmecas_esp.mp4",     _ENG + "/Olmecas_eng.mp4",     "los Olmecas"),
    "olmecas":      (_ESP + "/Olmecas_esp.mp4",     _ENG + "/Olmecas_eng.mp4",     "los Olmecas"),
    "tolteca":      (_ESP + "/Toltecas_esp.mp4",    _ENG + "/Toltecas_eng.mp4",    "los Toltecas"),
    "toltecas":     (_ESP + "/Toltecas_esp.mp4",    _ENG + "/Toltecas_eng.mp4",    "los Toltecas"),
    "zapoteca":     (_ESP + "/Zapotecas_esp.mp4",   _ENG + "/Zapotecas_eng.mp4",   "los Zapotecas"),
    "zapotecas":    (_ESP + "/Zapotecas_esp.mp4",   _ENG + "/Zapotecas_eng.mp4",   "los Zapotecas"),
    "mixteca":      (_ESP + "/Mixtecas_esp.mp4",    _ENG + "/Mixtecas_eng.mp4",    "los Mixtecas"),
    "mixtecas":     (_ESP + "/Mixtecas_esp.mp4",    _ENG + "/Mixtecas_eng.mp4",    "los Mixtecas"),
    # Formas en inglés. El modelo Vosk en-us transcribe "Aztecs", no
    # "aztecas": sin estas claves, un visitante en inglés jamás elegía
    # civilización. OJO: el match es por PALABRA COMPLETA, así que el
    # singular ya NO cubre al plural — cada forma que el léxico Vosk puede
    # escribir va enumerada aparte. Cuáles existen lo dice
    # `python3 tests/calibrar_vocabulario.py auditar`.
    "aztec":        (_ESP + "/Aztecas_esp.mp4",     _ENG + "/Aztecas_eng.mp4",     "los Aztecas"),
    "aztecs":       (_ESP + "/Aztecas_esp.mp4",     _ENG + "/Aztecas_eng.mp4",     "los Aztecas"),
    "olmec":        (_ESP + "/Olmecas_esp.mp4",     _ENG + "/Olmecas_eng.mp4",     "los Olmecas"),
    "toltec":       (_ESP + "/Toltecas_esp.mp4",    _ENG + "/Toltecas_eng.mp4",    "los Toltecas"),
    "zapotec":      (_ESP + "/Zapotecas_esp.mp4",   _ENG + "/Zapotecas_eng.mp4",   "los Zapotecas"),
    "mixtec":       (_ESP + "/Mixtecas_esp.mp4",    _ENG + "/Mixtecas_eng.mp4",    "los Mixtecas"),
    # "toltec" no existe en el léxico en-us, así que en inglés los Toltecas
    # sólo se pueden pedir por su capital, que sí existe: Tula.
    "tula":         (_ESP + "/Toltecas_esp.mp4",    _ENG + "/Toltecas_eng.mp4",    "los Toltecas"),
}

# REGLA DE ORO: acá sólo va lo que MEXA puede RECONOCER por voz.
# Ofrecer una civilización cuyo nombre no está en el léxico de ningún modelo
# Vosk es peor que no ofrecerla: con gramática cerrada el decodificador no
# puede contestar "eso no estaba en la lista", así que devuelve la opción más
# parecida y MEXA proyecta un video que nadie pidió. Antes de sumar una
# entrada, verificá que su nombre exista con
# `python3 tests/calibrar_vocabulario.py auditar`.
NOMBRES_DISPONIBLES = [
    "los Mayas", "los Aztecas", "Teotihuacán", "los Olmecas", "los Toltecas",
    "los Zapotecas", "los Mixtecas",
]

NOMBRES_EN = {
    "los Mayas":      "the Mayas",
    "los Aztecas":    "the Aztecs",
    "Teotihuacán":    "Teotihuacán",
    "los Olmecas":    "the Olmecs",
    "los Toltecas":   "the Toltecs",
    "los Zapotecas":  "the Zapotecs",
    "los Mixtecas":   "the Mixtecs",
}

# El puente entre el catálogo de videos y la base de conocimiento. Las dos
# listas hablan de las mismas siete civilizaciones pero con claves distintas:
# acá el nombre que MEXA PRONUNCIA ("los Mayas"), allá el tema que indexa los
# hechos ("mayas").
#
# Sirve para SEMBRAR el tema en cuanto el visitante elige: terminado el video
# de los Mayas, su primera pregunta ya cae en los hechos mayas aunque no
# nombre la civilización ("¿y cómo escribían?"). Sin esto, ese dato —que
# `dialogo.ciclo_interaccion` ya tenía en la mano— se perdía.
#
# Las claves son las de NOMBRES_DISPONIBLES y los valores los de
# `conocimiento.CIVILIZACIONES_VALIDAS`. Si se suma una civilización hay que
# tocar las tres listas; `tests/test_fuera_de_tema.py` verifica que no se
# desincronicen.
TEMAS_CONOCIMIENTO = {
    "los Mayas":      "mayas",
    "los Aztecas":    "aztecas",
    "Teotihuacán":    "teotihuacan",
    "los Olmecas":    "olmecas",
    "los Toltecas":   "toltecas",
    "los Zapotecas":  "zapotecas",
    "los Mixtecas":   "mixtecas",
}

# Lo que NO se ofrece en inglés, y por qué. Medido en test_civilizaciones.py
# (4 condiciones de ruido): en inglés dan 0/4, ni una sola vez.
#   'olmec' y 'toltec' NO EXISTEN en el léxico en-us de Vosk, así que el oído
#   inglés no puede escribirlas ni queriendo. El rescate por oído español
#   (dialogo.py) alcanza para Mixtecas — 2/4 — pero para éstas no llega nunca.
# Ofrecerlas es prometer algo que MEXA no puede cumplir, y con gramática
# cerrada el precio no es quedarse callada: es proyectar el video equivocado.
# En ESPAÑOL las siete andan 4/4 y se siguen ofreciendo todas.
_NO_OFRECIBLES_EN = {"los Olmecas", "los Toltecas"}


def nombres_ofrecidos(idioma: str) -> list[str]:
    """Los nombres que MEXA NOMBRA EN VOZ ALTA, en el idioma de la charla.

    Una sola función porque antes esta lista se armaba por duplicado en
    `main.py` y en `dialogo.py`, y dos copias de una regla es una regla que
    tarde o temprano se contradice a sí misma.
    """
    if idioma != "en":
        return list(NOMBRES_DISPONIBLES)
    return [NOMBRES_EN[n] for n in NOMBRES_DISPONIBLES
            if n not in _NO_OFRECIBLES_EN]

# ── Gramática cerrada para la pregunta de civilización ───────
# MEXA acaba de hacer una pregunta CERRADA ("¿sobre cuál civilización?"),
# así que el decodificador no tiene por qué elegir entre 64 mil palabras:
# se le dan sólo las que puede contestar. Medido: los aciertos pasan de
# 19/72 a 46/72 y dejan de derrumbarse con el ruido de sala.
#
# CADA MODELO RECIBE SÓLO LO QUE SABE PRONUNCIAR. Una palabra fuera del
# léxico rompe la gramática, así que estas listas NO se inventan: salen de
# `vosk_model_find_word` y las verifica tests/test_civilizaciones.py.
#
# OJO — EL PRECIO DE LA GRAMÁTICA CERRADA: al decodificador se le quita la
# posibilidad de decir "esto no estaba en la lista". Si el visitante pide algo
# cuyo nombre no figura acá, va a contestar la opción más parecida en vez de
# callarse, y no hay señal para distinguir ese invento de un acierto. Por eso
# toda opción ofrecida debe tener su palabra en esta gramática, y por eso
# `detectar_civilizacion_multi` exige acuerdo entre los dos modelos.
GRAMATICA_CIVILIZACIONES: dict[str, list[str]] = {
    "es": ["mayas", "aztecas", "mexicas", "teotihuacán", "olmeca", "toltecas",
           "zapotecas", "mixteca", "[unk]"],
    "en": ["mayas", "aztec", "aztecs", "teotihuacan", "zapotec", "tula", "[unk]"],
}


def gramaticas_json() -> dict[str, str]:
    """La gramática ya serializada, tal como la recibe Vosk: {idioma: json}.

    ensure_ascii=False NO ES COSMÉTICO, ES EL PUNTO DE ESTA FUNCIÓN. Con el
    `ensure_ascii=True` que trae `json.dumps` por defecto, "teotihuacán" viaja
    como el literal `teotihuac\u00e1n` — y VOSK NO DESESCAPA: busca esa cadena
    tal cual, no la encuentra y DESCARTA la palabra en silencio (avisa con
    "Ignoring word missing in vocabulary"). El oído español perdía Teotihuacán
    entero, y los aciertos que se veían los salvaba el modelo inglés, que la
    escribe sin tilde y por eso nunca sufrió el escapado.

    Existe como función UNA para que producción y test no puedan divergir: el
    defecto vivió meses porque `dialogo.py` y `test_civilizaciones.py`
    serializaban cada uno por su cuenta, y el test validaba la lista de Python
    (donde la tilde está bien) en vez de la cadena que se manda de verdad.
    """
    return {i: json.dumps(g, ensure_ascii=False)
            for i, g in GRAMATICA_CIVILIZACIONES.items()}


FRASES = {
    "es": {
        "saludo_civ":   "¡Hola! Soy MEXA, tu guía de la historia y cultura de México. ¿Sobre cuál civilización quieres aprender hoy?",
        "no_reconocio": "No reconocí esa civilización. Tenemos: {oferta}. ¿Cuál te gustaría?",
        "no_entendio":  "No escuché bien. ¿Puedes repetir, por favor?",
        "intro_video":  "Perfecto, te voy a mostrar un video sobre {nombre}.",
        "post_video":   "Espero que hayas disfrutado el video sobre {nombre}. ¿Tienes alguna pregunta?",
        "despedida":    "Fue un placer compartir cultura contigo. ¡Hasta pronto!",
        # Redirige sin regañar y VUELVE A OFRECER: el visitante que pregunta
        # fuera de tema casi nunca está jodiendo, es que no sabe qué puede
        # preguntar. Enumerar las civilizaciones convierte el rechazo en una
        # invitación, que es la diferencia entre una pared y un guía.
        "fuera_de_tema": "Solo puedo hablar de las civilizaciones de México. Tenemos: {oferta}. ¿Qué te gustaría saber?",
        # "¿Cómo te llamas?" es la pregunta más humana que le hacen, y es la
        # ÚNICA fuera de tema con respuesta fija. NO lleva {oferta}: cuando
        # esto se dispara el visitante ya eligió civilización y vio el video,
        # así que enumerarle las siete otra vez es ruido en el TTS.
        "identidad":     "Me llamo MEXA y soy un robot guía. Estoy aquí para contarte sobre las civilizaciones de México. ¿Qué te gustaría saber?",
    },
    "en": {
        "saludo_civ":   "Hello! I am MEXA, your guide to the history and culture of Mexico. Which civilization would you like to learn about today?",
        "no_reconocio": "I didn't recognize that civilization. We have: {oferta}. Which one would you like?",
        "no_entendio":  "I didn't catch that. Could you repeat, please?",
        "intro_video":  "Perfect, I will show you a video about {nombre}.",
        "post_video":   "I hope you enjoyed the video about {nombre}. Do you have any questions?",
        "despedida":    "It was a pleasure sharing culture with you. See you soon!",
        "fuera_de_tema": "I can only talk about the civilizations of Mexico. We have: {oferta}. What would you like to know?",
        "identidad":     "My name is MEXA and I am a robot guide. I am here to tell you about the civilizations of Mexico. What would you like to know?",
    },
}


# Un patrón por clave, compilado UNA vez al importar. `detectar_civilizacion`
# corre en cada intento del visitante; recompilar treinta patrones por frase
# es tirar CPU de la Raspberry sin necesidad.
_PATRONES = {clave: re.compile(rf"\b{re.escape(clave)}\b")
             for clave in CIVILIZACIONES}


_UNK = "[unk]"


def _podia_nombrar(idioma_modelo: str, nombre: str) -> bool:
    """¿La gramática de ese modelo tenía alguna palabra para esa civilización?

    Es lo que separa un "[unk]" que desmiente de uno que sólo se calla.
    """
    return any(clave in GRAMATICA_CIVILIZACIONES.get(idioma_modelo, ())
               for clave, (_es, _en, n) in CIVILIZACIONES.items() if n == nombre)


def detectar_civilizacion_multi(textos: dict[str, str],
                                idioma: str) -> tuple[str, str] | None:
    """Decide la civilización a partir de lo que oyó CADA modelo por separado.

    `textos` es {idioma_del_modelo: texto}, tal como lo devuelve
    `escuchar_multilingue`. `idioma` es el de la conversación, y sólo decide
    en qué idioma se proyecta el video.

    Se evalúa cada texto por su cuenta y NUNCA se concatenan: pegar las
    salidas de dos modelos fabrica coincidencias que nadie dijo.

    El criterio es el mismo que usa `escuchar_idioma`, y por el mismo motivo:
      - los dos modelos coinciden, o sólo uno reconoce algo → esa civilización
      - se contradicen, o ninguno reconoce nada             → None (repreguntar)

    Exigir acuerdo es lo que sostiene a la gramática cerrada. Forzado a elegir
    entre una lista, un modelo contesta cualquier cosa antes que callarse; que
    el otro modelo lo desmienta convierte ese invento en una repregunta —
    barata— en vez de en el video equivocado, que es caro.

    "[unk]" NO SIEMPRE ES SILENCIO, y esa distinción es la que evita proyectar
    cualquier cosa. Si un modelo dijo "[unk]" TENIENDO la palabra en su
    gramática, no se abstuvo: DESMINTIÓ. Si ni siquiera la tenía, no podía
    nombrarla ni queriendo y su "[unk]" no dice nada.

    Caso real que motivó la regla (medido en tests/test_civilizaciones.py): un
    visitante pide 'the olmecs', que en inglés NO se puede pedir; el oído
    español contesta "teotihuacán" y el inglés "[unk]". El inglés TIENE
    'teotihuacan' en su gramática, así que ese "[unk]" es un NO en la cara —
    y sin esta regla MEXA proyectaba Teotihuacán.

    SÓLO VETA EL OÍDO DEL IDIOMA QUE SE ESTÁ HABLANDO. El otro modelo está
    escuchando una lengua que no es la suya: que diga "[unk]" es lo NORMAL, no
    una opinión. Medido: sin esta restricción los aciertos se derrumban de 42
    a 30 sobre 56 — un visitante decía "los mayas" en español, el oído inglés
    se abstenía (como corresponde) y MEXA descartaba una elección perfecta.

    Lo que la regla NO rompe: el rescate por oído español. Cuando el español
    reconoce 'mixteca' y el inglés dice "[unk]", el inglés no tenía 'mixtec'
    en su gramática — no podía nombrarla. Ese "[unk]" sigue siendo silencio y
    la elección se acepta.
    """
    encontrados = {}
    abstenidos = []
    for idioma_modelo, texto in textos.items():
        if not texto:
            continue
        hallazgo = detectar_civilizacion(texto, idioma)
        if hallazgo:
            encontrados[idioma_modelo] = hallazgo
        elif _UNK in texto:
            abstenidos.append(idioma_modelo)

    if not encontrados:
        return None
    nombres = {nombre for _ruta, nombre in encontrados.values()}
    if len(nombres) > 1:
        return None          # se contradicen: mejor repreguntar

    elegido = next(iter(encontrados.values()))
    if idioma in abstenidos and _podia_nombrar(idioma, elegido[1]):
        return None          # el oído nativo dijo "[unk]" pudiendo nombrarla: es un NO
    return elegido


def detectar_civilizacion(texto: str, idioma: str) -> tuple[str, str] | None:
    """Retorna (ruta_video, nombre) según el idioma si el texto menciona una civilización.

    Compara por PALABRA COMPLETA, no por subcadena. Con subcadena, la clave
    "mexica" se disparaba dentro de "mexicana", "mexicano" y "mexican": un
    visitante que pedía comida mexicana se comía el video de los Aztecas.
    Medido: 7 de 23 frases de prueba enganchaban mal; ahora ninguna.

    Lo que "maya" sí sigue atrapando en "me gusta la maya" no es un error de
    esta función: ahí "maya" ES una palabra, y la ambigüedad es del idioma.
    """
    texto_lower = texto.lower()
    for clave, datos in CIVILIZACIONES.items():
        if _PATRONES[clave].search(texto_lower):
            ruta_es, ruta_en, nombre = datos
            return (ruta_en if idioma == "en" else ruta_es, nombre)
    return None
