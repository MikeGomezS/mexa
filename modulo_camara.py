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

# CascadeClassifier se carga una sola vez al importar el módulo.
# Recrearlo en cada llamada cargaba el XML del disco en cada frame.
_detector = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

def iniciar_camara():
    global cam
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

def capturar_frame():
    """Captura un frame de la cámara y lo regresa como array."""
    if cam is None:
        iniciar_camara()
    return cam.capture_array()

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
