"""
Prueba MANUAL e interactiva de motores y brazos de MEXA (Arduino Mega).

Lee una tecla a la vez (sin Enter) y envía el comando de una letra al
firmware (arduino/mexa/mexa.ino). Un hilo en segundo plano muestra todo
lo que el Arduino responde: 'OK <cmd>', 'PRES:0/1' (PIR) y 'WALL:...'.

SEGURIDAD:
  - ELEVÁ el robot con las ruedas en el aire antes de probar motores,
    así no se desplaza por la mesa.
  - Al salir (q / Ctrl+C / error) el script SIEMPRE manda 'S' (stop) y
    'P' (brazos a reposo) antes de cerrar.

Ejecutar desde la raíz del proyecto:  python3 tests/test_manual_arduino.py
Usa el puerto definido en modulos/config.py (ARDUINO_PUERTO).
"""

import os
import sys
import time
import threading

# Permite importar el paquete `modulos` al correr este test desde tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import serial  # pyserial
from modulos.config import ARDUINO_PUERTO, ARDUINO_BAUDRATE

# tecla -> (comando_firmware, descripción)
_COMANDOS = {
    "f": ("F", "Adelante (ambos lados +)"),
    "b": ("B", "Atrás (ambos lados -)"),
    "r": ("R", "Giro a la DERECHA (con evasión de pared)"),
    "l": ("L", "Giro a la IZQUIERDA (con evasión de pared)"),
    "s": ("S", "STOP (frena todos los motores)"),
    "1": ("1", "Solo Motor 0  — lado IZQUIERDO (pines D2/D3)"),
    "2": ("2", "Solo Motor 1  — lado IZQUIERDO (pines D4/D5)"),
    "3": ("3", "Solo Motor 2  — lado DERECHO  (pines D6/D7)"),
    "4": ("4", "Solo Motor 3  — lado DERECHO  (pines D8/D9)"),
    "h": ("H", "Brazos: animar (gesticular)"),
    "p": ("P", "Brazos: reposo"),
}

_seguir = True


def _menu() -> None:
    print("=" * 56)
    print("  MEXA — Prueba manual de motores y brazos")
    print("=" * 56)
    print("  CONDUCIR        IDENTIFICAR MOTOR     BRAZOS")
    print("   f  adelante      1  Motor0 (IZQ)      h  animar")
    print("   b  atras         2  Motor1 (IZQ)      p  reposo")
    print("   r  giro DER      3  Motor2 (DER)")
    print("   l  giro IZQ      4  Motor3 (DER)")
    print("   s  STOP")
    print("-" * 56)
    print("   q  salir (manda STOP + reposo automaticamente)")
    print("=" * 56)
    print("  SEGURIDAD: eleva el robot (ruedas en el aire) antes de probar.")
    print("  Tras mover un motor, presiona 's' para frenarlo.")
    print("-" * 56)
    sys.stdout.flush()


def _lector_serial(ser: serial.Serial) -> None:
    """Hilo: imprime todo lo que el Arduino envia (OK / PRES / WALL)."""
    while _seguir:
        try:
            linea = ser.readline().decode(errors="ignore").strip()
        except Exception:
            break
        if linea:
            print(f"    << {linea}")
            sys.stdout.flush()


def _leer_tecla():
    """Lee UNA tecla sin esperar Enter (modo cbreak). Ctrl+C sigue activo."""
    import termios
    import tty
    fd = sys.stdin.fileno()
    viejo = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, viejo)


def main() -> None:
    global _seguir

    print(f"[TEST] Abriendo {ARDUINO_PUERTO} a {ARDUINO_BAUDRATE} baud...")
    try:
        ser = serial.Serial(ARDUINO_PUERTO, ARDUINO_BAUDRATE, timeout=1)
    except Exception as e:
        print(f"[TEST] No se pudo abrir el puerto ({e}). ¿Arduino conectado?")
        return
    time.sleep(2)  # el Mega se reinicia al abrir el puerto
    print(f"[TEST] Conectado.\n")

    hilo = threading.Thread(target=_lector_serial, args=(ser,), daemon=True)
    hilo.start()

    _menu()

    if not sys.stdin.isatty():
        print("[TEST] Sin terminal interactiva; no puedo leer teclas. Aborto.")
        ser.close()
        return

    try:
        while True:
            tecla = _leer_tecla().lower()
            if tecla == "q":
                break
            if tecla in _COMANDOS:
                cmd, desc = _COMANDOS[tecla]
                ser.write((cmd + "\n").encode())
                print(f"  >> {cmd}  ({desc})")
                sys.stdout.flush()
            elif tecla in ("\n", "\r", " "):
                continue
            else:
                print(f"  (tecla '{tecla}' sin asignar — usa el menu)")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n[TEST] Ctrl+C detectado.")
    finally:
        # Seguridad: frenar motores y bajar brazos pase lo que pase.
        try:
            ser.write(b"S\n")
            ser.write(b"P\n")
            time.sleep(0.3)
        except Exception:
            pass
        _seguir = False
        time.sleep(0.2)
        ser.close()
        print("[TEST] STOP + reposo enviados. Puerto cerrado. Fin.")


if __name__ == "__main__":
    main()
