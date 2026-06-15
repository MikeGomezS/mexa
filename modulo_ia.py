# ============================================================
#  MEXA — Módulo 02: Motor de IA (Generación de respuestas)
#  Librería: ollama (modelo local en Raspberry Pi)
#  Instalar: curl -fsSL https://ollama.com/install.sh | sh
#            ollama pull llama3.2:1b
# ============================================================

import re
import ollama
from conocimiento import buscar_contexto

_SISTEMA_BASE = """Eres MEXA, un robot educativo experto en historia
y cultura de México. Responde de forma clara, amable y en
máximo 2 oraciones. Hablas a personas de todas las edades.
Si te preguntan algo que no es sobre México o cultura,
responde amablemente que solo puedes hablar de esos temas.
NO uses paréntesis, aclaraciones ni autocorrecciones en medio del texto.
Escribe oraciones limpias y directas, como si hablaras en voz alta."""

_idioma: str = "es"  # "es" o "en"

_INSTRUCCION_IDIOMA = {
    "es": "IMPORTANTE: responde SIEMPRE en español, sin importar el idioma en que se haga la pregunta. Aunque el usuario pregunte en inglés u otro idioma, tu respuesta DEBE ser en español.",
    "en": "IMPORTANT: ALWAYS respond in English, no matter what language the user asks in. Even if the question is in Spanish or another language, your response MUST be in English.",
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

def _sistema() -> str:
    return _SISTEMA_BASE + "\n" + _INSTRUCCION_IDIOMA[_idioma]

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

def generar_respuesta(pregunta: str) -> str:
    """
    Recibe una pregunta de texto y regresa la respuesta de la IA.
    Mantiene el historial de la conversación para preguntas de seguimiento.
    El modelo corre localmente en la Raspberry Pi — no necesita internet.
    """
    if not pregunta:
        return _MENSAJES_ERROR[_idioma][0]

    contexto = buscar_contexto(pregunta)
    contenido = f"{contexto}\n\nPregunta: {pregunta}" if contexto else pregunta
    _historial.append({"role": "user", "content": contenido})
    print(f"[IA] Procesando: {pregunta}")
    if contexto:
        print("[IA] Contexto verificado inyectado.")
    try:
        respuesta = ollama.chat(
            model="llama3.2:1b",  # modelo liviano para Raspberry Pi 5
            messages=[{"role": "system", "content": _sistema()}] + _historial[-6:],
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

    contexto = buscar_contexto(pregunta)
    contenido = f"{contexto}\n\nPregunta: {pregunta}" if contexto else pregunta
    _historial.append({"role": "user", "content": contenido})
    print(f"[IA] Procesando (stream): {pregunta}")

    try:
        stream = ollama.chat(
            model="llama3.2:1b",
            messages=[{"role": "system", "content": _sistema()}] + _historial[-6:],
            options=_OPCIONES_OLLAMA,
            keep_alive=-1,
            stream=True,
        )

        buffer = ""
        texto_completo = ""

        for chunk in stream:
            token = chunk["message"]["content"]
            buffer += token
            texto_completo += token

            # Yield cada oración completa en cuanto llega
            while True:
                match = re.search(r'[.!?]+\s', buffer)
                if not match:
                    break
                oracion = buffer[:match.end()].strip()
                oracion = _RE_PARENTESIS.sub("", oracion)
                oracion = _RE_ESPACIOS.sub(" ", oracion).strip()
                if oracion:
                    print(f"[IA] Oración lista: {oracion[:60]}...")
                    yield oracion
                buffer = buffer[match.end():]

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
    """Limpia el historial entre visitantes para no mezclar conversaciones."""
    _historial.clear()
