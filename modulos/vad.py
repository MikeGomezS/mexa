# ============================================================
#  MEXA — Detección de actividad de voz (VAD)
#
#  QUÉ DECIDE ESTE MÓDULO: cuándo el visitante EMPEZÓ y cuándo
#  TERMINÓ de hablar. Nada más. No captura audio, no decodifica
#  palabras, no toca el micrófono — recibe PCM y tiempo, y
#  devuelve un booleano. Está separado de modulo_audio.py porque
#  dejó de ser un detalle de la captura: son dos implementaciones
#  con su propio modelo, y porque una regla que no depende del
#  hardware se puede verificar sin hardware.
#  Ver tests/test_umbral_adaptativo.py.
#
#  DOS DETECTORES, UNA MISMA REGLA DE TIEMPO:
#
#  1. `DetectorVoz` — energía RMS contra un umbral RELATIVO al
#     ruido de sala medido. Mide VOLUMEN. Barato y sin modelo,
#     pero un pico de sala más fuerte que el umbral le parece
#     voz, porque el volumen es lo único que sabe mirar.
#
#  2. `DetectorVozNeural` — Silero VAD (ONNX, 2.3 MB) sobre
#     ventanas de 512 muestras a 16 kHz. Decide por FORMA
#     ESPECTRAL, no por volumen: por eso puede rechazar un golpe
#     fuerte y aceptar una voz suave, que es exactamente lo que
#     un umbral no puede hacer. Cuesta 0.26 ms por ventana de
#     32 ms en la Pi 5 — 0.8% de un núcleo. Es el que corre en
#     producción cuando el modelo está instalado.
#
#  La regla de TIEMPO (cuánto habla mínima, cuánto silencio para
#  cortar) es la MISMA para los dos y vive en `_SeguimientoHabla`:
#  cambiar de detector no debe cambiar el ritmo de la conversación.
# ============================================================

import audioop
import os
from collections import deque

_BASE_DIR   = os.path.dirname(__file__)
_MODELO_VAD = os.path.join(_BASE_DIR, "..", "media", "vad", "silero_vad.onnx")

_SILENCIO_SEG  = 1.5   # segundos de silencio continuo para dejar de escuchar
_MIN_HABLA_SEG = 0.3   # segundos mínimos de habla antes de activar el corte

_RATE_VAD = 16000      # el VAD ve el audio ya remuestreado, igual que Vosk

# ── Umbral de energía RELATIVO al ruido de la sala ───────────
# Antes había un número fijo (300 RMS) calibrado en un cuarto tranquilo.
# Un número fijo mide VOLUMEN, no voz, y falla en las DOS direcciones al
# cambiar de sala: en la expo el murmullo de fondo ya supera 300, el VAD
# nunca cierra y Vosk transcribe ruido; y un visitante que habla bajito
# nunca llega a 300, así que MEXA queda sorda. Los dos modos de falla
# salen del MISMO número. Acá el umbral se deriva del ruido MEDIDO.
#
# El factor NO se eligió a ojo: se barrió de 1.8 a 3.5 contra el test.
# Con ruido de sala PAREJO ganaba 1.8 — y era una trampa del test, porque
# el ruido blanco casi no varía de chunk a chunk. Agregando una sala con
# PICOS (risas, un carrito), todo lo que estuviera por debajo de 3.0
# quedaba PEGADO: cada pico reinicia la cuenta de silencio y el VAD no
# cierra nunca. 3.0 es el primer valor que aguanta los picos, y 3.5 no
# compra nada más y sordea al que habla bajo.
_FACTOR_UMBRAL  = 3.0    # cuánto por encima del ruido tiene que estar la voz (~9.5 dB)
_UMBRAL_MIN     = 120    # piso: una sala muy callada no vuelve al VAD hipersensible
_UMBRAL_MAX     = 4000   # techo: una sala imposible no deja a MEXA muda del todo
_PISO_INICIAL   = 100    # antes de calibrar: 100 × 3.0 = 300, el viejo fijo
_PERCENTIL_PISO = 0.20   # el ruido de fondo vive en la parte baja de la energía
_VENTANA_PISO   = 64     # chunks de historia (~6 s) para re-medir la sala sola

# ── Silero VAD ───────────────────────────────────────────────
_VENTANA_SILERO  = 512   # v5 exige EXACTAMENTE 512 muestras a 16 kHz (32 ms)
_CONTEXTO_SILERO = 64    # ...precedidas por las 64 muestras de la ventana anterior

# OJO — ESTE NÚMERO NO ESTÁ CALIBRADO POR EVIDENCIA, a diferencia de los
# dos factores de energía. Barrido de 0.20 a 0.60 contra el test: da
# EXACTAMENTE el mismo resultado en los diez casos, porque Silero devuelve
# casi siempre ~0 o ~1 y casi nunca algo intermedio. Es el default de
# Silero (0.5) apenas más permisivo. Si alguien necesita moverlo, que
# primero agregue al test el caso que hoy no distingue nada.
_PROB_VOZ = 0.45         # probabilidad mínima para llamarlo voz

# El detector neuronal TAMBIÉN mira la energía. No es redundancia ni
# cinturón y tirantes: son dos preguntas distintas.
#   Silero responde     "¿esto es voz?"        → rechaza golpes y ruido.
#   La energía responde "¿esto es voz de ACÁ?" → rechaza al stand de al lado.
# Medido: contra murmullo de sala (gente hablando), Silero SOLO queda
# PEGADO — peor que el umbral de energía — porque el murmullo ES voz y la
# forma espectral no distingue quién lo dijo. Lo único que separa al
# visitante del resto de la sala es que está MÁS CERCA del micrófono.
#
# El factor es más bajo que `_FACTOR_UMBRAL` porque acá la compuerta no
# tiene que rechazar golpes: de eso ya se encarga Silero. Barrido de 1.2
# a 2.5: por debajo de 1.8 el murmullo vuelve a dejar el VAD PEGADO. Se
# usa 2.0 —y no 1.8, que es el borde justo— por margen contra un murmullo
# real que no sea idéntico al sintético.
_FACTOR_ENERGIA_NEURAL = 2.0

# El piso arranca en el valor asumido y se corrige con lo que MEXA
# realmente oye: `calibrar_ruido_ambiente()` al arrancar, y después
# sola, en cada escucha (la sala de una expo no es la misma a las 9
# que a las 13). Se sigue midiendo aunque corra el detector neuronal:
# es el diagnóstico de la sala y la red de contención si falta el modelo.
_piso_ruido:   float      = _PISO_INICIAL
_ventana_piso: deque[int] = deque(maxlen=_VENTANA_PISO)

_sesion_vad = None   # sesión ONNX, cargada una sola vez


# ── Acondicionamiento de la señal ────────────────────────────

def quitar_dc(pcm: bytes) -> bytes:
    """Le saca a un chunk su componente continua (offset DC).

    POR QUÉ, y por qué NO es por Vosk: el iTalk-02 mete un offset de ~250
    (mediana medida). A Vosk le da exactamente igual —medido: WER idéntico
    hasta el tercer decimal con DC de 0, 250 y hasta 2000, porque Kaldi
    hace pre-énfasis y normaliza la media de los features—. El que sufre
    es el VAD.

    El DC no infla el RMS de forma pareja: se suma en cuadratura, así que
    sobre ruido de 385 agrega 19% y sobre voz de 2500 agrega 0.5%. O sea
    que levanta el piso mucho más que la voz y COMPRIME justo el margen
    que el VAD usa para decidir. Medido sobre la misma escena: el margen
    voz/umbral cae de 2.78x a 2.34x, y esta corrección lo devuelve a
    2.78x exacto.

    Se aplica por chunk (la media de un chunk con voz ya es ~0, así que
    restarla es inocuo) y verificado que no cambia el reconocimiento.
    """
    return audioop.bias(pcm, 2, -audioop.avg(pcm, 2))


# ── Medición del ruido de sala ───────────────────────────────

def piso_desde_muestras(rms) -> float:
    """Estima el ruido de fondo como un percentil BAJO de la energía reciente.

    POR QUÉ UN PERCENTIL Y NO UN PROMEDIO: el promedio se contamina con
    la voz, con una tos o con una silla que se arrastra. El ruido de sala
    es lo que está SIEMPRE, así que vive en la parte baja de la
    distribución; los picos son eventos, no piso.

    POR QUÉ NO "APRENDER SÓLO DE LOS CHUNKS SILENCIOSOS": un estimador
    que sólo mira lo que ya considera silencio no puede SUBIR. Si arranca
    creyendo que la sala es tranquila y no lo es, todos los chunks le
    parecen voz, nunca aprende y queda trabado en el error — que es justo
    el caso de la expo. El percentil sube y baja sin necesitar etiquetas.

    Función PURA: sin micrófono ni estado, verificable con series armadas.
    """
    if not rms:
        return _PISO_INICIAL
    ordenadas = sorted(rms)
    return float(ordenadas[int(_PERCENTIL_PISO * (len(ordenadas) - 1))])


def acotar_umbral(umbral: float) -> int:
    """Mete cualquier umbral de energía dentro de los límites de la sala.

    ES EL ÚNICO LUGAR QUE CONOCE LOS LÍMITES, y eso es el punto. Antes el
    acote estaba escrito a mano dentro de `umbral_desde_piso` y la
    compuerta del detector neuronal se olvidó del techo: en una sala de
    3000 RMS la compuerta se iba a 6000 y MEXA quedaba MUDA, justo lo que
    `_UMBRAL_MAX` dice evitar. Dos caminos, una regla escrita dos veces,
    una de las dos incompleta. Ahora hay un solo lugar donde equivocarse.
    """
    return int(min(max(umbral, _UMBRAL_MIN), _UMBRAL_MAX))


def umbral_desde_piso(piso: float) -> int:
    """Traduce un piso de ruido medido al umbral de voz, acotado.

    La asimetría de los límites es deliberada. Quedarse SORDO cuesta que
    el visitante repita: tres segundos. Quedarse PEGADO —tomar el ruido
    por voz— cuesta que MEXA transcriba la sala y le conteste a nadie,
    delante del jurado. Ante la duda, este umbral prefiere lo primero,
    igual que `escuchar_idioma` prefiere repreguntar.
    """
    return acotar_umbral(piso * _FACTOR_UMBRAL)


def piso_actual() -> float:
    """Ruido de sala medido hasta ahora, en RMS."""
    return _piso_ruido


def umbral_actual() -> int:
    """Umbral de energía vigente, según el ruido de sala medido hasta ahora."""
    return umbral_desde_piso(_piso_ruido)


def registrar_ruido(muestras) -> None:
    """Suma energía observada a la ventana móvil y re-mide la sala."""
    global _piso_ruido
    if not muestras:
        return
    _ventana_piso.extend(muestras)
    _piso_ruido = piso_desde_muestras(list(_ventana_piso))


# ── La regla de tiempo, común a los dos detectores ───────────

class _SeguimientoHabla:
    """Cuándo empezó y cuándo terminó de hablar, dado "hay voz / no hay voz".

    No sabe de audio ni de umbrales: recibe un booleano por chunk. Está
    aislada para que cambiar de detector NO cambie el ritmo de la
    conversación — el visitante no debería notar qué VAD corre adentro.
    """

    def __init__(self):
        self.habla_inicio:    float | None = None
        self.silencio_inicio: float | None = None

    def observar(self, hay_voz: bool, ahora: float) -> bool:
        """Devuelve True cuando el visitante terminó de hablar."""
        if hay_voz:
            if self.habla_inicio is None:
                self.habla_inicio = ahora
            self.silencio_inicio = None
        elif self.habla_inicio and (ahora - self.habla_inicio) >= _MIN_HABLA_SEG:
            if self.silencio_inicio is None:
                self.silencio_inicio = ahora
            elif ahora - self.silencio_inicio >= _SILENCIO_SEG:
                return True   # silencio prolongado → dejar de escuchar
        return False


class _DetectorBase:
    """Lo común: contabilidad del ruido y delegación en la regla de tiempo.

    Recibe PCM 16-bit mono a 16 kHz, NO el micrófono. Está separado a
    propósito, por el mismo motivo que `decidir_idioma` es una función
    pura: así la regla se verifica con escenas armadas (ruido → habla →
    ruido) sin depender de que haya alguien hablándole al robot.
    """

    def __init__(self):
        self.muestras: list[int] = []
        self._seguimiento = _SeguimientoHabla()

    def observar(self, pcm: bytes, ahora: float) -> bool:
        """Procesa un chunk. Devuelve True cuando el visitante terminó."""
        self.muestras.append(audioop.rms(pcm, 2))
        return self._seguimiento.observar(self._hay_voz(pcm), ahora)

    def _hay_voz(self, pcm: bytes) -> bool:
        raise NotImplementedError

    @property
    def hubo_voz(self) -> bool:
        return self._seguimiento.habla_inicio is not None


class DetectorVoz(_DetectorBase):
    """VAD por ENERGÍA: hay voz si el chunk supera el umbral.

    El umbral se fija al CREAR el detector y no se toca durante la frase:
    recalcularlo a mitad de habla dejaría que la propia voz del visitante
    levante el piso de ruido, y el VAD se cortaría solo.
    """

    def __init__(self, umbral: int | None = None):
        super().__init__()
        self.umbral = umbral_actual() if umbral is None else umbral

    @property
    def umbral_energia(self) -> int:
        """El nivel por debajo del cual este detector no oye nada.

        Se llama igual que en `DetectorVozNeural` a propósito, aunque no
        signifiquen lo mismo: acá es TODA la decisión, allá es solo la
        compuerta previa a Silero. Quien mide la sala necesita preguntar
        "¿a qué nivel dejás de oír?" sin saber cuál de los dos corre.
        """
        return self.umbral

    def _hay_voz(self, pcm: bytes) -> bool:
        return self.muestras[-1] >= self.umbral

    def __str__(self) -> str:
        return f"energía (umbral {self.umbral})"


# ── Silero VAD ───────────────────────────────────────────────

def vad_neural_disponible() -> bool:
    """True si el modelo Silero está en disco y onnxruntime puede cargarlo."""
    return os.path.isfile(_MODELO_VAD) and _cargar_sesion() is not None


def _cargar_sesion():
    """Devuelve la sesión ONNX, cargándola la primera vez. None si no se puede.

    UN SOLO HILO a propósito: medido en la Pi 5, más hilos no aceleran
    nada (0.26 → 0.21 ms) y en la exhibición esos núcleos los necesitan
    Vosk, la cámara y el proyector.
    """
    global _sesion_vad
    if _sesion_vad is None:
        if not os.path.isfile(_MODELO_VAD):
            return None
        try:
            import onnxruntime as ort
            opciones = ort.SessionOptions()
            opciones.intra_op_num_threads = 1
            opciones.inter_op_num_threads = 1
            opciones.log_severity_level   = 3   # ONNX es ruidoso por consola
            _sesion_vad = ort.InferenceSession(
                _MODELO_VAD, opciones, providers=["CPUExecutionProvider"])
            print("[VAD] Silero VAD cargado.")
        except Exception as e:
            print(f"[VAD] No se pudo cargar Silero ({e}); se usa energía.")
            return None
    return _sesion_vad


class DetectorVozNeural(_DetectorBase):
    """VAD NEURONAL: hay voz si Silero le da suficiente probabilidad.

    POR QUÉ ES MEJOR QUE UN UMBRAL: un umbral sólo sabe de volumen, así
    que una risa fuerte le parece voz y un visitante suave no le parece
    nada. Silero mira la FORMA del espectro a lo largo del tiempo — la
    misma idea con la que Alexa detecta susurros, que no son voz baja
    sino voz NO SONORA, espectralmente distinta.

    Silero v5 exige ventanas de EXACTAMENTE 512 muestras. Los chunks del
    micrófono no son múltiplo de 512, así que lo que sobra se guarda y se
    pega al chunk siguiente: el modelo lleva estado entre ventanas y
    saltearse muestras le rompe la continuidad.

    OJO — EL TENSOR DE ENTRADA NO ES DE 512 SINO DE 576: el modelo espera
    las 64 muestras ANTERIORES pegadas adelante de la ventana. No es un
    detalle cosmético ni algo que el modelo tolere: medido sobre la misma
    frase de Piper, sin contexto la probabilidad media de voz da 0.003
    (SORDO en todos los casos del test) y con contexto da 0.893. Es
    silencioso porque el modelo acepta el tensor igual y devuelve ceros.
    """

    def __init__(self, prob_minima: float = _PROB_VOZ,
                 piso: float | None = None):
        super().__init__()
        import numpy as np
        self._np          = np
        self.prob_minima  = prob_minima
        self.umbral_energia = acotar_umbral(
            (_piso_ruido if piso is None else piso) * _FACTOR_ENERGIA_NEURAL)
        self.ultima_prob  = 0.0
        self._resto       = np.zeros(0, dtype=np.int16)
        self._contexto    = np.zeros(_CONTEXTO_SILERO, dtype=np.float32)
        self._estado      = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr          = np.array(_RATE_VAD, dtype=np.int64)
        self._sesion      = _cargar_sesion()

    def _hay_voz(self, pcm: bytes) -> bool:
        if self._sesion is None:   # sin modelo, no hay decisión que tomar
            return False
        if self.muestras[-1] < self.umbral_energia:
            return False           # demasiado flojo para venir de acá adelante
        np = self._np
        self._resto = np.concatenate(
            (self._resto, np.frombuffer(pcm, dtype=np.int16)))

        # Un chunk trae varias ventanas; alcanza con que UNA sea voz para
        # que el chunk cuente como habla. Perder el arranque de una frase
        # cuesta más que aceptar 32 ms de más.
        hay_voz = False
        while len(self._resto) >= _VENTANA_SILERO:
            ventana, self._resto = (self._resto[:_VENTANA_SILERO],
                                    self._resto[_VENTANA_SILERO:])
            ventana = ventana.astype(np.float32) / 32768.0
            entrada = np.concatenate((self._contexto, ventana)).reshape(1, -1)
            salida, self._estado = self._sesion.run(
                None, {"input": entrada, "state": self._estado, "sr": self._sr})
            self._contexto   = ventana[-_CONTEXTO_SILERO:]
            self.ultima_prob = float(salida[0][0])
            hay_voz = hay_voz or self.ultima_prob >= self.prob_minima
        return hay_voz

    def __str__(self) -> str:
        return (f"Silero neuronal (prob ≥ {self.prob_minima}, "
                f"energía ≥ {self.umbral_energia})")


def crear_detector(piso: float | None = None):
    """Devuelve el mejor detector disponible.

    Silero si está instalado; energía si no. La degradación es a propósito
    y no silenciosa: MEXA tiene que seguir escuchando aunque falte el
    modelo, pero quien mire la consola tiene que enterarse de con qué oído
    está trabajando.

    `piso` fuerza el ruido de sala del que sale el umbral, en vez del que
    MEXA viene midiendo sola. Lo usa quien mide la sala a mano
    (`tests/calibrar_umbral_voz.py`), que tiene un piso recién medido y
    todavía no cargado. Sin esto, ese script tenía que decidir por su
    cuenta QUÉ detector corre y CON QUÉ umbral — y esa duplicación fue
    justo lo que lo hizo dictar veredicto contra el detector equivocado.
    """
    if vad_neural_disponible():
        return DetectorVozNeural(piso=piso)
    return DetectorVoz(None if piso is None else umbral_desde_piso(piso))
