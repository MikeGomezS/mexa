# ============================================================
#  MEXA — Módulo 06: Cámara Arducam Módulo 3 (12MP, Autofocus)
#  Hardware: Arducam IMX708 75° AF conectada al puerto CSI
#  Librerías: picamera2, OpenCV
#  Instalar: pip install picamera2 opencv-python
#            sudo apt install python3-picamera2 -y
#
#  CONEXIÓN:
#    Cable FFC incluido con la cámara
#    Conectar al puerto CAM/CSI de la Raspberry Pi 5
#    (el puerto tiene una pequeña palanca que se jala para soltar)
# ============================================================

from picamera2 import Picamera2
import cv2

cam = None

# Timeout (segundos) para capturar un frame. capture_array() se cuelga
# INDEFINIDAMENTE si el frontend CSI deja de transmitir (p. ej. cable FFC
# flojo): el job queda esperando un frame que nunca llega. Con timeout, MEXA
# degrada con gracia (sigue sin seguimiento de cara) en vez de congelarse.
# Un frame normal llega en decenas de ms; 2s es margen de sobra.
CAPTURA_TIMEOUT_S = 2.0

# CascadeClassifier se carga una sola vez al importar el módulo.
# Recrearlo en cada llamada cargaba el XML del disco en cada frame.
_detector = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

def iniciar_camara():
    """Inicia la cámara. Si no hay cámara conectada, deja cam=None y MEXA
    sigue funcionando sin seguimiento de cara (no aborta el arranque)."""
    global cam
    try:
        cam = Picamera2()
        config = cam.create_preview_configuration(
            main={"size": (1280, 720), "format": "RGB888"}
        )
        cam.configure(config)
        # Autofocus continuo — característica principal de la Arducam Módulo 3
        cam.set_controls({
            "AfMode": 2,   # 0=manual, 1=single, 2=continuo
            "AfSpeed": 1,  # 0=normal, 1=rápido
        })
        cam.start()
        print("[CAMARA] Arducam Módulo 3 iniciada con autofocus continuo.")
    except Exception as e:
        cam = None
        print(f"[CAMARA] No se pudo iniciar la cámara ({e}). "
              "Continúo sin seguimiento de cara.")

def capturar_frame():
    """Captura un frame de la cámara. Devuelve None si no hay cámara o si la
    captura excede CAPTURA_TIMEOUT_S (p. ej. cable CSI flojo: evita que MEXA
    se congele esperando un frame que no llega)."""
    if cam is None:
        return None
    try:
        job = cam.capture_array(wait=False)
        return cam.wait(job, timeout=CAPTURA_TIMEOUT_S)
    except TimeoutError:
        print(f"[CAMARA] Captura excedió {CAPTURA_TIMEOUT_S}s "
              "(¿cable CSI flojo?). Continúo sin frame.")
        return None

def _buscar_caras(frame):
    """Detecta caras en un frame usando el detector Haar cargado al inicio."""
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    return _detector.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
    )

def detectar_cara(frame=None) -> bool:
    """Regresa True si detecta al menos una cara en la imagen."""
    if frame is None:
        frame = capturar_frame()
    if frame is None:
        return False
    caras = _buscar_caras(frame)
    if len(caras) > 0:
        print(f"[CAMARA] {len(caras)} cara(s) detectada(s).")
        return True
    return False

def posicion_cara(frame=None):
    """
    Regresa 'izquierda', 'centro' o 'derecha' según la posición de la cara.
    Regresa None si no hay cara detectada.
    """
    if frame is None:
        frame = capturar_frame()
    if frame is None:
        return None
    caras = _buscar_caras(frame)
    if len(caras) == 0:
        return None
    x, y, w, h = caras[0]
    centro_x = x + w // 2
    ancho_frame = frame.shape[1]
    if centro_x < ancho_frame * 0.4:
        return "izquierda"
    elif centro_x > ancho_frame * 0.6:
        return "derecha"
    else:
        return "centro"

def apagar_camara():
    if cam:
        cam.stop()
        print("[CAMARA] Cámara apagada.")
