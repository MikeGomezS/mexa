# ============================================================
#  MEXA — Programa Principal (main.py)
#  WRO Future Innovators 2026
#  Equipo: Bruno, Emilia y Majo
#
#  Orquestador: une los módulos y corre el ciclo de exhibición.
#  El QUÉ dice MEXA vive en modulos/contenido.py, el CÓMO se
#  acerca en modulos/navegacion.py y la conversación en
#  modulos/dialogo.py. Acá sólo se inicia, se coordina y se apaga.
#
#  Para ejecutar: python3 main.py
#
#  ANTES DE CORRER:
#  1. Instalar dependencias:
#     pip install speechrecognition pyaudio pyttsx3 ollama picamera2 opencv-python pygame
#     sudo apt install espeak vlc -y
#
#  2. Descargar el modelo de IA:
#     curl -fsSL https://ollama.com/install.sh | sh
#     ollama pull llama3.2:3b
#
#  3. Conectar todos los componentes (motores/PIR/brazos van por el
#     Arduino vía USB serial; la cámara al puerto CSI).
# ============================================================

import time

from modulos.modulo_ia          import warmup_llm
from modulos.modulo_tts         import presintetizar
from modulos.modulo_sensores    import iniciar_sensores, detectar_persona
from modulos.modulo_motores     import iniciar_motores, detener
from modulos.modulo_camara      import iniciar_camara, apagar_camara
from modulos.modulo_proyector   import (iniciar_proyector, pantalla_bienvenida,
                                        apagar_proyector)
from modulos.modulo_brazos      import iniciar_brazos, cerrar_brazos
from modulos.conexion_arduino   import cerrar_conexion
from modulos.navegacion         import acercarse_a_usuario, retroceder
from modulos.dialogo            import ciclo_interaccion, Resultado
from modulos                    import contenido


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
        f = contenido.FRASES[idioma]
        nombres_civ = (
            contenido.NOMBRES_DISPONIBLES if idioma == "es"
            else [contenido.NOMBRES_EN[n] for n in contenido.NOMBRES_DISPONIBLES]
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

    iniciar_sensores()
    iniciar_motores()
    iniciar_camara()
    iniciar_proyector()
    iniciar_brazos()

    pantalla_bienvenida()

    # Optimizaciones de latencia: pre-sintetizar frases fijas y precalentar el
    # LLM para que la primera respuesta de IA no pague el costo de carga del modelo.
    _presintetizar_todo()
    warmup_llm()

    print("[MAIN] Todos los módulos iniciados. MEXA listo.")


def apagar_todo():
    """Apaga los módulos al salir (los GPIO viven en el Arduino, no en la Pi)."""
    print("[MAIN] Apagando MEXA...")
    detener()
    cerrar_brazos()
    cerrar_conexion()   # cierra el puerto serial compartido (un solo Arduino)
    apagar_camara()
    apagar_proyector()
    print("[MAIN] MEXA apagado correctamente.")


def ciclo_principal():
    """
    Flujo continuo de exhibición: espera a un visitante (PIR), lo atiende y,
    al terminar, vuelve a esperar al siguiente. Según el Resultado de
    ciclo_interaccion(): APAGAR=apagar MEXA, ESPERAR=esperar al siguiente,
    REINICIAR=reiniciar la interacción de inmediato (dijo "empecemos de nuevo").
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

            # Atender al visitante. REINICIAR = volver a empezar en el lugar.
            resultado = ciclo_interaccion()
            while resultado is Resultado.REINICIAR:
                resultado = ciclo_interaccion()

            # Deshacer el acercamiento: MEXA retrocede a donde empezó.
            retroceder(camino)

            if resultado is Resultado.APAGAR:
                break

            # ESPERAR → volver a esperar al siguiente visitante.
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
