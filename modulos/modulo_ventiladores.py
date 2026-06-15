# ============================================================
#  MEXA — Módulo 08: Control de Ventiladores (Enfriamiento)
#  Hardware: 4x WINSINN 5015 12V DC
#  Librería: RPi.GPIO, subprocess
#
#  CONEXIONES:
#    Ventiladores VCC (cable rojo)  → 12V (fuente AC-DC 12V 3A)
#    Ventiladores GND (cable negro) → GND de la fuente 12V
#                                     Y GND común con la Pi
#
#  CONTROL ON/OFF (opcional pero recomendado):
#    Transistor NPN BC547 (o similar):
#      Base       → Resistencia 1kΩ → GPIO 21 (Pin 40)
#      Colector   → GND de los ventiladores
#      Emisor     → GND común
#    Con esto la Raspberry Pi puede encender/apagar los ventiladores
#    según la temperatura, sin arriesgar los pines GPIO con 12V.
#
#  OPCIÓN SIMPLE (demo):
#    Si no quieren usar transistor, simplemente conecten los
#    ventiladores directo a la fuente 12V y siempre estarán encendidos.
# ============================================================

import RPi.GPIO as GPIO
import subprocess

from .config import FAN_PIN, TEMP_FAN_ON, TEMP_FAN_OFF

TEMP_ON  = TEMP_FAN_ON
TEMP_OFF = TEMP_FAN_OFF

_ventiladores_encendidos = False
_modo_siempre_on = False

def iniciar_ventiladores():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(FAN_PIN, GPIO.OUT)
    GPIO.output(FAN_PIN, GPIO.LOW)
    print("[VENTILADORES] Módulo inicializado.")

def encender():
    global _ventiladores_encendidos
    GPIO.output(FAN_PIN, GPIO.HIGH)
    _ventiladores_encendidos = True
    print("[VENTILADORES] Encendidos.")

def apagar():
    global _ventiladores_encendidos
    GPIO.output(FAN_PIN, GPIO.LOW)
    _ventiladores_encendidos = False
    print("[VENTILADORES] Apagados.")

def obtener_temperatura() -> float:
    """Lee la temperatura actual de la CPU de la Raspberry Pi."""
    try:
        output = subprocess.check_output(
            ["vcgencmd", "measure_temp"]
        ).decode().strip()
        # output = "temp=55.0'C"
        temp = float(output.replace("temp=", "").replace("'C", ""))
        return temp
    except Exception:
        return 0.0

def controlar_por_temperatura():
    """
    Enciende o apaga los ventiladores según la temperatura.
    Si el modo siempre-ON está activo, nunca los apaga.
    """
    temp = obtener_temperatura()
    print(f"[VENTILADORES] Temperatura CPU: {temp}°C")
    if _modo_siempre_on:
        if not _ventiladores_encendidos:
            encender()
        return temp
    if temp >= TEMP_ON and not _ventiladores_encendidos:
        encender()
    elif temp <= TEMP_OFF and _ventiladores_encendidos:
        apagar()
    return temp

def encender_siempre():
    """Para el demo: encender y marcar modo siempre-ON para que
    controlar_por_temperatura() no los apague."""
    global _modo_siempre_on
    _modo_siempre_on = True
    encender()
    print("[VENTILADORES] Modo SIEMPRE ENCENDIDO activado.")
