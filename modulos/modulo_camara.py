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

import os

from picamera2 import Picamera2
import cv2

cam = None

# Timeout (segundos) para capturar un frame. capture_array() se cuelga
# INDEFINIDAMENTE si el frontend CSI deja de transmitir (p. ej. cable FFC
# flojo): el job queda esperando un frame que nunca llega. Con timeout, MEXA
# degrada con gracia (sigue sin seguimiento de cara) en vez de congelarse.
# Un frame normal llega en decenas de ms; 2s es margen de sobra.
CAPTURA_TIMEOUT_S = 2.0

# Detector de caras YuNet (DNN, OpenCV FaceDetectorYN). Reemplaza al Haar
# clásico, que en este entorno (fondo cargado, contraluz, persona en
# movimiento) inventaba falsos positivos sobre sillas/reflejos/ropa y perdía
# la cara real con el blur del movimiento. YuNet es robusto al blur y al
# contraluz y entrega un SCORE de confianza por cara: el lazo de acercamiento
# —que mueve los motores— sólo actúa sobre caras de alta confianza, nunca
# sobre un fantasma. Se carga una sola vez al importar el módulo.
#
# score_threshold ALTO a propósito: este detector alimenta un lazo que MUEVE
# el robot; preferimos un miss (no moverse este tick) antes que perseguir una
# detección dudosa. El suavizado temporal lo aporta el lazo que la consume.
_YUNET_MODELO = os.path.join(
    os.path.dirname(__file__), "modelos_vision",
    "face_detection_yunet_2023mar.onnx"
)
_SCORE_MIN = 0.7   # confianza mínima [0,1] para aceptar una cara
_detector = cv2.FaceDetectorYN.create(
    _YUNET_MODELO, "", (1280, 720), score_threshold=_SCORE_MIN
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
    """Detecta caras en un frame con YuNet. Devuelve una lista de cajas
    (x, y, w, h) en píxeles, sólo de las caras con score >= _SCORE_MIN (el
    filtrado por confianza lo hace YuNet internamente vía score_threshold).

    YuNet espera la imagen en BGR; el frame de picamera2 viene en RGB
    (verificado: 'RGB888' entrega RGB real en esta config), así que se
    convierte. setInputSize debe declarar el tamaño real del frame en cada
    llamada por si cambiara la resolución."""
    h, w = frame.shape[:2]
    _detector.setInputSize((w, h))
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    _, caras = _detector.detect(bgr)
    if caras is None:
        return []
    return [(int(x), int(y), int(cw), int(ch)) for x, y, cw, ch, *_ in caras]

# Nº de frames que muestrea posicion_cara() en su modo one-shot para votar la
# posición por mayoría. La detección Haar es ruidosa frame a frame: con un solo
# frame, un miss puntual devuelve None y MEXA no se orienta. Con varias muestras
# y voto por mayoría, un par de misses no arruinan la lectura. 5 frames a ~30fps
# son <200ms: imperceptible para el visitante.
MUESTRAS_CONSENSO = 5


def _clasificar_horizontal(centro_x, ancho_frame) -> str:
    """izquierda/centro/derecha según dónde cae el centro de la cara en el
    ancho del frame. Banda central [0.4, 0.6] = 'centro'. Geometría única,
    compartida por posicion_cara() y localizar_cara() para no duplicar umbrales."""
    if centro_x < ancho_frame * 0.4:
        return "izquierda"
    elif centro_x > ancho_frame * 0.6:
        return "derecha"
    return "centro"


def _posicion_en_frame(frame):
    """Posición ('izquierda'/'centro'/'derecha') de la primera cara de UN frame.
    None si no hay cara o el frame es None. Es la geometría cruda, sin filtro."""
    if frame is None:
        return None
    caras = _buscar_caras(frame)
    if len(caras) == 0:
        return None
    x, y, w, h = caras[0]
    return _clasificar_horizontal(x + w // 2, frame.shape[1])


def posicion_cara(frame=None):
    """
    Regresa 'izquierda', 'centro' o 'derecha' según la posición de la cara.
    Regresa None si no hay cara detectada.

    Dos modos según cómo se llame:
      - Con `frame` explícito: evalúa SOLO ese frame (crudo). Lo usa el loop de
        polling, que ya aporta un frame por iteración y no debe re-muestrear.
      - Sin `frame` (one-shot, p. ej. orientarse_a_usuario en main.py): MUESTREA
        MUESTRAS_CONSENSO frames y vota la posición por MAYORÍA. Los misses
        (None) no votan; si todas las muestras son miss, devuelve None. Así una
        sola llamada no depende de un frame con suerte.
    """
    if frame is not None:
        return _posicion_en_frame(frame)

    votos = {}
    for _ in range(MUESTRAS_CONSENSO):
        pos = _posicion_en_frame(capturar_frame())
        if pos is not None:
            votos[pos] = votos.get(pos, 0) + 1
    if not votos:
        return None
    return max(votos, key=votos.get)


def localizar_cara(frame=None):
    """Lectura de UN frame para el lazo de acercamiento.

    Devuelve la tupla (posicion, tamano_rel) de la cara MÁS GRANDE, o None si
    no hay cara (o no hay cámara / captura vencida):
      - posicion: 'izquierda'/'centro'/'derecha' — para centrar girando.
      - tamano_rel: alto_cara / alto_frame, en (0, 1]. Proxy de DISTANCIA sin
        sensor extra: cara grande => persona cerca.

    Toma la cara MÁS GRANDE a propósito: si hay varias personas, MEXA se acerca
    a la de adelante. Es SINGLE-FRAME (no muestrea ni filtra): el lazo que la
    consume aporta el suavizado temporal — un miss simplemente significa 'no
    moverse este tick'. Para una lectura one-shot robusta usá posicion_cara()."""
    if frame is None:
        frame = capturar_frame()
    if frame is None:
        return None
    caras = _buscar_caras(frame)
    if len(caras) == 0:
        return None
    x, y, w, h = max(caras, key=lambda c: c[2] * c[3])
    posicion = _clasificar_horizontal(x + w // 2, frame.shape[1])
    tamano_rel = h / frame.shape[0]
    return (posicion, tamano_rel)

def apagar_camara():
    if cam:
        cam.stop()
        print("[CAMARA] Cámara apagada.")
