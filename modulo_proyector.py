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
#        └── imagenes/
#            ├── bienvenida.jpg
#            ├── teotihuacan.jpg
#            ├── azteca.jpg
#            ├── maya.jpg
#            ├── independencia.jpg
#            ├── revolucion.jpg
#            ├── olmeca.jpg
#            └── mexico_general.jpg
# ============================================================

import cv2
import os
import subprocess
import sys

import pygame

CARPETA_IMAGENES = os.path.join(os.path.dirname(__file__), "media", "imagenes")
CARPETA_VIDEOS   = os.path.join(os.path.dirname(__file__), "media", "videos")

# Diccionario de palabras clave → archivo de imagen
IMAGENES_POR_TEMA = {
    "teotihuacan":    "teotihuacan.jpg",
    "piramide":       "teotihuacan.jpg",
    "azteca":         "azteca.jpg",
    "mexica":         "azteca.jpg",
    "templo mayor":   "azteca.jpg",
    "maya":           "maya.jpg",
    "chichen itza":   "maya.jpg",
    "independencia":  "independencia.jpg",
    "hidalgo":        "independencia.jpg",
    "morelos":        "independencia.jpg",
    "revolucion":     "revolucion.jpg",
    "zapata":         "revolucion.jpg",
    "villa":          "revolucion.jpg",
    "olmeca":         "olmeca.jpg",
    "cabeza colosal": "olmeca.jpg",
}

pantalla = None

_PROYECTOR_W = 1920
_PROYECTOR_H = 1080

_PROYECTOR_X = 0      # mismo monitor (HDMI-A-2, posición 0,0); ya no se usa segundo display
_PROYECTOR_Y = 0

_CARA_SCRIPT = os.path.join(os.path.dirname(__file__), "_cara_animada.py")

# Subproceso que corre la animación de bienvenida
_cara_proc: subprocess.Popen | None = None


def iniciar_proyector():
    """Inicializa pygame como ventana sin borde posicionada sobre el proyector (HDMI-A-1)."""
    global pantalla
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
    # Posicionar la ventana en las coordenadas exactas del proyector en el
    # escritorio virtual. SDL_VIDEO_FULLSCREEN_DISPLAY no funciona con SDL2/X11;
    # SDL_VIDEO_WINDOW_POS sí lo hace de forma confiable.
    os.environ["SDL_VIDEO_WINDOW_POS"] = f"{_PROYECTOR_X},{_PROYECTOR_Y}"
    pygame.init()
    pantalla = pygame.display.set_mode((_PROYECTOR_W, _PROYECTOR_H), pygame.NOFRAME)
    pantalla.fill((0, 0, 0))
    pygame.display.flip()
    print("[PROYECTOR] Iniciado en el monitor principal (HDMI-A-2, posición 0,0).")


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
        env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
    )
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


def mostrar_imagen(nombre_archivo: str):
    """Muestra una imagen en pantalla completa en el proyector."""
    _desactivar_cara()

    if pantalla is None:
        iniciar_proyector()

    ruta = os.path.join(CARPETA_IMAGENES, nombre_archivo)
    if not os.path.exists(ruta):
        print(f"[PROYECTOR] Imagen no encontrada: {ruta}")
        mostrar_texto("📷 Imagen no disponible")
        return

    try:
        img = pygame.image.load(ruta)
        img = pygame.transform.scale(img, pantalla.get_size())
        pantalla.blit(img, (0, 0))
        pygame.display.flip()
        print(f"[PROYECTOR] Mostrando: {nombre_archivo}")
    except Exception as e:
        print(f"[PROYECTOR] Error al mostrar imagen: {e}")

def mostrar_texto(texto: str, color=(255, 255, 255), fondo=(0, 0, 0)):
    """Muestra texto grande en la pantalla del proyector."""
    _desactivar_cara()

    if pantalla is None:
        iniciar_proyector()

    pantalla.fill(fondo)
    fuente = pygame.font.SysFont("Arial", 60, bold=True)
    palabras = texto.split()
    lineas = []
    linea_actual = ""
    for palabra in palabras:
        prueba = linea_actual + " " + palabra if linea_actual else palabra
        if fuente.size(prueba)[0] < pantalla.get_width() - 100:
            linea_actual = prueba
        else:
            lineas.append(linea_actual)
            linea_actual = palabra
    lineas.append(linea_actual)

    y_inicio = pantalla.get_height() // 2 - (len(lineas) * 70) // 2
    for i, linea in enumerate(lineas):
        superficie = fuente.render(linea, True, color)
        x = (pantalla.get_width() - superficie.get_width()) // 2
        pantalla.blit(superficie, (x, y_inicio + i * 70))

    pygame.display.flip()

def mostrar_segun_tema(respuesta: str):
    """
    Detecta el tema en la respuesta de la IA y muestra la imagen correspondiente.
    Si no encuentra tema conocido, muestra el texto de la respuesta.
    """
    respuesta_lower = respuesta.lower()
    for clave, archivo in IMAGENES_POR_TEMA.items():
        if clave in respuesta_lower:
            mostrar_imagen(archivo)
            return
    resumen = " ".join(respuesta.split()[:12]) + "..."
    mostrar_texto(resumen)

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
    _desactivar_cara()

    if not os.path.exists(ruta_video):
        print(f"[PROYECTOR] Video no encontrado: {ruta_video}")
        mostrar_texto("Video no disponible")
        return

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
