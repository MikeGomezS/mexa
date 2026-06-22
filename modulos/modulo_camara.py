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

# --- Filtro de persistencia (debounce temporal) ------------------------------
# El detector Haar evalúa cada frame de forma AISLADA, sin memoria: pierde la
# cara en frames sueltos (giro leve, poca luz, movimiento) y la recupera al
# siguiente. Eso hace PARPADEAR el estado (el test marcó 22 cambios en 20s con
# una persona quieta frente a la cámara). El parpadeo NO es del cable ni del
# sensor: es del algoritmo.
#
# El filtro exige CONSISTENCIA temporal antes de cambiar el estado confirmado:
#   - Pasa a "hay cara" sólo tras UMBRAL_PRESENCIA frames SEGUIDOS con cara.
#   - Pasa a "sin cara" sólo tras UMBRAL_AUSENCIA  frames SEGUIDOS sin cara.
# Así un miss aislado ya no tumba la detección, y un falso positivo aislado
# tampoco la dispara. Es el patrón debounce clásico (igual que el de un botón).
#
# Umbrales ASIMÉTRICOS a propósito: confirmamos presencia rápido (no hacer
# esperar al visitante) pero soltamos despacio (aguantar parpadeos breves).
UMBRAL_PRESENCIA = 2   # frames seguidos con cara para CONFIRMAR presencia
UMBRAL_AUSENCIA  = 4   # frames seguidos sin cara para CONFIRMAR ausencia

_hits_seguidos = 0          # frames consecutivos con cara (crudo)
_misses_seguidos = 0        # frames consecutivos sin cara (crudo)
_presencia_confirmada = False  # estado ya filtrado que devuelve detectar_cara()


def reiniciar_filtro():
    """Resetea el debounce. Llamar al empezar una interacción nueva para que
    no arrastre el estado de la persona anterior."""
    global _hits_seguidos, _misses_seguidos, _presencia_confirmada
    _hits_seguidos = 0
    _misses_seguidos = 0
    _presencia_confirmada = False


def _actualizar_filtro(hay_cara_cruda: bool) -> bool:
    """Alimenta el debounce con la detección CRUDA de un frame y devuelve el
    estado de presencia ya FILTRADO. Sólo imprime en las transiciones reales."""
    global _hits_seguidos, _misses_seguidos, _presencia_confirmada
    antes = _presencia_confirmada
    if hay_cara_cruda:
        _hits_seguidos += 1
        _misses_seguidos = 0
        if _hits_seguidos >= UMBRAL_PRESENCIA:
            _presencia_confirmada = True
    else:
        _misses_seguidos += 1
        _hits_seguidos = 0
        if _misses_seguidos >= UMBRAL_AUSENCIA:
            _presencia_confirmada = False
    if _presencia_confirmada != antes:
        print(f"[CAMARA] Presencia {'CONFIRMADA' if _presencia_confirmada else 'PERDIDA'}.")
    return _presencia_confirmada

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
    """Regresa True si hay una cara presente de forma SOSTENIDA en el tiempo.

    No es la detección cruda de un frame: pasa por el filtro de persistencia
    (ver _actualizar_filtro). Pensada para llamarse en un LOOP de polling —
    cada llamada aporta un frame de evidencia. Una llamada suelta sólo mueve
    los contadores un paso y no confirma nada por sí sola.

    Un frame None (sin cámara o captura vencida) cuenta como 'sin cara':
    si el CSI deja de transmitir, la presencia decae sola y no queda pegada."""
    if frame is None:
        frame = capturar_frame()
    hay_cruda = frame is not None and len(_buscar_caras(frame)) > 0
    return _actualizar_filtro(hay_cruda)

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
