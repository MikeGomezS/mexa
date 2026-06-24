# ============================================================
#  MEXA — Programa Principal (main.py)
#  WRO Future Innovators 2026
#  Equipo: Bruno, Emilia y Majo
#
#  Este archivo une todos los módulos y corre el ciclo principal.
#  Para ejecutar: python3 main.py
#
#  ANTES DE CORRER:
#  1. Instalar dependencias:
#     pip install speechrecognition pyaudio pyttsx3 ollama picamera2 opencv-python pygame
#     sudo apt install python3-rpi.gpio espeak vlc -y
#
#  2. Descargar el modelo de IA:
#     curl -fsSL https://ollama.com/install.sh | sh
#     ollama pull llama3.2:3b
#
#  3. Crear carpeta de imágenes:
#     mkdir -p media/imagenes
#     (Agregar imágenes JPG de sitios culturales mexicanos)
#
#  4. Conectar todos los componentes según los pines indicados
#     en cada módulo.
# ============================================================

import os
import time
import RPi.GPIO as GPIO

from modulos.modulo_audio       import escuchar_pregunta
from modulos.modulo_ia          import (generar_respuesta_stream,
                                        limpiar_historial, establecer_idioma,
                                        warmup_llm)
from modulos.modulo_tts         import hablar, hablar_stream, presintetizar
from modulos.modulo_sensores    import iniciar_sensores, detectar_persona
from modulos.modulo_motores     import (iniciar_motores, detener, orientarse_a_usuario,
                                        mover_por_tiempo, mover_adelante)
from modulos.modulo_camara      import iniciar_camara, posicion_cara, localizar_cara, apagar_camara
from modulos.modulo_proyector   import (iniciar_proyector, mostrar_segun_tema,
                                        pantalla_bienvenida, cambiar_expresion,
                                        apagar_proyector, reproducir_video, CARPETA_VIDEOS)
from modulos.modulo_brazos      import iniciar_brazos, cerrar_brazos
from modulos.conexion_arduino   import cerrar_conexion
from modulos.registro_camino    import RegistroCamino, retroceder

# ── Configuración ────────────────────────────────────────────
TIEMPO_ESPERA_USUARIO = 30   # segundos antes de despedirse si no habla
INTENTOS_MAX          = 3    # intentos de escuchar antes de despedirse

# ── Acercamiento con cámara (drive-and-sense en dos fases) ────
# MEXA centra al visitante Y se le acerca usando el TAMAÑO de la cara como proxy
# de distancia (cara grande = cerca). El avance es CONTINUO: los motores NO se
# detienen entre lecturas; MEXA sensa EN MOVIMIENTO y sólo frena para corregir
# rumbo (giro) o al terminar. Esto da una caminata fluida, no entrecortada.
#
# HALLAZGO DE HARDWARE (validado en tests/calibrar_acercamiento.py): MEXA es BAJO
# y la cámara va inclinada, así que al acercarse (~1m) la cara del visitante se
# RECORTA por arriba del cuadro y YuNet deja de verla. Por eso la cara casi nunca
# crece hasta un objetivo grande: se PIERDE antes. Esa pérdida estando CERCA y
# CENTRADO ES la señal de "ya casi llego" y dispara el EMPUJE CIEGO final, que
# cierra el último tramo. Si la cara se pierde LEJOS o descentrada, la persona se
# fue: MEXA no empuja y aborta.
#
# Calibrado en hardware (ruedas chicas): MEXA avanza ~2.5 cm/s (motores a full,
# sin PWM). Estos valores son punto de partida; HAY QUE CALIBRARLOS en el robot
# real (dependen de la lente, la altura de la cámara y la velocidad de los motores).
ACERCAMIENTO_TIMEOUT_S  = 30.0  # tope duro de seguridad para TODA la maniobra
TAMANO_CARA_OBJETIVO    = 0.40  # techo de seguridad: si la cara llegara a verse así
                                # de grande, frena. Casi nunca se alcanza (la cara se
                                # recorta antes ~25%); el freno real es la pérdida por
                                # recorte + el empuje ciego de la fase 2.
PULSO_GIRO_S            = 0.80  # barrido por paso: más alto = gira menos entrecortado, pero
                                # si se pasa del centro oscila (zona 40/60% lo auto-corrige).
                                # Subido 0.25->0.80 para que el giro se sienta más fluido.
MAX_MISSES_ACERCAMIENTO = 6     # frames sin cara seguidos -> fin de la fase visual
SETTLE_ACERCAMIENTO_S   = 0.35  # respiro anti-blur SÓLO tras un giro: deja asentar
                                # robot+cámara antes de re-sensar. SIN esto, el frame
                                # post-giro sale borroso, YuNet cae bajo _SCORE_MIN y
                                # MEXA pierde la cara (validado en hardware 2026-06-23).
# Empuje ciego final (fase 2): tras perder la cara por cercanía, avanza a ciegas
# para cerrar el último tramo hasta el visitante.
UMBRAL_CARA_CERCA       = 0.20  # último tamaño mínimo para confiar en que el recorte
                                # es por cercanía (no porque la persona se fue)
AVANCE_CIEGO_FINAL_S    = 4.0   # segundos de empuje ciego. CALIBRAR: parate frente a
                                # MEXA y SUBÍ este valor hasta que frene a la distancia
                                # que quieras (~2.5 cm/s -> 4s ≈ 10cm). SEGURIDAD: no lo
                                # subas tanto que MEXA choque con el visitante.

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

_NOMBRES_EN = {
    "los Mayas":      "the Mayas",
    "los Aztecas":    "the Aztecs",
    "Teotihuacán":    "Teotihuacán",
    "los Olmecas":    "the Olmecs",
    "los Toltecas":   "the Toltecs",
    "los Zapotecas":  "the Zapotecs",
    "los Mixtecas":   "the Mixtecs",
}

_FRASES = {
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

def _presintetizar_todo() -> None:
    """Pre-sintetiza con Piper todas las frases fijas al arrancar para
    reproducción instantánea durante la interacción (sin latencia de síntesis)."""
    print("[MAIN] Pre-sintetizando frases fijas...")

    # Prompt de idioma (siempre en inglés, antes de saber la preferencia).
    frases = [
        "Hi, I am MEXA. Would you prefer Spanish or English?",  # _seleccionar_idioma
        "Please say 'español' or 'English'.",                   # _seleccionar_idioma
    ]

    # Frases dependientes del idioma y de cada civilización.
    for idioma in ("es", "en"):
        f = _FRASES[idioma]
        nombres_civ = (
            _NOMBRES_DISPONIBLES if idioma == "es"
            else [_NOMBRES_EN[n] for n in _NOMBRES_DISPONIBLES]
        )
        oferta = ", ".join(nombres_civ)
        frases.append(f["saludo_civ"].format(oferta=oferta))
        frases.append(f["no_reconocio"].format(oferta=oferta))
        frases.append(f["no_entendio"])
        frases.append(f["despedida"])
        for nombre in nombres_civ:
            frases.append(f["intro_video"].format(nombre=nombre))
            frases.append(f["post_video"].format(nombre=nombre))

    for texto in frases:
        presintetizar(texto)

    print(f"[MAIN] {len(frases)} frases listas.")


def iniciar_todo():
    """Inicializa todos los módulos del robot."""
    print("=" * 50)
    print("  MEXA — Iniciando sistema...")
    print("=" * 50)
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    iniciar_sensores()
    iniciar_motores()
    iniciar_camara()
    iniciar_proyector()
    iniciar_brazos()

    pantalla_bienvenida()

    # Optimizaciones de latencia (validadas en tests/test_flujo.py):
    # pre-sintetizar frases fijas y precalentar el LLM para que la primera
    # respuesta de IA no pague el costo de carga del modelo.
    _presintetizar_todo()
    warmup_llm()

    print("[MAIN] Todos los módulos iniciados. MEXA listo.")

def apagar_todo():
    """Limpia los GPIO y apaga los módulos al salir."""
    print("[MAIN] Apagando MEXA...")
    detener()
    cerrar_brazos()
    cerrar_conexion()   # cierra el puerto serial compartido (un solo Arduino)
    apagar_camara()
    apagar_proyector()
    GPIO.cleanup()
    print("[MAIN] MEXA apagado correctamente.")

_PALABRAS_ADIOS   = {"adios", "adiós"}
_PALABRAS_SALIDA  = {"bye", "hasta luego", "no", "no gracias", "nada", "ninguna"}
_PALABRAS_REINICIO = {"mexa", "mesa"}  # "mesa" es como Vosk suele transcribir "mexa"


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


def _detectar_civilizacion(texto: str, idioma: str) -> tuple[str, str] | None:
    """Retorna (ruta_video, nombre) según el idioma si el texto menciona una civilización."""
    texto_lower = texto.lower()
    for clave, datos in _CIVILIZACIONES.items():
        if clave in texto_lower:
            ruta_es, ruta_en, nombre = datos
            return (ruta_en if idioma == "en" else ruta_es, nombre)
    return None


def _ciclo_preguntas(f: dict) -> bool | None:
    """
    Escucha y responde preguntas, usando las frases del idioma elegido (f).
    Retorna True  → terminar programa (adiós)
            False → volver a esperar PIR
            None  → reiniciar ciclo_interaccion inmediatamente (se dijo "mexa")
    """
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

        if any(k in p for k in _PALABRAS_REINICIO):
            return None

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


def ciclo_interaccion() -> bool | None:
    """
    Flujo completo con un visitante.
    Retorna True  → terminar el programa (se dijo adiós)
            False → volver a esperar a un visitante (PIR)
            None  → reiniciar la interacción de inmediato (se dijo "mexa")
    """
    limpiar_historial()
    orientarse_a_usuario(posicion_cara())

    # 0. Selección de idioma
    idioma = _seleccionar_idioma()
    establecer_idioma(idioma)
    f = _FRASES[idioma]

    nombres_disp = (
        _NOMBRES_DISPONIBLES if idioma == "es"
        else [_NOMBRES_EN[n] for n in _NOMBRES_DISPONIBLES]
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
        return False

    ruta_video, nombre_civ_es = video_info
    nombre_civ = _NOMBRES_EN[nombre_civ_es] if idioma == "en" else nombre_civ_es

    # 3. Reproducir el video en el idioma seleccionado
    cambiar_expresion("hablando")
    hablar(f["intro_video"].format(nombre=nombre_civ))
    reproducir_video(ruta_video)

    # 5. Preguntar si tienen dudas
    time.sleep(3)
    cambiar_expresion("hablando")
    hablar(f["post_video"].format(nombre=nombre_civ))

    # 6 y 7. Ciclo de preguntas con IA + despedida.
    # Propaga el resultado: True=adiós (apagar), False=esperar persona,
    # None=reiniciar la interacción de inmediato (alguien dijo "mexa").
    return _ciclo_preguntas(f)

def acercarse_a_usuario():
    """Drive-and-sense en dos fases: MEXA centra al visitante y se le acerca.

    FASE 1 (visual, avance CONTINUO). Usa el tamaño de la cara como proxy de
    distancia. En cada lectura:
      - centrado    -> avanza CONTINUO (no frena entre lecturas: sensa en marcha).
      - descentrado -> frena, da un giro corto hacia ese lado, asienta (anti-blur)
                       y re-sensa. Centrar tiene prioridad sobre avanzar.
      - sin cara    -> sigue su marcha; si la pierde MAX_MISSES seguidas, cierra
                       la fase visual y evalúa la fase 2.
      - cara enorme -> (tamano >= TAMANO_CARA_OBJETIVO) techo de seguridad: frena.

    FASE 2 (empuje ciego final). Al cerrar la fase visual por pérdida de cara:
      - si la perdió CERCA (último tamaño >= UMBRAL_CARA_CERCA) y CENTRADA, asume
        que fue por RECORTE (MEXA es bajo, la cara se sale por arriba) y empuja a
        ciegas AVANCE_CIEGO_FINAL_S para cerrar el último tramo.
      - si la perdió LEJOS o descentrada, la persona se fue: no empuja, aborta.

    Cortes de seguridad: ACERCAMIENTO_TIMEOUT_S acota TODA la maniobra. El avance
    continuo deja los motores en marcha; sólo se frena para girar, al alcanzar el
    techo de tamaño, o al terminar.

    REGISTRA el recorrido: cada comando de motor queda anotado con su
    timestamp y se devuelve como lista de (comando, timestamp), para que
    MEXA pueda RETROCEDER al punto de partida tras atender al visitante."""
    registro = RegistroCamino()
    registro.iniciar()  # engancha la capa serial: anota cada F/B/R/L/S
    fin = time.time() + ACERCAMIENTO_TIMEOUT_S
    misses = 0
    primera_cara = True
    ult_tamano = 0.0
    ult_posicion = "centro"
    avanzando = False  # ¿los motores están en marcha continua hacia adelante?

    def asegurar_avance():
        nonlocal avanzando
        if not avanzando:
            mover_adelante()
            avanzando = True

    def frenar():
        nonlocal avanzando
        if avanzando:
            detener()
            avanzando = False

    while time.time() < fin:
        lectura = localizar_cara()  # se sensa EN MOVIMIENTO durante el avance
        if lectura is None:
            misses += 1
            if misses >= MAX_MISSES_ACERCAMIENTO:
                frenar()
                cerca = ult_tamano >= UMBRAL_CARA_CERCA
                centrada = ult_posicion == "centro"
                if cerca and centrada:
                    print(f"[MAIN] Acercamiento: cara perdida CERCA "
                          f"(últ={ult_tamano:.0%}, centro) -> recorte. "
                          f"Empuje ciego {AVANCE_CIEGO_FINAL_S}s.")
                    mover_por_tiempo("adelante", AVANCE_CIEGO_FINAL_S)
                else:
                    print(f"[MAIN] Acercamiento: cara perdida LEJOS/descentrada "
                          f"(últ={ult_tamano:.0%}, {ult_posicion}) -> no empujo.")
                break
            continue
        misses = 0
        posicion, tamano = lectura
        ult_tamano, ult_posicion = tamano, posicion
        # Tamaño al que MEXA ENGANCHA por primera vez al visitante: dato clave de
        # calibración (¿a qué distancia detecta cuando dispara el PIR?).
        if primera_cara:
            print(f"[MAIN] Acercamiento: primera cara en pos={posicion}, "
                  f"tamaño={tamano:.0%}.")
            primera_cara = False
        if tamano >= TAMANO_CARA_OBJETIVO:
            frenar()
            print(f"[MAIN] Acercamiento: techo de seguridad (cara={tamano:.0%}), freno.")
            break
        if posicion == "centro":
            asegurar_avance()  # avance CONTINUO: no se frena entre lecturas
        else:
            # Corrección de rumbo: frenar, girar un pulso y asentar (anti-blur)
            # antes de re-sensar, que un frame post-giro sale borroso.
            frenar()
            mover_por_tiempo(posicion, PULSO_GIRO_S)
            time.sleep(SETTLE_ACERCAMIENTO_S)
    else:
        frenar()
        print("[MAIN] Acercamiento: TIMEOUT, freno.")
    detener()
    registro.finalizar()  # deja de escuchar y cierra el último tramo
    return registro.eventos


def ciclo_principal():
    """
    Flujo continuo de exhibición: espera a un visitante (PIR), lo atiende y,
    al terminar, vuelve a esperar al siguiente. Según lo que retorne
    ciclo_interaccion(): True=apagar MEXA, False=esperar al siguiente,
    None=reiniciar la interacción de inmediato (alguien dijo "mexa").
    """
    print("[MAIN] MEXA en espera de visitantes...")

    try:
        while True:
            # Esperar a un visitante.
            while not detectar_persona():
                time.sleep(0.5)

            print("[MAIN] ¡Persona detectada! Iniciando interacción.")

            # Centrar y acercarse al visitante con la cámara (lazo cerrado).
            # Guarda el recorrido para poder volver al punto de partida.
            camino = acercarse_a_usuario()

            # Atender al visitante. None = reiniciar de inmediato (dijo "mexa").
            terminar = ciclo_interaccion()
            while terminar is None:
                terminar = ciclo_interaccion()

            # Deshacer el acercamiento: MEXA retrocede a donde empezó.
            retroceder(camino)

            if terminar:                # True → adiós: apagar MEXA
                break

            # False → volver a esperar al siguiente visitante.
            pantalla_bienvenida()
            print("[MAIN] Interacción completada. Esperando al siguiente visitante...")

    except KeyboardInterrupt:
        print("\n[MAIN] Interrupción detectada (Ctrl+C).")
    finally:
        apagar_todo()

# ── Punto de entrada ────────────────────────────────────────
if __name__ == "__main__":
    iniciar_todo()
    ciclo_principal()
