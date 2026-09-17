# ============================================================
#  MEXA — Módulo 05: Control de Motores DC
#  Hardware: 4x Motor DC + puente(s) H tipo MX1508 + Arduino (USB Serial)
#
#  CONEXIONES ARDUINO → puente H (fuente: arduino/mexa/mexa.ino:68-78):
#    Motor 0 → D2, D3  ┐ LADO IZQUIERDO
#    Motor 1 → D4, D5  ┘
#    Motor 2 → D6, D7  ┐ LADO DERECHO (montados en espejo: el firmware les
#    Motor 3 → D8, D9  ┘ invierte el sentido por software, sin tocar cables)
#
#  SIN PWM. El firmware maneja los pines con digitalWrite: cada motor está a
#  fondo o parado, no hay estado intermedio. Lo único que se elige por software
#  es CUÁNTO DURA el movimiento (ver PULSO_GIRO_S).
#
#  ESTAS FUNCIONES YA NO ACEPTAN `velocidad`. Lo aceptaban y lo IGNORABAN, con
#  el argumento de "no romper a quien ya las llama". Se auditó el 2026-09-17:
#  NADIE lo pasaba, ni por nombre ni posicionalmente, en ningún módulo ni
#  test. O sea que la razón para conservarlo era falsa y el parámetro sólo
#  servía para que una llamada con velocidad pareciera hacer algo. El día que
#  haya un driver con PWM se agrega de vuelta, con un firmware que lo use.
#
#  PROTOCOLO SERIAL (firmware unificado, arduino/mexa/mexa.ino:345-364):
#    Conducir      F → adelante   B → atrás
#                  R → girar derecha   L → girar izquierda   S → stop
#    Diagnóstico   1..4 → mueve UN solo motor (0..3) y frena el resto
#    Brazos        H → gesticular   P → volver a reposo
#    El Arduino responde "OK <cmd>" a cada comando que reconoce.
#
#  EL FIRMWARE FRENA SOLO. Mientras hay un 'F' activo vigila los ultrasónicos
#  frontales y frena si alguien está demasiado cerca; durante un 'R'/'L' vigila
#  el lateral de ese lado y cancela el giro si hay pared. O sea: un comando
#  puede terminar ANTES de lo que esta capa pidió. Quien necesite saberlo
#  consulta freno_por_persona() en conexion_arduino.py.
#
#  NOTA: la conexión serial es COMPARTIDA con los brazos y los sensores
#  (un solo Arduino). El transporte vive en conexion_arduino.py.
# ============================================================

import time

from .conexion_arduino import iniciar_conexion, enviar

# ── Cuánto dura UN pulso de giro ─────────────────────────────
# ÚNICA FUENTE DE VERDAD. Vive acá y no en el lazo de navegación porque es una
# propiedad del TREN DE TRACCIÓN, no de la cámara: los motores no tienen PWM
# (el firmware los maneja con digitalWrite, ver arduino/mexa/mexa.ino), así que
# la velocidad angular es una constante de hardware. Lo único que se elige por
# software es CUÁNTO RATO gira, y eso es esto.
#
# MÁS LARGO = MENOS PULSOS para encarar al visitante, y la maniobra completa
# termina antes: cada pulso paga SETTLE_ACERCAMIENTO_S (0.35s) de tiempo muerto
# anti-blur, así que barrer el mismo ángulo en 2 pulsos en vez de 3 ahorra una
# tanda entera de ese peaje. El techo lo pone la banda central de la cámara
# ([0.4, 0.6] del ancho, ver modulo_camara._clasificar_horizontal): si un pulso
# barre MÁS que esa banda, MEXA se pasa de largo y oscila izquierda-derecha en
# vez de converger.
#
# Historial: 0.25 -> 0.80 (giro menos entrecortado) -> 1.20 (menos pulsos).
# MEDIR con `python3 tests/calibrar_pulsos.py giro` antes de volver a tocarlo.
PULSO_GIRO_S = 1.20



def iniciar_motores():
    """Abre (o reutiliza) la conexión serial compartida con el Arduino."""
    iniciar_conexion()


def mover_adelante():
    enviar("F")

# NO HAY `mover_atras`. La tenía y nadie la llamaba nunca: el retroceso pasa
# por `mover_por_tiempo("atras", ...)` —vía la tabla `_COMANDO` de abajo—, que
# es lo que usa `registro_camino.retroceder`. Ir hacia atrás sigue funcionando
# igual; lo que se fue es la SEGUNDA forma de pedirlo.

def girar_derecha():
    enviar("R")

def girar_izquierda():
    enviar("L")

def detener():
    enviar("S")


# Dirección en castellano -> comando del firmware. Una sola tabla: antes esto
# era una cadena de `if` dentro de mover_por_tiempo, y quien necesitaba arrancar
# un movimiento SIN dormir no tenía de dónde agarrarse.
_COMANDO = {"adelante": "F", "atras": "B", "derecha": "R", "izquierda": "L"}


def iniciar_movimiento(direccion):
    """Manda el comando y VUELVE en el acto, con los motores en marcha.

    Existe para los lazos que tienen que VIGILAR mientras se mueven — el
    firmware frena solo (persona al frente, pared al girar), y quien duerme un
    sleep ciego no se entera y termina anotando en el registro del camino un
    movimiento que no pasó. Quien no necesite vigilar nada, que use
    mover_por_tiempo(), que es esto más el sleep y el freno.

    Devuelve True si la dirección era válida (si no, no manda nada)."""
    cmd = _COMANDO.get(direccion)
    if cmd is None:
        print(f"[MOTORES] Dirección desconocida: {direccion!r}. No muevo nada.")
        return False
    enviar(cmd)
    return True


def mover_por_tiempo(direccion="adelante", segundos=1.0):
    """Mueve `segundos` y frena. Movimiento CIEGO: no mira si el firmware
    cortó por su cuenta. Si eso importa, mirá iniciar_movimiento()."""
    if not iniciar_movimiento(direccion):
        return
    time.sleep(segundos)
    detener()


def orientarse_a_usuario(posicion: str | None = None):
    if posicion == "izquierda":
        girar_izquierda()
        time.sleep(0.3)
        detener()
    elif posicion == "derecha":
        girar_derecha()
        time.sleep(0.3)
        detener()
