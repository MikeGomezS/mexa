"""
Diagnóstico de la CADENA DE MANDO de los motores de MEXA.

No intenta mover: verifica DÓNDE se corta la orden cuando MEXA "no avanza y
hay silencio". Abre el serial, escucha el banner de arranque del firmware,
manda 'F' y muestra TODO lo que el Arduino responde, luego 'S'.

Qué mirar:
  - Banner "MEXA firmware listo: ..."  -> el firmware correcto está corriendo.
  - "OK F" tras mandar F               -> el firmware RECIBE y PROCESA el comando.
    Si además el LED de la placa (pin 13) enciende, la lógica está 100% sana
    y el problema es de POTENCIA/cableado de motores (aguas abajo del Arduino).
  - SIN banner / SIN "OK F"            -> el comando NO llega al firmware:
    serial, sketch equivocado o Arduino colgado.

USO (MEXA con todo conectado; mirá el LED chico de la placa Arduino):
  python3 tests/diagnostico_motores.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial
from modulos.config import ARDUINO_PUERTO, ARDUINO_BAUDRATE


def _volcar(ser, etiqueta, segundos):
    """Lee y muestra todo lo que el Arduino envíe durante 'segundos'."""
    fin = time.time() + segundos
    recibido = False
    while time.time() < fin:
        n = ser.in_waiting
        if n:
            datos = ser.read(n).decode(errors="ignore")
            for linea in datos.splitlines():
                linea = linea.strip()
                if linea:
                    print(f"[ARDUINO<-] {etiqueta}: {linea!r}")
                    recibido = True
        time.sleep(0.05)
    if not recibido:
        print(f"[ARDUINO<-] {etiqueta}: (nada)")


def main() -> None:
    print(f"[DIAG] Abriendo {ARDUINO_PUERTO} @ {ARDUINO_BAUDRATE}...")
    ser = serial.Serial(ARDUINO_PUERTO, ARDUINO_BAUDRATE, timeout=1)
    try:
        print("[DIAG] Esperando reinicio del Arduino + banner de arranque (3s)...")
        _volcar(ser, "arranque", 3.0)

        print("\n[DIAG] >>> Envío 'F' (adelante). Mirá el LED de la placa (pin 13).")
        ser.write(b"F\n")
        _volcar(ser, "tras F", 2.0)

        print("\n[DIAG] >>> Envío 'S' (stop).")
        ser.write(b"S\n")
        _volcar(ser, "tras S", 1.0)
    except KeyboardInterrupt:
        ser.write(b"S\n")
        print("\n[DIAG] Ctrl+C — STOP enviado.")
    finally:
        ser.close()
        print("[DIAG] Puerto cerrado. Fin.")


if __name__ == "__main__":
    main()
