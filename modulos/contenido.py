# ============================================================
#  MEXA — Contenido e internacionalización
#
#  DATOS, no lógica: el catálogo de civilizaciones (palabra clave
#  -> video por idioma), los nombres para hablar y las frases
#  fijas en español/inglés. Vive separado del flujo para que
#  `main.py` orqueste y este módulo solo describa QUÉ dice MEXA.
# ============================================================

from .modulo_proyector import CARPETA_VIDEOS
import os

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
}

NOMBRES_DISPONIBLES = ["los Mayas", "los Aztecas", "Teotihuacán", "los Olmecas", "los Toltecas", "los Zapotecas", "los Mixtecas"]

NOMBRES_EN = {
    "los Mayas":      "the Mayas",
    "los Aztecas":    "the Aztecs",
    "Teotihuacán":    "Teotihuacán",
    "los Olmecas":    "the Olmecs",
    "los Toltecas":   "the Toltecs",
    "los Zapotecas":  "the Zapotecs",
    "los Mixtecas":   "the Mixtecs",
}

FRASES = {
    "es": {
        "saludo_civ":   "¡Hola! Soy MEXA, tu guía de la historia y cultura de México. ¿Sobre cuál civilización quieres aprender hoy?",
        "no_reconocio": "No reconocí esa civilización. Tenemos: {oferta}. ¿Cuál te gustaría?",
        "no_entendio":  "No escuché bien. ¿Puedes repetir, por favor?",
        "intro_video":  "Perfecto, te voy a mostrar un video sobre {nombre}.",
        "post_video":   "Espero que hayas disfrutado el video sobre {nombre}. ¿Tienes alguna pregunta?",
        "despedida":    "Fue un placer compartir cultura contigo. ¡Hasta pronto!",
    },
    "en": {
        "saludo_civ":   "Hello! I am MEXA, your guide to the history and culture of Mexico. Which civilization would you like to learn about today?",
        "no_reconocio": "I didn't recognize that civilization. We have: {oferta}. Which one would you like?",
        "no_entendio":  "I didn't catch that. Could you repeat, please?",
        "intro_video":  "Perfect, I will show you a video about {nombre}.",
        "post_video":   "I hope you enjoyed the video about {nombre}. Do you have any questions?",
        "despedida":    "It was a pleasure sharing culture with you. See you soon!",
    },
}


def detectar_civilizacion(texto: str, idioma: str) -> tuple[str, str] | None:
    """Retorna (ruta_video, nombre) según el idioma si el texto menciona una civilización."""
    texto_lower = texto.lower()
    for clave, datos in CIVILIZACIONES.items():
        if clave in texto_lower:
            ruta_es, ruta_en, nombre = datos
            return (ruta_en if idioma == "en" else ruta_es, nombre)
    return None
