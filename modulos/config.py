# ============================================================
#  MEXA — Configuración central de pines GPIO y constantes
#  Cambiar un pin aquí lo actualiza en todos los módulos.
# ============================================================

# Sensores
# Presencia (2x PIR) y ultrasónicos viven en el Arduino Mega, no en la Pi.
# Sus pines se definen en arduino/mexa/mexa.ino. No hay pines de sensor aquí.

# Motores (Puente H MX1508)
IN1, IN2 = 5,  6   # Motor Izquierdo
IN3, IN4 = 13, 19  # Motor Derecho

# Encoders
ENC_IZQ = 26
ENC_DER = 20

# Ventiladores
FAN_PIN = 21

# Arduino (UN solo Arduino via USB Serial — controla brazos + motores)
ARDUINO_PUERTO   = "/dev/ttyUSB0"  # usar /dev/ttyACM0 si es Arduino Uno/Mega original
ARDUINO_BAUDRATE = 9600

# Aliases retrocompatibles (apuntan al mismo Arduino)
BRAZOS_PUERTO    = ARDUINO_PUERTO
BRAZOS_BAUDRATE  = ARDUINO_BAUDRATE
MOTORES_PUERTO   = ARDUINO_PUERTO
MOTORES_BAUDRATE = ARDUINO_BAUDRATE

# Umbrales de temperatura
TEMP_FAN_ON  = 60.0  # °C — encender ventiladores
TEMP_FAN_OFF = 50.0  # °C — apagar ventiladores
