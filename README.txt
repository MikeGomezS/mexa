# MEXA — Instrucciones de instalación y uso
# WRO Future Innovators 2026

## Estructura de archivos
```
mexa/
├── main.py
├── modulo_audio.py
├── modulo_ia.py
├── modulo_tts.py
├── modulo_sensores.py
├── modulo_motores.py
├── modulo_camara.py
├── modulo_proyector.py
├── modulo_ventiladores.py
├── requirements.txt
├── README.txt
└── media/
    └── imagenes/
        (agregar aquí imágenes JPG de sitios culturales)
```

## Paso 1 — Actualizar la Raspberry Pi
```
sudo apt update && sudo apt upgrade -y
```

## Paso 2 — Instalar dependencias del sistema
```
sudo apt install python3-rpi.gpio espeak vlc python3-picamera2 -y
```

## Paso 3 — Instalar librerías de Python
```
pip install -r requirements.txt
```

## Paso 4 — Instalar Ollama (motor de IA local)
```
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

## Paso 5 — Crear carpeta de imágenes
```
mkdir -p media/imagenes
```
Agregar imágenes JPG con estos nombres exactos:
- bienvenida.jpg
- teotihuacan.jpg
- azteca.jpg
- maya.jpg
- independencia.jpg
- revolucion.jpg
- olmeca.jpg
- mexico_general.jpg

## Paso 6 — Ejecutar MEXA
```
python3 main.py
```
Para detener: presionar Ctrl+C

## Pines GPIO usados
- GPIO 17  → Sensor PIR (detección de personas)
- GPIO 23  → HC-SR04 TRIG
- GPIO 24  → HC-SR04 ECHO
- GPIO 5   → Motor Izquierdo IN1
- GPIO 6   → Motor Izquierdo IN2
- GPIO 13  → Motor Derecho IN3
- GPIO 19  → Motor Derecho IN4
- GPIO 26  → Encoder Motor Izquierdo
- GPIO 20  → Encoder Motor Derecho
- GPIO 21  → Control transistor ventiladores
- CSI      → Cámara Arducam Módulo 3
- USB      → Micrófono USB 360°
- micro-HDMI 1 → Proyector KACOTA HY300 Pro
