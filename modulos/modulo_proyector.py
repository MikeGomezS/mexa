# ============================================================
#  MEXA — Módulo 07: Control del Proyector (Pantalla HDMI)
#  Hardware: KACOTA HY300 Pro conectado por Micro-HDMI
#  Librerías: pygame, subprocess, vlc
#  Instalar: pip install pygame
#            sudo apt install vlc -y
#
#  CONEXIÓN:
#    Cable Micro-HDMI → HDMI (incluido en el kit RasTech)
#    Conectar al puerto Micro-HDMI 1 de la Raspberry Pi 5
#    El proyector se enciende aparte con su propio adaptador.
#
#  ESTRUCTURA DE CARPETAS NECESARIA:
#    mexa/
#    └── media/
#        └── videos/
#            ├── español/   ({Nombre}_esp.mp4)
#            └── ingles/    ({Nombre}_eng.mp4)
#
#  MEXA NO USA IMÁGENES FIJAS. Este encabezado siguió pidiendo una
#  carpeta media/imagenes/ con ocho .jpg después de que el commit
#  a8ec7fb borrara la maquinaria que las mostraba (la cara animada
#  las tapaba a los 0.7s): el archivo que dejó de usarlas fue el
#  mismo que las siguió exigiendo.
# ============================================================

import cv2
import os
import select
import subprocess
import sys
import time

import pygame

CARPETA_VIDEOS   = os.path.join(os.path.dirname(__file__), "..", "media", "videos")

pantalla = None

_PROYECTOR_W = 1920
_PROYECTOR_H = 1080

_PROYECTOR_X = 0      # mismo monitor (HDMI-A-2, posición 0,0); ya no se usa segundo display
_PROYECTOR_Y = 0

_CARA_SCRIPT = os.path.join(os.path.dirname(__file__), "_cara_animada.py")

# Subproceso que corre la animación de bienvenida
_cara_proc: subprocess.Popen | None = None


# Cuánto se espera a que la cara avise que ya pintó, antes de rendirse.
_ESPERA_CARA_S = 4.0


def iniciar_proyector():
    """Abre la ventana del proceso principal sobre el proyector.

    Va en FULLSCREEN, no sólo NOFRAME: el panel del escritorio (wf-panel-pi
    bajo labwc) es una capa por encima de las ventanas normales y quedaba
    dibujado sobre la imagen. Medido: fullscreen lo tapa, sin borde no.
    """
    global pantalla
    if pantalla is not None:
        return
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
    # Posicionar la ventana en las coordenadas exactas del proyector en el
    # escritorio virtual. SDL_VIDEO_FULLSCREEN_DISPLAY no funciona con SDL2/X11;
    # SDL_VIDEO_WINDOW_POS sí lo hace de forma confiable.
    os.environ["SDL_VIDEO_WINDOW_POS"] = f"{_PROYECTOR_X},{_PROYECTOR_Y}"
    pygame.init()
    pantalla = pygame.display.set_mode((_PROYECTOR_W, _PROYECTOR_H),
                                       pygame.NOFRAME | pygame.FULLSCREEN)
    pantalla.fill((0, 0, 0))
    pygame.display.flip()
    print("[PROYECTOR] Iniciado en el monitor principal (posición 0,0).")


def _cerrar_ventana() -> None:
    """Cierra la ventana del proceso principal (la cara tiene la suya).

    Mientras la cara está en pantalla esta ventana no dibuja NADA: es un fondo
    negro tapado por el subproceso. Dejarla viva daba dos ventanas pygame
    peleando por el mismo monitor, y dos entradas en la barra de tareas.
    """
    global pantalla
    if pantalla is None:
        return
    pygame.display.quit()
    pantalla = None


def _esperar_cara_lista(proc: subprocess.Popen) -> bool:
    """Espera la línea 'LISTO' que la cara manda tras pintar su primer cuadro.

    POR QUÉ ESPERAR. La cara tarda ~0.7 s en aparecer. Sin este apretón de
    manos hay que elegir entre dos cosas feas: cerrar la ventana de fondo antes
    y mostrar el ESCRITORIO durante ese rato, o no cerrarla nunca y quedarse con
    la ventana duplicada. Esperando, el traspaso no tiene ningún hueco.

    Si la cara no avisa (arrancó mal, versión vieja), se devuelve False y la
    ventana de fondo se queda: peor que perfecto, pero nunca peor que antes.
    """
    if proc.stdout is None:
        return False
    limite = time.time() + _ESPERA_CARA_S
    while True:
        restante = limite - time.time()
        if restante <= 0 or not select.select([proc.stdout], [], [], restante)[0]:
            break
        linea = proc.stdout.readline()
        if not linea:                 # el proceso se murió
            break
        if linea.strip() == b"LISTO":
            return True
    print("[PROYECTOR] La cara no avisó que arrancó; dejo la ventana de fondo.")
    return False


def _desactivar_cara() -> None:
    """Termina el subproceso de animación si está corriendo."""
    global _cara_proc
    if _cara_proc and _cara_proc.poll() is None:
        _cara_proc.terminate()
        try:
            _cara_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _cara_proc.kill()
    _cara_proc = None


def _iniciar_cara(expresion: str = "idle") -> None:
    """Lanza el subproceso de animación con la expresión indicada."""
    global _cara_proc
    _desactivar_cara()
    _cara_proc = subprocess.Popen(
        [
            sys.executable, _CARA_SCRIPT,
            str(_PROYECTOR_W), str(_PROYECTOR_H),
            str(_PROYECTOR_X), str(_PROYECTOR_Y),
            expresion,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env={**os.environ,
             "DISPLAY": os.environ.get("DISPLAY", ":0"),
             # Sin esto la primera línea del pipe sería el saludo de pygame.
             "PYGAME_HIDE_SUPPORT_PROMPT": "1"},
    )
    if _esperar_cara_lista(_cara_proc):
        _cerrar_ventana()
    print(f"[PROYECTOR] Cara activada: {expresion}")


def cambiar_expresion(expresion: str) -> None:
    """
    Cambia la expresión de la cara en tiempo real sin reiniciar el proceso.
    Si la cara no está activa, la inicia con la expresión indicada.
    """
    global _cara_proc
    if _cara_proc and _cara_proc.poll() is None:
        try:
            _cara_proc.stdin.write(f"expresion:{expresion}\n".encode())
            _cara_proc.stdin.flush()
            return
        except (BrokenPipeError, OSError):
            pass
    _iniciar_cara(expresion)


def enviar_volumen(v: float) -> None:
    """Envía el volumen de audio (0.0–1.0) al proceso de cara para sincronizar la boca."""
    global _cara_proc
    if _cara_proc and _cara_proc.poll() is None:
        try:
            _cara_proc.stdin.write(f"volumen:{v:.3f}\n".encode())
            _cara_proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass


# NO HAY `mostrar_segun_tema` NI `mostrar_imagen`, Y ES A PROPÓSITO.
# Proyectaban una foto del sitio mientras MEXA contestaba. No funcionaba, y no
# por un bug chico: `mostrar_imagen` mataba el subproceso de la cara para
# pintar la foto, y el `cambiar_expresion("hablando")` de la línea siguiente lo
# relanzaba enseguida, tapándola. La cara tarda ~0.7 s en aparecer (ver
# `_esperar_cara_lista`), así que la imagen se veía ese rato y desaparecía
# ANTES de que MEXA dijera una palabra. Era una regresión: `mostrar_segun_tema`
# es anterior a la cara animada, y la cara le tomó el proyector.
#
# En un proyector no entran las dos cosas, y la cara es lo que le da presencia
# al robot. Así que gana la cara y esto se fue entero.
#
# Si algún día se quiere la foto de vuelta, lo que hay que resolver PRIMERO es
# quién manda en la pantalla mientras MEXA habla — no reescribir esta función.
# Y de paso, dos bugs que tenía y que no hay que heredar: matcheaba por
# SUBCADENA ("mexica" adentro de "mexicana" mostraba la foto azteca) y las
# claves iban sin acento, así que "Teotihuacán" bien pronunciado NO mostraba
# `teotihuacan.jpg`.

def pantalla_bienvenida():
    """Inicia la cara animada en expresión idle (esperando visitantes)."""
    _iniciar_cara("idle")

def reproducir_video(ruta_video: str, duracion_seg: float = 15.0):
    """
    Reproduce un video dentro de la ventana pygame ya posicionada en el proyector.
    OpenCV decodifica los frames; cvlc maneja el audio en paralelo.
    Se detiene después de `duracion_seg` segundos (por defecto 15).
    """
    global pantalla

    # EL ARCHIVO SE CHEQUEA ANTES DE TOCAR LA PANTALLA, y el orden es el
    # arreglo. Antes se mataba la cara, se abría la ventana y RECIÉN entonces
    # se miraba si el video existía: con un video faltante el visitante se
    # quedaba mirando un cartel de "Video no disponible". El proyector no
    # muestra texto — un cartel de error en la cara de un jurado es peor que
    # cualquier falla silenciosa. Chequeando primero, si el video no está la
    # cara sigue donde estaba y el visitante no ve nada raro; el problema
    # queda en consola, que es para quien sí lo tiene que ver.
    if not os.path.exists(ruta_video):
        print(f"[PROYECTOR] Video no encontrado: {ruta_video}")
        return

    _desactivar_cara()
    # La cara cierra esta ventana al tomar la pantalla, así que hay que
    # reabrirla. Antes se daba por sentado que seguía viva y el video reventaba
    # con AttributeError sobre None.
    iniciar_proyector()

    cap = cv2.VideoCapture(ruta_video)
    if not cap.isOpened():
        print(f"[PROYECTOR] No se pudo abrir el video: {ruta_video}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    max_frames = int(fps * duracion_seg)
    clock = pygame.time.Clock()

    audio = subprocess.Popen(
        ["cvlc", "--no-video", "--play-and-exit", ruta_video],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    print(f"[PROYECTOR] Reproduciendo: {ruta_video} ({duracion_seg}s)")
    frames_reproducidos = 0
    try:
        while frames_reproducidos < max_frames:
            ret, frame = cap.read()
            if not ret:
                break
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            surface = pygame.image.frombuffer(
                frame_rgb.tobytes(),
                (frame_rgb.shape[1], frame_rgb.shape[0]),
                "RGB",
            )
            surface = pygame.transform.scale(surface, (_PROYECTOR_W, _PROYECTOR_H))
            pantalla.blit(surface, (0, 0))
            pygame.display.flip()
            pygame.event.pump()
            clock.tick(fps)
            frames_reproducidos += 1
    finally:
        cap.release()
        audio.terminate()
        audio.wait()

    pantalla.fill((0, 0, 0))
    pygame.display.flip()
    print("[PROYECTOR] Video terminado.")


def apagar_proyector():
    _desactivar_cara()
    pygame.quit()
    print("[PROYECTOR] Apagado.")
