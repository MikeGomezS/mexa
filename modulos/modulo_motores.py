# ============================================================
#  MEXA — Módulo 05: Control de Motores DC
#  Hardware: 2x Motor DC + puente H MX1508/TC1508A + Arduino (USB Serial)
#
#  CONEXIONES ARDUINO → puente H (ver arduino/mexa/mexa.ino):
#    Motor Izquierdo  IN1 → D4    IN2 → D5
#    Motor Derecho    IN3 → D6    IN4 → D7
#
#  PROTOCOLO SERIAL (manejado por el firmware unificado):
#    F → adelante   B → atrás   R → girar derecha   L → girar izquierda   S → stop
#
#  NOTA: la conexión serial es COMPARTIDA con los brazos
#  (un solo Arduino). El transporte vive en conexion_arduino.py.
# ============================================================

import time

from .conexion_arduino import iniciar_conexion, enviar


def iniciar_motores():
    """Abre (o reutiliza) la conexión serial compartida con el Arduino."""
    iniciar_conexion()


def mover_adelante(velocidad=None):
    enviar("F")

def mover_atras(velocidad=None):
    enviar("B")

def girar_derecha(velocidad=None):
    enviar("R")

def girar_izquierda(velocidad=None):
    enviar("L")

def detener():
    enviar("S")


def mover_por_tiempo(direccion="adelante", segundos=1.0, velocidad=None):
    if direccion == "adelante":
        mover_adelante()
    elif direccion == "atras":
        mover_atras()
    elif direccion == "derecha":
        girar_derecha()
    elif direccion == "izquierda":
        girar_izquierda()
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
