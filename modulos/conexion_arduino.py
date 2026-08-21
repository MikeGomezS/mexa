# ============================================================
#  MEXA — Conexión serial compartida con el Arduino
#
#  UN solo Arduino controla brazos + motores, así que hay UN
#  solo puerto serial. Este módulo es el ÚNICO dueño de esa
#  conexión: modulo_brazos y modulo_motores envían a través de
#  él. Así evitamos abrir el mismo puerto dos veces ("device
#  busy") y mantenemos una sola fuente de verdad del transporte.
#
#  El canal es de IDA Y VUELTA: el Arduino también informa lo que
#  sienten sus sensores. Este módulo es el TRANSPORTE (lee bytes,
#  arma líneas); traducir e interpretar esas líneas es tarea de
#  telemetria.py, que no toca hardware y por eso se testea sola.
# ============================================================

import time
import serial

from .config import ARDUINO_PUERTO, ARDUINO_BAUDRATE
from .telemetria import EstadoFrente, interpretar_linea

_serial = None
_rx_buffer = ""          # acumula bytes hasta tener líneas completas
_presencia = False       # último estado de presencia reportado por el Arduino
_frente = EstadoFrente() # distancia frontal + freno reflejo (ultrasónicos)
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
    'PRES:0/1' (presencia), 'DIST:<izq>,<der>' (ultrasónicos frontales),
    'STOP:<cm>' (frenó solo), 'WALL:I/D' (pared) y 'OK <cmd>' (eco).

    Cada llamada VACÍA el buffer de entrada, así que hay que bombear
    seguido: si el serial se llena, el Arduino se bloquea escribiendo."""
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

    ahora = time.monotonic()
    partes = _rx_buffer.split("\n")
    _rx_buffer = partes.pop()          # lo último puede ser una línea incompleta
    for linea in partes:
        evento = interpretar_linea(linea)
        if not evento:
            continue
        if evento[0] == "presencia":
            _presencia = evento[1]
        else:
            _frente.anotar(evento, ahora)


def hay_presencia() -> bool:
    """Procesa lo recibido del Arduino y devuelve el último estado de
    presencia conocido (lo determinan los 2 PIR conectados al Arduino)."""
    _bombear()
    return _presencia


def distancia_frontal_cm():
    """cm hasta lo más cercano que ven los ultrasónicos FRONTALES, o None
    si no hay lectura fresca.

    None es "NO SÉ", no "no hay nadie": el Arduino sólo mide mientras MEXA
    AVANZA, así que quieto siempre da None. Si los sensores frontales no
    están conectados, esto devuelve None SIEMPRE y MEXA se comporta igual
    que antes (se guía por la cámara). Esa es la degradación buscada:
    ningún sensor ausente puede empeorar lo que ya funcionaba.

    999.0 (telemetria.SIN_ECO_CM) sí es un dato: "nadie dentro del alcance"."""
    _bombear()
    return _frente.distancia_cm(time.monotonic())


def freno_por_persona():
    """cm a los que el Arduino frenó SOLO por tener a alguien demasiado
    cerca al frente, o None si no frenó desde el último avance.

    Es un REFLEJO ya ejecutado: cuando esto devuelve un número, los motores
    YA están parados. La Pi no lo previene, se entera — y debe mandar 'S'
    para que su propio estado (y el registro del camino) coincida con la
    realidad del robot."""
    _bombear()
    return _frente.freno_cm()


def reiniciar_frente():
    """Olvida las lecturas frontales. Se llama al arrancar CADA avance, en
    espejo con `reiniciarFrente()` del firmware: la distancia de la maniobra
    anterior no dice nada de ésta."""
    _frente.reiniciar()


def cerrar_conexion():
    """Cierra el puerto serial compartido. Llamar UNA sola vez al apagar."""
    global _serial
    if _serial and _serial.is_open:
        _serial.close()
        print("[ARDUINO] Desconectado.")
    _serial = None
