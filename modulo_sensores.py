# ============================================================
#  MEXA — Módulo 04: Sensores PIR + Ultrasónico HC-SR04
#  Hardware: PIR HC-SR501 + Sensor HC-SR04
#  Librería: RPi.GPIO
#  Instalar: sudo apt install python3-rpi.gpio -y
#
#  CONEXIONES:
#  PIR HC-SR501:
#    VCC  → Pin 2  (5V)
#    GND  → Pin 6  (GND)
#    OUT  → GPIO 17 (Pin 11)
#
#  HC-SR04:
#    VCC  → Pin 2  (5V)
#    GND  → Pin 6  (GND)
#    TRIG → GPIO 23 (Pin 16)
#    ECHO → GPIO 24 (Pin 18)  ⚠ IMPORTANTE: agregar divisor de voltaje
#           El ECHO da 5V pero la Pi solo acepta 3.3V en GPIO.
#           Solución simple: resistencia 1kΩ entre ECHO y GPIO,
#           y resistencia 2kΩ entre GPIO y GND.
# ============================================================

import RPi.GPIO as GPIO
import time

from config import PIR_PIN, TRIG_PIN, ECHO_PIN

def iniciar_sensores():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(PIR_PIN,  GPIO.IN)
    GPIO.setup(TRIG_PIN, GPIO.OUT)
    GPIO.setup(ECHO_PIN, GPIO.IN)
    GPIO.output(TRIG_PIN, False)
    time.sleep(0.5)
    print("[SENSORES] Inicializados correctamente.")

def detectar_persona() -> bool:
    """Regresa True si el PIR detecta movimiento (alguien cerca)."""
    return GPIO.input(PIR_PIN) == GPIO.HIGH

def medir_distancia_cm() -> float:
    """
    Mide la distancia en centímetros con el HC-SR04.
    Rango útil: 2cm - 400cm
    """
    # Enviar pulso
    GPIO.output(TRIG_PIN, True)
    time.sleep(0.00001)
    GPIO.output(TRIG_PIN, False)

    # Esperar respuesta
    inicio = time.time()
    fin    = time.time()

    timeout = time.time() + 0.1  # 100ms máximo
    while GPIO.input(ECHO_PIN) == 0:
        inicio = time.time()
        if time.time() > timeout:
            return 999.0  # error / fuera de rango

    timeout = time.time() + 0.1
    while GPIO.input(ECHO_PIN) == 1:
        fin = time.time()
        if time.time() > timeout:
            return 999.0

    distancia = (fin - inicio) * 17150
    return round(distancia, 1)

def hay_obstaculo(limite_cm=20) -> bool:
    """Regresa True si hay algo a menos de limite_cm de distancia."""
    return medir_distancia_cm() < limite_cm
