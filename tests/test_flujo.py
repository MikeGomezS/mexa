"""
Prueba del flujo completo de MEXA usando solo:
  - Micrófono (Vosk STT)
  - Bocina (piper-tts + pw-play)
  - Proyector (pygame + VLC via HDMI)
  - Brazos (Arduino via USB Serial — opcional, se omite si no está conectado)

Sin GPIO, sin motores, sin cámara, sin sensores.
Ejecutar desde la raíz del proyecto: python3 tests/test_flujo.py
"""

import os
import sys
import time

# Permite importar el paquete `modulos` al correr este test desde tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_proyector import (
    iniciar_proyector, pantalla_bienvenida, cambiar_expresion,
    mostrar_segun_tema, reproducir_video, apagar_proyector, CARPETA_VIDEOS,
)
from modulos.modulo_audio  import escuchar_pregunta
from modulos.modulo_tts    import hablar, hablar_stream, presintetizar
from modulos.modulo_ia     import generar_respuesta_stream, limpiar_historial, establecer_idioma, warmup_llm
from modulos.modulo_brazos import iniciar_brazos, cerrar_brazos

# ── Configuración ────────────────────────────────────────────
INTENTOS_MAX         = 3
TIEMPO_ESPERA_USUARIO = 30

# ── Civilizaciones disponibles ───────────────────────────────
# Cada entrada: palabra_clave → (ruta_video_es, ruta_video_en, nombre_para_hablar)
_ESP = os.path.join(CARPETA_VIDEOS, "español")
_ENG = os.path.join(CARPETA_VIDEOS, "ingles")

_CIVILIZACIONES: dict[str, tuple[str, str, str]] = {
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
}

_NOMBRES_DISPONIBLES = ["los Mayas", "los Aztecas", "Teotihuacán", "los Olmecas", "los Toltecas", "los Zapotecas", "los Mixtecas"]

_PALABRAS_ADIOS  = {"adios", "adiós"}
_PALABRAS_SALIDA = {"bye", "hasta luego", "no", "no gracias", "nada", "ninguna"}

# ── Frases por idioma ─────────────────────────────────────────
_FRASES = {
    "es": {
        "saludo_idioma":  "Hola, soy MEXA. ¿Prefieres hablar en español o en inglés?",
        "no_entendio":    "No escuché bien. ¿Puedes repetir, por favor?",
        "saludo_civ":     "¡Hola! Soy MEXA, tu guía de la historia y cultura de México. ¿Sobre cuál civilización quieres aprender hoy?",
        "no_reconocio":   "No reconocí esa civilización. Tenemos: {oferta}. ¿Cuál te gustaría?",
        "intro_video":    "Perfecto, te voy a mostrar un video sobre {nombre}.",
        "post_video":     "Espero que hayas disfrutado el video sobre {nombre}. ¿Tienes alguna pregunta?",
        "despedida":      "Fue un placer compartir cultura contigo. ¡Hasta pronto!",
    },
    "en": {
        "saludo_idioma":  "Hi, I am MEXA. Would you prefer to speak in Spanish or English?",
        "no_entendio":    "I didn't catch that. Could you repeat, please?",
        "saludo_civ":     "Hello! I am MEXA, your guide to the history and culture of Mexico. Which civilization would you like to learn about today?",
        "no_reconocio":   "I didn't recognize that civilization. We have: {oferta}. Which one would you like?",
        "intro_video":    "Perfect, I will show you a video about {nombre}.",
        "post_video":     "I hope you enjoyed the video about {nombre}. Do you have any questions?",
        "despedida":      "It was a pleasure sharing culture with you. See you soon!",
    },
}

_NOMBRES_EN = {
    "los Mayas":      "the Mayas",
    "los Aztecas":    "the Aztecs",
    "Teotihuacán":    "Teotihuacán",
    "los Olmecas":    "the Olmecs",
    "los Toltecas":   "the Toltecs",
    "los Zapotecas":  "the Zapotecs",
    "los Mixtecas":   "the Mixtecs",
}


def _presintetizar_todo() -> None:
    """Pre-sintetiza todas las frases fijas al arrancar para reproducción instantánea."""
    print("[MEXA] Pre-sintetizando frases fijas...")

    nombres_es = _NOMBRES_DISPONIBLES
    nombres_en = [_NOMBRES_EN[n] for n in _NOMBRES_DISPONIBLES]
    oferta_es  = ", ".join(nombres_es)
    oferta_en  = ", ".join(nombres_en)

    frases = [
        "Hi, I am MEXA. Would you prefer Spanish or English?",
        "Please say 'español' or 'English'.",
    ]

    for idioma, f, oferta, nombres_civ in [
        ("es", _FRASES["es"], oferta_es, nombres_es),
        ("en", _FRASES["en"], oferta_en, nombres_en),
    ]:
        frases.append(f["saludo_civ"])
        frases.append(f["no_reconocio"].format(oferta=oferta))
        frases.append(f["no_entendio"])
        frases.append(f["despedida"])
        for nombre in nombres_civ:
            frases.append(f["intro_video"].format(nombre=nombre))
            frases.append(f["post_video"].format(nombre=nombre))

    for texto in frases:
        presintetizar(texto)

    print(f"[MEXA] {len(frases)} frases listas.")


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
    return "es"  # fallback


def _detectar_civilizacion(texto: str, idioma: str) -> tuple[str, str] | None:
    texto_lower = texto.lower()
    for clave, datos in _CIVILIZACIONES.items():
        if clave in texto_lower:
            ruta_es, ruta_en, nombre = datos
            return (ruta_en if idioma == "en" else ruta_es, nombre)
    return None


def _ciclo_preguntas(f: dict) -> bool:
    """Retorna True si el programa debe terminar (se dijo adiós)."""
    tiempo_ultimo = time.time()
    intentos_sin_respuesta = 0

    while True:
        if time.time() - tiempo_ultimo > TIEMPO_ESPERA_USUARIO:
            cambiar_expresion("hablando")
            time.sleep(3)
            hablar(f["despedida"])
            return False

        cambiar_expresion("escuchando")
        pregunta = escuchar_pregunta(timeout=8)

        if not pregunta:
            intentos_sin_respuesta += 1
            if intentos_sin_respuesta >= INTENTOS_MAX:
                cambiar_expresion("hablando")
                time.sleep(3)
                hablar(f["despedida"])
                return False
            cambiar_expresion("hablando")
            hablar(f["no_entendio"])
            continue

        intentos_sin_respuesta = 0
        tiempo_ultimo = time.time()
        p = pregunta.lower()

        if any(k in p for k in _PALABRAS_ADIOS):
            cambiar_expresion("hablando")
            time.sleep(3)
            hablar(f["despedida"])
            return True

        if any(k in p for k in _PALABRAS_SALIDA):
            cambiar_expresion("hablando")
            time.sleep(3)
            hablar(f["despedida"])
            return False

        cambiar_expresion("pensando")
        mostrar_segun_tema(pregunta)
        cambiar_expresion("hablando")
        hablar_stream(generar_respuesta_stream(pregunta))


def _esperar_wakeword() -> bool:
    """Espera a escuchar 'MEXA'. Retorna True para iniciar, False para terminar."""
    print("[MEXA] Suspendido. Di 'MEXA' para iniciar o 'adiós' para terminar.")
    cambiar_expresion("idle")
    while True:
        resp = escuchar_pregunta(timeout=10)
        if not resp:
            continue
        r = resp.lower()
        if "mexa" in r or "mesa" in r:
            return True
        if any(k in r for k in _PALABRAS_ADIOS):
            return False


def _run_interaccion() -> bool:
    """Corre una interacción completa. Retorna True si el programa debe terminar."""
    limpiar_historial()

    idioma = _seleccionar_idioma()
    establecer_idioma(idioma)
    f = _FRASES[idioma]

    nombres_disp = (
        _NOMBRES_DISPONIBLES if idioma == "es"
        else [_NOMBRES_EN[n] for n in _NOMBRES_DISPONIBLES]
    )
    oferta = ", ".join(nombres_disp)

    cambiar_expresion("hablando")
    hablar(f["saludo_civ"].format(oferta=oferta))

    video_info = None
    intentos = 0
    while video_info is None and intentos < INTENTOS_MAX:
        cambiar_expresion("escuchando")
        eleccion = escuchar_pregunta(timeout=10)
        if eleccion:
            video_info = _detectar_civilizacion(eleccion, idioma)
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
        return True

    ruta_video, nombre_civ_es = video_info
    nombre_civ = _NOMBRES_EN[nombre_civ_es] if idioma == "en" else nombre_civ_es

    cambiar_expresion("hablando")
    hablar(f["intro_video"].format(nombre=nombre_civ))
    reproducir_video(ruta_video)
    time.sleep(3)

    cambiar_expresion("hablando")
    hablar(f["post_video"].format(nombre=nombre_civ))
    return _ciclo_preguntas(f)


def main():
    print("=" * 50)
    print("  MEXA — Prueba de flujo completo")
    print("=" * 50)

    iniciar_proyector()
    pantalla_bienvenida()
    iniciar_brazos()
    _presintetizar_todo()
    warmup_llm()

    try:
        while True:
            terminar = _run_interaccion()
            if terminar:
                break
            if not _esperar_wakeword():
                break
    finally:
        cerrar_brazos()
        apagar_proyector()

    print("[MEXA] Prueba finalizada.")


if __name__ == "__main__":
    main()
