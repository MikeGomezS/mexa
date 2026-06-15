# ============================================================
#  MEXA — Conexión serial compartida con el Arduino
#
#  UN solo Arduino controla brazos + motores, así que hay UN
#  solo puerto serial. Este módulo es el ÚNICO dueño de esa
#  conexión: modulo_brazos y modulo_motores envían a través de
#  él. Así evitamos abrir el mismo puerto dos veces ("device
#  busy") y mantenemos una sola fuente de verdad del transporte.
# ============================================================

import time
import serial

from config import ARDUINO_PUERTO, ARDUINO_BAUDRATE

_serial = None


def iniciar_conexion():
    """Abre el puerto serial una sola vez. Idempotente: si ya está
    abierto, no hace nada y devuelve la conexión existente."""
    global _serial
    if _serial and _serial.is_open:
        return _serial
    try:
        _serial = serial.Serial(ARDUINO_PUERTO, ARDUINO_BAUDRATE, timeout=1)
        time.sleep(2)  # el Arduino se reinicia al abrir el puerto serial
        print(f"[ARDUINO] Conectado en {ARDUINO_PUERTO} a {ARDUINO_BAUDRATE} baud.")
    except Exception as e:
        print(f"[ARDUINO] No se pudo conectar ({e}). Brazos y motores quedarán inactivos.")
        _serial = None
    return _serial


def enviar(cmd: str):
    """Envía un comando de una letra al Arduino (agrega '\\n')."""
    if _serial and _serial.is_open:
        try:
            _serial.write((cmd + "\n").encode())
        except Exception as e:
            print(f"[ARDUINO] Error enviando '{cmd}': {e}")


def cerrar_conexion():
    """Cierra el puerto serial compartido. Llamar UNA sola vez al apagar."""
    global _serial
    if _serial and _serial.is_open:
        _serial.close()
        print("[ARDUINO] Desconectado.")
    _serial = None
