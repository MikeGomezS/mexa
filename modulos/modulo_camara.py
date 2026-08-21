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

import math
import os
from typing import NamedTuple

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

class Cara(NamedTuple):
    """Una cara detectada, con las señales que sirven para ELEGIRLA.

    x, y, w, h  : caja en píxeles.
    frontalidad : 1.0 = mira de frente a MEXA, 0.0 = de perfil. Es el proxy
                  de "me está hablando a MÍ": quien te habla, te mira.
    score       : confianza de YuNet [0, 1].
    """
    x: int
    y: int
    w: int
    h: int
    frontalidad: float
    score: float


# ── Frontalidad: de dónde sale ────────────────────────────────
# YuNet devuelve 15 números por cara: caja(4) + 5 landmarks(10) + score(1).
# Los landmarks son ojo der., ojo izq., punta de nariz, y las dos comisuras
# de la boca. Con los tres primeros alcanza para un proxy de YAW: en una cara
# de frente la nariz cae sobre el punto medio de los ojos; al girar la cabeza,
# la nariz se corre hacia un ojo. Se normaliza por la distancia interocular
# para que no dependa del tamaño de la cara ni de la distancia a la cámara.
#
# OJO: las comisuras dan el ANCHO de la boca, no su APERTURA. Con estos 5
# puntos NO se puede medir si alguien está hablando. Frontalidad es lo más
# cerca de "me habla a mí" que se puede llegar con este detector.
#
# Umbrales MEDIDOS sobre tests/diag_frames/ (misma persona, misma sala):
#   de frente (frames 06/07/08/11/14) -> desvío 0.00, 0.03, 0.01, 0.08, 0.02
#   de perfil (frames 12/13)          -> desvío 0.83, 2.09
# Entre 0.20 y 0.80 no cayó ninguna muestra: el corte va en ese hueco.
_DESVIO_FRONTAL = 0.20   # <= esto: de frente, frontalidad 1.0
_DESVIO_PERFIL  = 0.80   # >= esto: de perfil,  frontalidad 0.0


def _frontalidad(fila) -> float:
    """Cuánto mira esta cara hacia MEXA, en [0, 1], desde los landmarks.

    Interpola linealmente entre _DESVIO_FRONTAL y _DESVIO_PERFIL. Si los ojos
    salen pegados (cara diminuta o landmarks basura) la distancia interocular
    no sirve como escala y se devuelve 0.0: sin evidencia de que mire, no se
    la premia."""
    ojo_der  = (fila[4], fila[5])
    ojo_izq  = (fila[6], fila[7])
    nariz_x  = fila[8]
    interocular = math.hypot(ojo_izq[0] - ojo_der[0], ojo_izq[1] - ojo_der[1])
    if interocular < 1.0:
        return 0.0
    desvio = abs(nariz_x - (ojo_der[0] + ojo_izq[0]) / 2) / interocular
    if desvio <= _DESVIO_FRONTAL:
        return 1.0
    if desvio >= _DESVIO_PERFIL:
        return 0.0
    return (_DESVIO_PERFIL - desvio) / (_DESVIO_PERFIL - _DESVIO_FRONTAL)


def _buscar_caras(frame) -> list[Cara]:
    """Detecta caras en un frame con YuNet. Devuelve una lista de `Cara`, sólo
    con las de score >= _SCORE_MIN (el filtrado lo hace YuNet vía score_threshold).

    El frame se le pasa a YuNet TAL CUAL. picamera2 configurada como 'RGB888'
    entrega los bytes en orden BGR — que es justo lo que YuNet espera. La
    conversión RGB2BGR que había acá invertía R y B y le daba al detector una
    imagen con los canales cruzados. Medido sobre tests/diag_frames/: con los
    canales cruzados YuNet no veía NADA en 14 de 20 frames y las caras que sí
    encontraba salían con score 0.38-0.89; sin cruzarlos, encuentra cara en 11
    frames más y los scores suben a 0.80-0.93. Ninguna muestra empeoró.

    setInputSize debe declarar el tamaño real del frame en cada llamada por si
    cambiara la resolución."""
    h, w = frame.shape[:2]
    _detector.setInputSize((w, h))
    _, caras = _detector.detect(frame)
    if caras is None:
        return []
    return [Cara(int(f[0]), int(f[1]), int(f[2]), int(f[3]),
                 _frontalidad(f), float(f[14]))
            for f in caras]


# ── Elección de objetivo entre VARIAS personas ────────────────
# Antes se tomaba la cara MÁS GRANDE. "Más grande" no es "la que me habla":
# también es el adulto entre niños, el que pasa caminando pegado a la cámara,
# o el que está de espaldas charlando con su acompañante. Ahora cada cara se
# puntúa con tres señales y gana la de mayor puntaje.
#
# Los pesos reparten así la intención "la persona que tengo en frente y me
# está hablando": cercanía y frontalidad pesan IGUAL (son las dos mitades de
# la frase) y la centralidad desempata.
_PESO_CERCANIA    = 0.40   # está cerca de MEXA
_PESO_FRONTALIDAD = 0.40   # me está mirando (proxy de "me habla a mí")
_PESO_CENTRALIDAD = 0.20   # está EN FRENTE, no al costado del cuadro
# Tamaño de cara a partir del cual "más cerca" ya no suma: a esta altura
# relativa la persona está a distancia de conversación. Medido: en
# tests/diag_frames/ las caras a distancia de interacción dan 17-23%.
_TAMANO_SATURACION = 0.30


def _puntuar(cara: Cara, ancho: int, alto: int) -> float:
    """Puntaje [0, 1] de qué tan buen objetivo es esta cara para MEXA."""
    cercania    = min(cara.h / alto / _TAMANO_SATURACION, 1.0)
    centro_rel  = (cara.x + cara.w / 2) / ancho
    centralidad = 1.0 - min(abs(centro_rel - 0.5) / 0.5, 1.0)
    return (_PESO_CERCANIA    * cercania +
            _PESO_FRONTALIDAD * cara.frontalidad +
            _PESO_CENTRALIDAD * centralidad)


# ── Enganche temporal (lock) ──────────────────────────────────
# Puntuar por frame no alcanza: con dos personas de puntaje parecido, la
# elección se da vuelta frame a frame y MEXA zigzaguea entre las dos sin
# llegar a ninguna. Una vez elegido un objetivo, MEXA se queda con él y sólo
# lo suelta si otro lo supera por un MARGEN claro, o si lo pierde de vista
# varias lecturas seguidas.
_MARGEN_CAMBIO       = 0.15  # cuánto tiene que superar un rival al objetivo actual
_MISSES_SOLTAR       = 4     # lecturas seguidas sin ver al objetivo -> se suelta.
                             # Va por debajo de MAX_MISSES_ACERCAMIENTO (6) para
                             # que el lock se libere ANTES de que la navegación
                             # abandone la maniobra.
_RADIO_MISMO_OBJETIVO = 0.20  # fracción del ancho del frame dentro de la cual una
                              # cara se considera "la misma persona" entre frames


class _Seguidor:
    """Recuerda a QUIÉN eligió MEXA, para no cambiar de persona a mitad de camino.

    No es un tracker de verdad (no hay re-identificación): asocia por CERCANÍA
    del centro entre frames, que alcanza porque entre lectura y lectura pasan
    decenas de milisegundos y la gente no se teletransporta."""

    def __init__(self):
        self.centro = None   # (x, y) del último centro del objetivo
        self.misses = 0

    def reiniciar(self) -> None:
        self.centro = None
        self.misses = 0

    def elegir(self, caras: list[Cara], ancho: int, alto: int) -> Cara | None:
        """Devuelve la cara objetivo de este frame, o None si no se la ve."""
        if not caras:
            self._perder()
            return None

        puntajes = {id(c): _puntuar(c, ancho, alto) for c in caras}
        mejor = max(caras, key=lambda c: puntajes[id(c)])

        if self.centro is None:               # sin objetivo: engancha al mejor
            return self._enganchar(mejor)

        actual = self._reencontrar(caras, ancho)
        if actual is None:                    # el objetivo no aparece este frame
            self._perder()
            return None

        # Sigue siendo el objetivo salvo que otro lo supere por un margen claro.
        if puntajes[id(mejor)] > puntajes[id(actual)] + _MARGEN_CAMBIO:
            return self._enganchar(mejor)
        return self._enganchar(actual)

    def _reencontrar(self, caras: list[Cara], ancho: int) -> Cara | None:
        """La cara de este frame más cercana al último centro del objetivo,
        siempre que caiga dentro del radio. None si ninguna califica."""
        radio = ancho * _RADIO_MISMO_OBJETIVO
        cerca = [(math.hypot(c.x + c.w / 2 - self.centro[0],
                             c.y + c.h / 2 - self.centro[1]), c)
                 for c in caras]
        distancia, cara = min(cerca, key=lambda par: par[0])
        return cara if distancia <= radio else None

    def _enganchar(self, cara: Cara) -> Cara:
        self.centro = (cara.x + cara.w / 2, cara.y + cara.h / 2)
        self.misses = 0
        return cara

    def _perder(self) -> None:
        if self.centro is None:
            return
        self.misses += 1
        if self.misses >= _MISSES_SOLTAR:
            self.reiniciar()


_seguidor = _Seguidor()


def reiniciar_objetivo() -> None:
    """Olvida a la persona enganchada. Se llama al empezar una maniobra nueva
    (otro visitante, otro acercamiento) para que MEXA no arrastre el objetivo
    de la interacción anterior."""
    _seguidor.reiniciar()


def _elegir_cara(frame) -> Cara | None:
    """Cara objetivo de UN frame: detecta, puntúa y aplica el enganche."""
    alto, ancho = frame.shape[:2]
    return _seguidor.elegir(_buscar_caras(frame), ancho, alto)


# Nº de frames que muestrea posicion_cara() en su modo one-shot para votar la
# posición por mayoría. La detección es ruidosa frame a frame: con un solo
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
    """Posición ('izquierda'/'centro'/'derecha') de la cara OBJETIVO de UN frame.
    None si no hay objetivo visible o el frame es None.

    Usa el mismo criterio de elección que localizar_cara(). Antes tomaba
    `caras[0]` —el orden arbitrario del detector—, así que con varias personas
    el voto de posicion_cara() promediaba las posiciones de personas DISTINTAS
    y no significaba nada."""
    if frame is None:
        return None
    cara = _elegir_cara(frame)
    if cara is None:
        return None
    return _clasificar_horizontal(cara.x + cara.w // 2, frame.shape[1])


def posicion_cara(frame=None):
    """
    Regresa 'izquierda', 'centro' o 'derecha' según la posición de la cara.
    Regresa None si no hay cara detectada.

    Dos modos según cómo se llame:
      - Con `frame` explícito: evalúa SOLO ese frame (crudo). Lo usa el loop de
        polling, que ya aporta un frame por iteración y no debe re-muestrear.
      - Sin `frame` (one-shot, p. ej. orientarse_a_usuario en dialogo.py):
        MUESTREA MUESTRAS_CONSENSO frames y vota la posición por MAYORÍA. Los
        misses (None) no votan; si todas las muestras son miss, devuelve None.
        Gracias al enganche, las 5 muestras siguen a la MISMA persona.
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

    Devuelve la tupla (posicion, tamano_rel) de la cara OBJETIVO, o None si no
    hay objetivo visible (o no hay cámara / captura vencida):
      - posicion: 'izquierda'/'centro'/'derecha' — para centrar girando.
      - tamano_rel: alto_cara / alto_frame, en (0, 1]. Proxy de DISTANCIA sin
        sensor extra: cara grande => persona cerca.

    El objetivo NO es la cara más grande: es la de mayor puntaje (cercanía +
    frontalidad + centralidad), con enganche temporal para no saltar de persona
    a mitad del acercamiento. Ver _puntuar y _Seguidor.

    Es SINGLE-FRAME: el lazo que la consume aporta el suavizado temporal — un
    miss simplemente significa 'no moverse este tick'. Para una lectura one-shot
    robusta usá posicion_cara()."""
    if frame is None:
        frame = capturar_frame()
    if frame is None:
        return None
    cara = _elegir_cara(frame)
    if cara is None:
        return None
    posicion = _clasificar_horizontal(cara.x + cara.w // 2, frame.shape[1])
    return (posicion, cara.h / frame.shape[0])


def apagar_camara():
    if cam:
        cam.stop()
        print("[CAMARA] Cámara apagada.")
