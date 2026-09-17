# ============================================================
#  MEXA — Configuración del enlace con el Arduino
#
#  MEXA NO USA NINGÚN GPIO DE LA RASPBERRY. Motores, brazos, PIR
#  y ultrasónicos cuelgan TODOS del Arduino Mega 2560 y se hablan
#  por USB serial. Los pines de cada uno viven en
#  arduino/mexa/mexa.ino, su única fuente de verdad.
#
#  QUÉ HABÍA ACÁ Y POR QUÉ SE FUE (2026-09-17): este archivo
#  conservaba `IN1..IN4` (pines de motor en la Pi), `ENC_IZQ`,
#  `ENC_DER`, `FAN_PIN`, `TEMP_FAN_ON/OFF` y cuatro alias de
#  puerto. Sobrevivientes de la arquitectura vieja, cuando todo
#  colgaba de la Pi. NADIE los importaba — eran documentación
#  falsa con forma de código, que es la peor clase: el lector
#  supone que si está en config.py, algo lo usa.
#
#  Los encoders además nunca existieron: no hay pines de encoder
#  en el firmware ni lectura en ningún lado. MEXA no tiene
#  odometría. El regreso se calcula POR TIEMPO
#  (modulo_motores.PULSO_GIRO_S), y eso limita su precisión.
#
#  Si algún día algo vuelve a colgarse de la Pi, vuelve acá.
# ============================================================

# UN solo Arduino por USB serial: motores + brazos + sensores.
ARDUINO_PUERTO   = "/dev/ttyACM0"  # Mega 2560 R3 original (CDC ACM); usar /dev/ttyUSB0 si es clon CH340
ARDUINO_BAUDRATE = 9600
