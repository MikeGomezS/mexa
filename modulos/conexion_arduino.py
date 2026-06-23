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

from .config import ARDUINO_PUERTO, ARDUINO_BAUDRATE

_serial = None
_rx_buffer = ""          # acumula bytes hasta tener líneas completas
_presencia = False       # último estado de presencia reportado por el Arduino
_observador = None       # callback(cmd) opcional: ve cada comando enviado
                         # (lo usa registro_camino para anotar el recorrido)


def set_observador(fn):
    """Registra (o limpia con None) un observador que recibe CADA comando
    enviado al Arduino. Es el gancho que usa RegistroCamino para anotar el
    camino sin acoplar la capa serial a la lógica de motores."""
    global _observador
    _observador = fn


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
    if _observador is not None:
        # Anota la INTENCIÓN de movimiento con su timestamp, aunque el
        # serial esté caído: el camino y su inverso quedan consistentes.
        _observador(cmd)
    if _serial and _serial.is_open:
        try:
            _serial.write((cmd + "\n").encode())
        except Exception as e:
            print(f"[ARDUINO] Error enviando '{cmd}': {e}")


def _bombear():
    """Lee SIN bloquear todo lo que el Arduino haya enviado y actualiza
    el estado compartido. El Arduino manda líneas terminadas en '\\n':
    'PRES:0/1' (presencia de los PIR), 'WALL:I/D' (evasión) y 'OK <cmd>'.
    Aquí solo nos interesa la presencia; el resto se ignora."""
    global _rx_buffer, _presencia
    if not (_serial and _serial.is_open):
        return
    try:
        n = _serial.in_waiting
        if not n:
            return
        _rx_buffer += _serial.read(n).decode(errors="ignore")
    except Exception as e:
        print(f"[ARDUINO] Error leyendo: {e}")
        return

    partes = _rx_buffer.split("\n")
    _rx_buffer = partes.pop()          # lo último puede ser una línea incompleta
    for linea in partes:
        linea = linea.strip()
        if linea.startswith("PRES:"):
            _presencia = linea.endswith("1")


def hay_presencia() -> bool:
    """Procesa lo recibido del Arduino y devuelve el último estado de
    presencia conocido (lo determinan los 2 PIR conectados al Arduino)."""
    _bombear()
    return _presencia


def cerrar_conexion():
    """Cierra el puerto serial compartido. Llamar UNA sola vez al apagar."""
    global _serial
    if _serial and _serial.is_open:
        _serial.close()
        print("[ARDUINO] Desconectado.")
    _serial = None
