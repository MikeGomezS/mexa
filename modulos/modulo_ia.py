# ============================================================
#  MEXA — Módulo 02: Motor de IA (Generación de respuestas)
#  Librería: ollama (modelo local en Raspberry Pi)
#  Instalar: curl -fsSL https://ollama.com/install.sh | sh
#            ollama pull llama3.2:1b
# ============================================================

import re
import ollama
from .conocimiento import CIVILIZACIONES_VALIDAS, contexto_de, resolver_tema

# ESTE PROMPT ES LA SEGUNDA LÍNEA DE DEFENSA, NO LA PRIMERA.
# Antes decía "si te preguntan algo que no es sobre México, responde que solo
# puedes hablar de esos temas", y eso era todo el filtro que había. No alcanza:
# es una prohibición NEGATIVA dirigida a llama3.2:1b, y un modelo de mil
# millones de parámetros no tiene con qué sostenerla — el mismo motivo por el
# que `conocimiento.buscar_contexto` documenta que tampoco puede desconfiar
# del contexto que le pasan. El filtro de verdad es `resolver_tema`, que corre
# en CÓDIGO y decide antes de que el modelo vea la pregunta.
# Lo que queda acá cubre el hueco que el código no puede cerrar: una pregunta
# fuera de tema que heredó tema igual (la lista negra es incompleta a
# propósito). Con los hechos delante y la orden de no salirse de ellos, el 1b
# falla hacia "solo puedo hablar de las civilizaciones" en vez de inventar.
_SISTEMA_BASE = """Eres MEXA, un robot educativo que habla ÚNICAMENTE de las
civilizaciones de México: Teotihuacán, aztecas, mayas, olmecas, toltecas,
zapotecas y mixtecas. Responde de forma clara, amable y en
máximo 2 oraciones. Hablas a personas de todas las edades.
Usa SOLO los hechos verificados que te doy. Si la pregunta no se puede
responder con esos hechos, di amablemente que solo puedes hablar de las
civilizaciones de México. NUNCA inventes datos ni hables de otros temas.
NO uses paréntesis, aclaraciones ni autocorrecciones en medio del texto.
Escribe oraciones limpias y directas, como si hablaras en voz alta."""

_idioma: str = "es"  # "es" o "en"

# CIVILIZACIÓN DE LA QUE SE VIENE HABLANDO. Es lo que hace que una pregunta
# de seguimiento signifique algo: "¿y quién la construyó?" no nombra ninguna
# civilización, así que sin esta memoria llegaba al modelo con contexto vacío
# y llama3.2:1b contestaba de su propia cabeza.
#
# NO sale del historial de la charla. El historial guarda el TEXTO de lo que
# se dijo, no los HECHOS: `_mensajes` inyecta el contexto SÓLO en el turno
# actual, a propósito, porque arrastrarlo repaga 5-25 s de procesamiento de
# prompt en la Pi por cada turno. Así que el tema se guarda aparte, que
# cuesta una sola palabra en lugar de 400 caracteres por pregunta vieja.
_tema_actual: str | None = None

_INSTRUCCION_IDIOMA = {
    "es": "IMPORTANTE: responde SIEMPRE en español, sin importar el idioma en que se haga la pregunta. Aunque el usuario pregunte en inglés u otro idioma, tu respuesta DEBE ser en español.",
    "en": "IMPORTANT: ALWAYS respond in English, no matter what language the user asks in. Even if the question is in Spanish or another language, your response MUST be in English.",
}

# Rechazo de última instancia. `dialogo` intercepta la pregunta fuera de tema
# ANTES de llegar acá y contesta con `FRASES[idioma]["fuera_de_tema"]`, que
# además enumera las civilizaciones disponibles. Esta versión corta existe
# para que llamar a la IA sin filtrar no se convierta igual en una respuesta
# inventada: el peor resultado posible no es que MEXA se niegue, es que un
# modelo de mil millones de parámetros hable sin un solo hecho delante.
_FUERA_DE_TEMA = {
    "es": "Solo puedo hablar de las civilizaciones de México. ¿Qué te gustaría saber sobre ellas?",
    "en": "I can only talk about the civilizations of Mexico. What would you like to know about them?",
}

_MENSAJES_ERROR = {
    "es": ("No escuché bien tu pregunta. ¿Puedes repetirla, por favor?",
           "Lo siento, tuve un problema al procesar tu pregunta. Intenta de nuevo."),
    "en": ("I didn't catch your question. Could you repeat it, please?",
           "Sorry, I had a problem processing your question. Please try again."),
}

def establecer_idioma(idioma: str):
    """Define el idioma de respuesta para toda la sesión ('es' o 'en')."""
    global _idioma
    _idioma = idioma if idioma in ("es", "en") else "es"
    print(f"[IA] Idioma establecido: {_idioma}")

def establecer_tema(tema: str | None):
    """Siembra la civilización de la que se va a hablar.

    La llama `dialogo` en cuanto el visitante ELIGE su civilización, antes de
    que empiecen las preguntas. Ese dato ya existía —`ciclo_interaccion` lo
    tiene en `nombre_civ_es`— y no llegaba hasta acá, así que la primera
    pregunta de seguimiento arrancaba sin tema aunque el visitante acabara de
    ver el video entero.
    """
    global _tema_actual
    _tema_actual = tema if tema in CIVILIZACIONES_VALIDAS else None
    print(f"[IA] Tema establecido: {_tema_actual}")


def tema_para(pregunta: str) -> str | None:
    """El tema de esta pregunta, o None si hay que rechazarla.

    Resuelve contra el tema pegajoso y lo ACTUALIZA si la pregunta cambia de
    civilización. La decisión en sí vive en `conocimiento.resolver_tema`: acá
    sólo se le suma el estado de la conversación.

    EL TEMA SOBREVIVE AL RECHAZO. Si la pregunta se va de tema, `_tema_actual`
    NO se toca: el visitante pregunta cualquier cosa, MEXA lo redirige, y el
    siguiente "¿y cuándo la construyeron?" sigue cayendo en la civilización
    correcta. Borrarlo dejaría la charla muerta después de un solo desvío.
    """
    global _tema_actual
    tema = resolver_tema(pregunta, _tema_actual)
    if tema is not None:
        _tema_actual = tema
    return tema


def _sistema() -> str:
    return _SISTEMA_BASE + "\n" + _INSTRUCCION_IDIOMA[_idioma]

# Largo MÍNIMO del primer trozo, en caracteres. Se busca la coma A PARTIR de
# acá, así que una coma más temprana se ignora y MEXA no arranca diciendo un
# fragmento suelto de tres palabras. Más chico = habla antes pero suena picado;
# más grande = suena mejor pero el visitante mira a un robot callado.
# 25 sale de la medida: a 6.8 tokens/s en la Pi, ~8 tokens ≈ 1.2 s.
_MIN_PRIMER_TROZO = 25

# TOPE DURO del primer trozo. Sin esto no hay garantía ninguna: medido, el
# modelo puede escribir la primera coma recién en el carácter 94, y el visitante
# se come 17 segundos de silencio. Pasado este largo se corta en el último
# espacio, aunque quede a mitad de cláusula. A 6.8 tokens/s son ~2.4 s.
# Es un compromiso EXPLÍCITO: la costura se nota un poco, el silencio se nota
# muchísimo. Si suena mal, subilo; si MEXA tarda en arrancar, bajalo.
_MAX_PRIMER_TROZO = 60

_RE_CLAUSULA   = re.compile(r"[,;:]\s")   # corte de cláusula para el primer trozo
_RE_PARENTESIS = re.compile(r"\(.*?\)")  # elimina (no, espera... ¡México!)
_RE_ESPACIOS   = re.compile(r" {2,}")

# Historial de la conversación actual (máximo últimos 6 turnos = 3 intercambios).
# Permite preguntas de seguimiento como "¿y quién la construyó?"
_historial: list = []

_OPCIONES_OLLAMA = {
    "num_predict": 80,
    "num_thread":  4,    # limita threads para evitar thrashing en Pi
    "top_k":       40,   # reduce tokens candidatos por paso → más rápido
    "top_p":       0.9,
}

def _mensajes(contexto: str, pregunta: str) -> list:
    """Arma el prompt: sistema + historial + la pregunta actual CON sus hechos.

    EL CONTEXTO SÓLO VA EN EL TURNO ACTUAL, y esto no es cosmética. Antes el
    historial guardaba `f"{contexto}\n\nPregunta: {pregunta}"` completo, así
    que los ~400 caracteres de hechos de CADA pregunta vieja viajaban otra vez
    en cada turno — hasta 1200 caracteres de material ya consumido.

    Y eso se paga caro: procesar el prompt en esta Pi cuesta entre 5 y 25
    segundos, MEDIDO, y es lo primero que espera el visitante, antes de que se
    genere un solo token. El historial existe para que MEXA entienda "¿y quién
    la construyó?", no para volver a suministrarle datos que ya usó.
    """
    mensajes = [{"role": "system", "content": _sistema()}] + _historial[-6:]
    if contexto:
        mensajes[-1] = {"role": "user",
                        "content": f"{contexto}\n\nPregunta: {pregunta}"}
    return mensajes


def generar_respuesta(pregunta: str) -> str:
    """
    Recibe una pregunta de texto y regresa la respuesta de la IA.
    Mantiene el historial de la conversación para preguntas de seguimiento.
    El modelo corre localmente en la Raspberry Pi — no necesita internet.
    """
    if not pregunta:
        return _MENSAJES_ERROR[_idioma][0]

    tema = tema_para(pregunta)
    if tema is None:
        return _FUERA_DE_TEMA[_idioma]
    contexto = contexto_de(tema)
    _historial.append({"role": "user", "content": pregunta})
    mensajes = _mensajes(contexto, pregunta)
    print(f"[IA] Procesando: {pregunta} [tema: {tema}]")
    if contexto:
        print("[IA] Contexto verificado inyectado.")
    try:
        respuesta = ollama.chat(
            model="llama3.2:1b",  # modelo liviano para Raspberry Pi 5
            messages=mensajes,
            options=_OPCIONES_OLLAMA,
            keep_alive=-1,
        )
        texto = respuesta["message"]["content"]
        texto = _RE_PARENTESIS.sub("", texto)
        texto = _RE_ESPACIOS.sub(" ", texto).strip()
        _historial.append({"role": "assistant", "content": texto})
        print(f"[IA] Respuesta generada: {texto[:60]}...")
        return texto
    except Exception as e:
        _historial.pop()  # revertir la pregunta fallida
        print(f"[IA] Error: {e}")
        return _MENSAJES_ERROR[_idioma][1]

def generar_respuesta_stream(pregunta: str):
    """
    Igual que generar_respuesta pero yield-ea oraciones completas conforme
    la IA las genera. Permite que el TTS empiece a hablar sin esperar el
    texto completo — reduce la latencia de la primera respuesta.
    """
    if not pregunta:
        yield _MENSAJES_ERROR[_idioma][0]
        return

    tema = tema_para(pregunta)
    if tema is None:
        # OJO: en un generador `return valor` no emite nada — deja el valor en
        # el StopIteration, que `hablar_stream` no lee nunca, y MEXA se queda
        # MUDA. Hay que yield-earlo y recién después cortar.
        yield _FUERA_DE_TEMA[_idioma]
        return
    contexto = contexto_de(tema)
    _historial.append({"role": "user", "content": pregunta})
    mensajes = _mensajes(contexto, pregunta)
    print(f"[IA] Procesando (stream): {pregunta} [tema: {tema}]")

    try:
        stream = ollama.chat(
            model="llama3.2:1b",
            messages=mensajes,
            options=_OPCIONES_OLLAMA,
            keep_alive=-1,
            stream=True,
        )

        buffer = ""
        texto_completo = ""
        primero = True

        for chunk in stream:
            token = chunk["message"]["content"]
            buffer += token
            texto_completo += token

            # Yield cada oración completa en cuanto llega
            while True:
                match = re.search(r'[.!?]+\s', buffer)
                # EL PRIMER TROZO SE CORTA ANTES, en la primera coma útil.
                # El visitante no espera la respuesta: espera la PRIMERA PALABRA.
                # A 6.8 tokens/s (medido en la Pi), aguardar una oración entera
                # son ~12 s de silencio mirando a un robot mudo; cortar en la
                # primera coma útil lo baja a ~1.2 s.
                # El resto sigue saliendo por oración completa: para entonces MEXA
                # ya está hablando y Piper sintetiza 7x más rápido que el habla,
                # así que la cola nunca se queda corta.
                # ESTO SÓLO ES ACEPTABLE PORQUE hablar_stream ya no corta el audio
                # entre trozos (un solo pw-play). Con el corte viejo, partir en la
                # coma habría AGREGADO un silencio en mitad de la frase.
                corte = match.end() if match else None
                if primero and corte is None:
                    # .search(buffer, pos) — con patrón COMPILADO, porque
                    # re.search(pat, txt, 25) toma el 25 como FLAGS, no como
                    # posición, y buscaría desde el principio.
                    clausula = _RE_CLAUSULA.search(buffer, _MIN_PRIMER_TROZO)
                    if clausula:
                        corte = clausula.end()
                    elif len(buffer) >= _MAX_PRIMER_TROZO:
                        # Sin coma a la vista: cortar en el último espacio para
                        # no partir una palabra por la mitad.
                        espacio = buffer.rfind(" ", _MIN_PRIMER_TROZO,
                                               _MAX_PRIMER_TROZO)
                        corte = espacio + 1 if espacio > 0 else _MAX_PRIMER_TROZO
                if corte is None:
                    break
                primero = False
                oracion = buffer[:corte].strip()
                oracion = _RE_PARENTESIS.sub("", oracion)
                oracion = _RE_ESPACIOS.sub(" ", oracion).strip()
                if oracion:
                    print(f"[IA] Oración lista: {oracion[:60]}...")
                    yield oracion
                buffer = buffer[corte:]

        # Resto sin puntuación final
        if buffer.strip():
            oracion = _RE_PARENTESIS.sub("", buffer)
            oracion = _RE_ESPACIOS.sub(" ", oracion).strip()
            if oracion:
                yield oracion

        texto_completo = _RE_PARENTESIS.sub("", texto_completo)
        texto_completo = _RE_ESPACIOS.sub(" ", texto_completo).strip()
        _historial.append({"role": "assistant", "content": texto_completo})

    except Exception as e:
        _historial.pop()
        print(f"[IA] Error: {e}")
        yield _MENSAJES_ERROR[_idioma][1]


def warmup_llm() -> None:
    """Carga el modelo en RAM al arrancar para que la primera respuesta no tarde más."""
    print("[IA] Calentando modelo LLM...")
    try:
        ollama.generate(model="llama3.2:1b", prompt="", keep_alive=-1)
        print("[IA] Modelo LLM listo.")
    except Exception as e:
        print(f"[IA] Warmup fallido: {e}")

def limpiar_historial():
    """Limpia el historial y el tema entre visitantes.

    El tema se borra ACÁ Y NO en otro lado por el mismo motivo que el
    historial: si sobrevive al cambio de visitante, el próximo hereda la
    civilización del anterior y su primera pregunta suelta se contesta con
    hechos que él nunca pidió.
    """
    global _tema_actual
    _historial.clear()
    _tema_actual = None
