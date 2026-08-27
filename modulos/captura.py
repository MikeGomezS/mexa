# ============================================================
#  MEXA — Captura de audio POR PIPEWIRE
#
#  POR QUÉ EXISTE ESTE MÓDULO. MEXA tenía un pie adentro y otro
#  afuera del servidor de sonido: la salida (pw-play del TTS, cvlc
#  del video) iba por PipeWire, pero la entrada la abría PyAudio
#  directo contra ALSA. PipeWire nunca veía el micrófono, así que
#  no podía restarle nada, y por eso MEXA tenía que taparse los
#  oídos mientras hablaba: nadie podía interrumpirla.
#
#  Leyendo el micrófono desde PipeWire, el cancelador de eco
#  (config/pipewire/99-mexa-aec.conf) puede restar lo que MEXA
#  misma está diciendo antes de que llegue a Vosk.
#
#  POR QUÉ pw-record Y NO EL PLUGIN ALSA DE PIPEWIRE: instalar
#  pipewire-alsa cambia el ruteo de audio de TODAS las apps de la
#  Pi, y deja a PortAudio como una capa inútil por encima de
#  PipeWire. Acá se saca la capa: una dependencia menos y los dos
#  lados del audio en el mismo servidor.
#
#  LO QUE CAMBIA AL PASAR A UN PIPE. PyAudio entregaba bloques
#  completos; un pipe no garantiza nada de eso. Los tres supuestos
#  que hay que sostener a mano están en tests/test_captura.py.
# ============================================================

import os
import subprocess

# El micrófono SIN eco que publica el módulo echo-cancel, y el micrófono
# crudo por si el cancelador no está cargado. Estos nombres son la única
# fuente de verdad: tests/calibrar_aec.py los importa de acá.
NODO_AEC   = "mexa_aec_source"
NODO_CRUDO = "alsa_input.usb-Clip-on_USB_microphone_iTalk-02-00.mono-fallback"

# 16 kHz mono s16: exactamente lo que necesitan Vosk y Silero. Se le pide
# a PipeWire directamente en vez de remuestrear después con audioop —
# PipeWire resamplea mejor, y de paso desaparece un paso del camino.
RATE  = 16000
ANCHO = 2

# Tope de seguridad al descartar: 4 MB son ~128 s de audio, mucho más de
# lo que puede acumularse en el pipe. Existe para que un productor
# enloquecido no deje el descarte girando para siempre.
_DESCARTE_MAX = 4 * 1024 * 1024


def nodo_existe(nombre: str) -> bool:
    """True si PipeWire tiene ese nodo cargado ahora mismo."""
    try:
        salida = subprocess.run(["pw-cli", "ls", "Node"], capture_output=True,
                                text=True, timeout=10).stdout
    except Exception:
        return False
    return f'node.name = "{nombre}"' in salida


def elegir_nodo(existe=None) -> str:
    """El micrófono sin eco si está; el crudo si no.

    Degrada a propósito en vez de fallar: que el cancelador no esté
    cargado significa que MEXA no puede ser interrumpida, no que tenga
    que quedarse sorda. Se avisa por consola, igual que hace vad.py
    cuando le falta el modelo de Silero.
    """
    existe = existe or nodo_existe
    if existe(NODO_AEC):
        return NODO_AEC
    print(f"[AUDIO] El cancelador de eco no está cargado ({NODO_AEC} no "
          f"existe): escucho el micrófono crudo. MEXA no va a poder ser "
          f"interrumpida mientras habla.")
    return NODO_CRUDO


def comando(nodo: str) -> list[str]:
    """El pw-record que alimenta la captura."""
    return ["pw-record", "--target", nodo, "--rate", str(RATE),
            "--channels", "1", "--format", "s16", "--raw", "-"]


class CapturaPipeWire:
    """Micrófono leído de un pw-record, con la interfaz que espera _escuchar().

    Cumple el mismo contrato que el stream de PyAudio al que reemplaza
    —read(frames), is_active(), close()— para que el cambio quede
    contenido acá y no se derrame sobre el VAD ni sobre los tests que ya
    usan esa costura.
    """

    def __init__(self, argv: list[str]):
        # bufsize=0: sin BufferedReader de por medio. Mezclar un lector
        # con buffer y lecturas no bloqueantes deja datos escondidos en
        # el buffer de Python que el descarte nunca ve.
        self._proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, bufsize=0)
        self._fd = self._proc.stdout.fileno()

    def read(self, n_frames: int, exception_on_overflow: bool = False) -> bytes:
        """Devuelve EXACTAMENTE n_frames*2 bytes, o levanta OSError.

        El bucle no es una precaución teórica: un pipe entrega lo que
        haya llegado, no lo que se pidió. Aceptar el trozo corto haría
        que los chunks quedaran de largo variable y correría todas las
        constantes de tiempo del VAD sin que nada avise.

        Si el productor muere se levanta OSError y NO se devuelve
        silencio: _escuchar() ya sabe atrapar OSError y recrear el
        stream, mientras que un silencio eterno dejaría a MEXA sorda
        pareciendo que anda.
        """
        faltan = n_frames * ANCHO
        trozos = []
        while faltan > 0:
            try:
                trozo = os.read(self._fd, faltan)
            except InterruptedError:
                continue
            if not trozo:
                raise OSError("[AUDIO] pw-record dejó de entregar audio.")
            trozos.append(trozo)
            faltan -= len(trozo)
        return b"".join(trozos)

    def descartar_pendiente(self) -> None:
        """Tira el audio que se acumuló mientras nadie leía.

        Mientras MEXA habla nadie consume el pipe, así que lo primero que
        habría al volver a escuchar es su propia voz de hace dos
        segundos. Es el mismo motivo por el que existía _vaciar_buffer()
        con PyAudio, con otra mecánica: acá se lee sin bloquear hasta que
        el pipe queda seco.
        """
        os.set_blocking(self._fd, False)
        try:
            tirado = 0
            while tirado < _DESCARTE_MAX:
                try:
                    trozo = os.read(self._fd, 65536)
                except (BlockingIOError, InterruptedError):
                    break
                if not trozo:
                    break
                tirado += len(trozo)
        finally:
            os.set_blocking(self._fd, True)

    def is_active(self) -> bool:
        """True mientras el pw-record siga vivo."""
        return self._proc.poll() is None

    def close(self) -> None:
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2)
        except Exception:
            pass


def abrir(nodo: str | None = None) -> CapturaPipeWire:
    """Abre la captura sobre el nodo indicado, o el mejor disponible."""
    return CapturaPipeWire(comando(nodo or elegir_nodo()))
