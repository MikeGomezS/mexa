# ============================================================
#  MEXA — Módulo 04: Presencia (2x PIR vía Arduino)
#
#  Los PIR YA NO se leen desde la Raspberry Pi. Ahora están
#  conectados al Arduino Mega (PIR derecho -> D24, izquierdo -> D22),
#  que reporta la presencia por serial ("PRES:0/1", OR de ambos).
#  Por eso este módulo ya no usa RPi.GPIO: delega en la conexión
#  serial compartida (conexion_arduino.py), su dueño único.
# ============================================================

from .conexion_arduino import iniciar_conexion, hay_presencia


def iniciar_sensores():
    """Asegura que la conexión serial con el Arduino esté abierta.
    Es idempotente: si los motores ya la abrieron, no hace nada."""
    iniciar_conexion()
    print("[SENSORES] Presencia vía PIR del Arduino (serial).")


def detectar_persona() -> bool:
    """Regresa True si alguno de los 2 PIR del Arduino detecta movimiento."""
    return hay_presencia()
