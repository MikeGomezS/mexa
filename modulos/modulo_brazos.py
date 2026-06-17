# ============================================================
#  MEXA — Módulo 08: Control de Brazos (Arduino via USB Serial)
#  Hardware: 2x Servo + Arduino (USB Serial)
#
#  CONEXIONES ARDUINO (ver arduino/mexa/mexa.ino):
#    Brazo izquierdo → D10
#    Brazo derecho   → D11
#    (D2–D9 los usan los 4 motores DC)
#
#  PROTOCOLO SERIAL (manejado por el firmware unificado):
#    H → iniciar animación (hablando)
#    P → detener y volver a posición de reposo
#
#  NOTA: la conexión serial es COMPARTIDA con los motores
#  (un solo Arduino). El transporte vive en conexion_arduino.py.
# ============================================================

from .conexion_arduino import iniciar_conexion, enviar


def iniciar_brazos():
    """Abre (o reutiliza) la conexión serial compartida con el Arduino."""
    iniciar_conexion()


def animar():
    """Activa la animación de brazos (llamar al inicio de hablar)."""
    enviar("H")


def parar():
    """Detiene la animación y regresa los brazos a reposo."""
    enviar("P")


def cerrar_brazos():
    """Regresa los brazos a reposo. NO cierra el puerto: es compartido con
    los motores. El cierre lo hace conexion_arduino.cerrar_conexion()."""
    parar()
    print("[BRAZOS] En reposo.")
