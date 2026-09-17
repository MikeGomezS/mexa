# MEXA — Instrucciones de instalación y uso
# WRO Future Innovators 2026
#
# REGLA DE ESTE ARCHIVO: acá no se escribe nada que el código no
# respalde. Si una versión futura del código cambia un modelo, un
# binario o una carpeta, ESTE archivo se corrige en el mismo commit.
# Una instrucción desactualizada no es documentación incompleta: es
# una trampa, porque el lector la sigue creyendo que es verdad.

## Estructura del proyecto
```
mexa/
├── main.py                  orquestador: inicia, coordina y apaga
├── arduino/mexa/mexa.ino    firmware: motores, brazos, PIR, ultrasónicos
├── config/pipewire/         configuración del cancelador de eco (AEC)
├── docs/                    informes de hardware (fuente .html + .pdf)
├── modulos/
│   ├── conexion_arduino.py  dueño único del puerto serial
│   ├── telemetria.py        traduce lo que informa el Arduino (lógica pura)
│   ├── modulo_motores.py    comandos de movimiento
│   ├── modulo_brazos.py     gesto de los brazos
│   ├── modulo_sensores.py   presencia (PIR, vía Arduino)
│   ├── navegacion.py        acercarse al visitante y volver
│   ├── registro_camino.py   anota el recorrido para deshacerlo
│   ├── modulo_camara.py     captura + detección de caras (YuNet)
│   ├── modulo_audio.py      reconocimiento de voz (Vosk)
│   ├── vad.py               cuándo empieza y termina de hablar (Silero)
│   ├── captura.py           micrófono vía PipeWire + AEC
│   ├── modulo_tts.py        voz (Piper, con espeak-ng de respaldo)
│   ├── modulo_ia.py         respuestas (Ollama, local)
│   ├── conocimiento.py      hechos que la IA puede usar
│   ├── contenido.py         qué civilizaciones ofrece y qué dice
│   ├── dialogo.py           la conversación
│   ├── modulo_proyector.py  video y cara animada por HDMI
│   ├── _cara_animada.py     dibujo de la cara
│   └── config.py            puerto y baudrate del Arduino
├── tests/                   pruebas y calibraciones
├── requirements.txt
└── media/                   NO versionado: se descarga o se copia aparte
    ├── tts/                 voces de Piper (.onnx + .onnx.json)
    ├── vad/silero_vad.onnx
    └── videos/{español,ingles}/
```

## Paso 1 — Actualizar la Raspberry Pi
```
sudo apt update && sudo apt upgrade -y
```

## Paso 2 — Instalar dependencias del sistema
```
sudo apt install espeak-ng vlc python3-picamera2 pipewire-bin -y
```
Los cuatro son obligatorios y ninguno lo instala pip:
- `espeak-ng` — voz de respaldo. El código llama al binario `espeak-ng`,
  NO a `espeak`: son dos paquetes distintos y el viejo no sirve.
- `vlc` — trae `cvlc`, que reproduce el audio de los videos.
- `python3-picamera2` — cámara CSI.
- `pipewire-bin` — trae `pw-record` y `pw-play`. Sin eso MEXA se queda
  sorda y muda, y `pip install -r` no lo avisa.

MEXA no necesita `python3-rpi.gpio`: no usa un solo GPIO de la Pi.

## Paso 3 — Instalar librerías de Python
```
pip install -r requirements.txt
```

## Paso 4 — Instalar Ollama y el modelo de IA
```
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:1b
```
Es `1b`, no `3b`. El modelo está escrito en `modulos/modulo_ia.py`; si se
descarga otro, Ollama responde que no existe y MEXA se queda sin IA.

## Paso 5 — Descargar las voces de Piper
Sin esto MEXA no tiene voz neural y cae siempre a `espeak-ng`.
Cada voz son DOS archivos: el modelo y su .json al lado. Los cuatro nombres
son exactos — los lee `modulos/modulo_tts.py`.
```
mkdir -p media/tts
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main
for f in es/es_MX/claude/high/es_MX-claude-high.onnx \
         es/es_MX/claude/high/es_MX-claude-high.onnx.json \
         en/en_US/lessac/high/en_US-lessac-high.onnx \
         en/en_US/lessac/high/en_US-lessac-high.onnx.json; do
  curl -L -o "media/tts/$(basename $f)" "$BASE/$f"
done
```
Son ~177 MB entre las dos.

## Paso 6 — Descargar los modelos de voz (Vosk)
Desde https://alphacephei.com/vosk/models, descomprimir en la raíz del
proyecto con estos nombres exactos:
```
vosk-model-small-es-0.42     -> modelo_vosk_es/
vosk-model-small-en-us-0.15  -> modelo_vosk_en/
```
Sin el de inglés MEXA sigue arrancando, pero escucha todo con oído
español (ver `modulos/modulo_audio.py`).

## Paso 7 — Descargar el modelo de VAD (Silero)
El VAD decide cuándo el visitante empezó y terminó de hablar. Sin este
archivo MEXA sigue funcionando, pero degrada al VAD de energía, que es
peor con ruido de sala (lo avisa por consola al arrancar).
```
mkdir -p media/vad
curl -L -o media/vad/silero_vad.onnx \
  https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx
```
Son 2.3 MB y corre en CPU (0.26 ms por ventana de 32 ms en la Pi 5).

## Paso 8 — Instalar el cancelador de eco (AEC)
Sin esto MEXA se oye a sí misma y no se la puede interrumpir mientras
habla. El archivo versionado es la copia autoritativa; PipeWire lee la
copia del home:
```
mkdir -p ~/.config/pipewire/pipewire.conf.d
cp config/pipewire/99-mexa-aec.conf ~/.config/pipewire/pipewire.conf.d/
systemctl --user restart pipewire
```
Leer los comentarios de ese archivo antes de tocarlo: documenta dos
formas de romperse EN SILENCIO ya vistas en hardware.

## Paso 9 — Colocar los videos de las civilizaciones
```
mkdir -p media/videos/español media/videos/ingles
```
Un video por civilización y por idioma, con estos nombres exactos:
```
media/videos/español/{Nombre}_esp.mp4
media/videos/ingles/{Nombre}_eng.mp4
```
Nombres: Mayas, Aztecas, Teotihuacan, Olmecas, Toltecas, Zapotecas, Mixtecas.

La lista que MEXA realmente ofrece vive en `modulos/contenido.py`
(`CIVILIZACIONES` y `NOMBRES_DISPONIBLES`); un video en disco que no esté ahí
no se ofrece nunca. Antes de sumar una civilización, verificá que Vosk pueda
oír su nombre con `python3 tests/calibrar_vocabulario.py auditar`.

MEXA no usa imágenes fijas. Mientras habla, el proyector muestra su cara
animada (`modulos/_cara_animada.py`); ver el comentario en
`modulos/modulo_proyector.py` sobre por qué se quitaron.

## Paso 10 — Cargar el firmware en el Arduino
Abrir `arduino/mexa/mexa.ino` en el Arduino IDE, elegir placa
"Arduino Mega or Mega 2560" y subirlo. Al arrancar, el Arduino imprime por
serial:
```
MEXA firmware listo: 4 motores + 2 brazos + 2 PIR + 4 ultrasonicos
```
Si ese banner no aparece, el firmware cargado no es éste.

## Paso 11 — Ejecutar MEXA
```
python3 main.py
```
MEXA arranca dormida y despierta cuando alguien dice "comencemos".
Para detener: presionar Ctrl+C

## Conexiones de hardware

### Todo lo que se mueve o mide proximidad va al Arduino
Motores, brazos, PIR y ultrasónicos cuelgan del Arduino Mega 2560, NO de
los GPIO de la Raspberry. La fuente de verdad de cada pin es el propio
firmware: `arduino/mexa/mexa.ino`.

Resumen (21 pines en uso):
```
D2-D3    Motor 0  ┐ lado IZQUIERDO      D22   PIR izquierdo
D4-D5    Motor 1  ┘                     D24   PIR derecho
D6-D7    Motor 2  ┐ lado DERECHO        D29/D28  ultrasónico lateral derecho   (TRIG/ECHO)
D8-D9    Motor 3  ┘ (espejo, invertido) D31/D30  ultrasónico lateral izquierdo (TRIG/ECHO)
D10      Servo brazo derecho            D53/D52  ultrasónico frontal derecho   (TRIG/ECHO)
D11      Servo brazo izquierdo          D51/D50  ultrasónico frontal izquierdo (TRIG/ECHO)
D13      LED de la placa = motor activo
```
Alimentación: VM del driver al + de la pila; GND del driver al - de la pila
Y TAMBIÉN al GND del Arduino (tierra común).

El detalle completo — protocolo serial, umbrales, reflejos de freno y
diagnóstico — está en `docs/informe_conexiones_arduino.pdf`. Se regenera desde
`docs/informe_conexiones_arduino.html`; ver `docs/README.txt`.

### Lo que va directo a la Raspberry Pi
```
CSI            Cámara Arducam Módulo 3 (IMX708)
USB            Arduino Mega 2560 (/dev/ttyACM0)
USB            Micrófono (MONO de 1 canal: no hay dirección de llegada
               del sonido; ver modulos/vad.py y tests/test_seleccion_objetivo.py)
micro-HDMI 1   Proyector KACOTA HY300 Pro
```

MEXA NO TIENE ENCODERS. No hay odometría: el regreso al punto de partida se
calcula por TIEMPO (`modulo_motores.PULSO_GIRO_S`), no por vueltas de rueda.
Eso limita su precisión y hay que tenerlo presente al calibrar.

## Verificar el hardware
```
python3 tests/diagnostico_motores.py            ¿llega la orden al firmware?
python3 tests/test_manual_arduino.py            prueba interactiva tecla por tecla
python3 tests/probar_ultrasonicos_frontales.py  ¿miden los frontales?
python3 tests/calibrar_pulsos.py giro           ajustar PULSO_GIRO_S
```
SEGURIDAD: elevá el robot con las ruedas en el aire antes de probar motores.
