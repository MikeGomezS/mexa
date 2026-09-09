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
import re
import subprocess

# El micrófono SIN eco que publica el módulo echo-cancel.
NODO_AEC = "mexa_aec_source"


def _listar_nodos() -> str:
    """La lista de nodos de PipeWire, cruda. Cuesta ~11 ms (medido)."""
    try:
        return subprocess.run(["pw-cli", "ls", "Node"], capture_output=True,
                              text=True, timeout=10).stdout
    except Exception:
        return ""


# ── El micrófono crudo se BUSCA, no se nombra ────────────────
#
# Acá había un nombre escrito a mano. El 2026-09-08 se cambió el clip-on
# por un lavalier inalámbrico y ese nombre dejó de existir: MEXA quedó
# apuntando a un nodo fantasma.
#
# Y lo grave no fue quedarse sin nodo, fue que NADIE SE ENTERÓ:
# `pw-record --target <nodo-que-no-existe>` NO FALLA. Cae al micrófono por
# defecto y sigue entregando audio como si nada. Medido ese día: 156614
# bytes de audio REAL leídos de un nodo inexistente, que resultaron ser el
# micrófono del parlante Bluetooth. O sea que la degradación "caigo al
# micrófono CRUDO avisando" de elegir_nodo() estaba parada sobre un nombre
# que nadie verificaba: creía caer al micrófono y caía a cualquier cosa.
#
# Por eso ahora el micrófono se busca en el grafo. El patrón deja afuera a
# propósito los micrófonos Bluetooth (`bluez_input.*`), que son justo los
# que se colaron las dos veces que esto se rompió en silencio.
#
# SOBRE LOS NOMBRES QUE CAMBIAN AL CAMBIAR DE PUERTO USB: un dispositivo
# con número de serie se llama por su serie y sobrevive al cambio de
# puerto — verificado el 2026-09-08 moviendo el receptor de puerto, el
# nombre no cambió. Uno SIN número de serie lleva la ruta USB adentro del
# nombre y sí cambia. Buscar por patrón cubre los dos casos; escribir el
# nombre a mano no cubre ninguno.
_PATRON_MIC = re.compile(r'node\.name = "(alsa_input\.usb-[^"]*)"')


def microfono_usb(listar=None) -> str | None:
    """El micrófono USB publicado en el grafo, o None si no hay ninguno.

    Devuelve None en vez de un nombre inventado A PROPÓSITO. Un nombre que
    no existe no es un valor seguro: pw-record se lo come sin chistar y
    escucha otra cosa. Si no hay micrófono hay que decirlo, no adivinarlo.
    """
    hallados = sorted(set(_PATRON_MIC.findall((listar or _listar_nodos)())))
    if not hallados:
        return None
    if len(hallados) > 1:
        print(f"[AUDIO] Hay {len(hallados)} micrófonos USB: {hallados}. "
              f"Uso {hallados[0]}.")
    return hallados[0]


# Se resuelve una vez al importar (cuesta ~11 ms) y queda como constante
# del módulo porque es la costura que importan tests/test_captura.py,
# tests/calibrar_aec.py y tests/probar_barge_in.py. Si se cambia el
# micrófono con MEXA ya corriendo hay que reimportar; en la práctica el
# micrófono se enchufa antes de arrancar.
NODO_CRUDO = microfono_usb()

# Puertos del grafo. Que el nodo del AEC EXISTA no significa que esté
# escuchando el micrófono correcto: el módulo echo-cancel se carga junto
# con el daemon de PipeWire, ANTES de que los dispositivos estén
# publicados, y si el micrófono todavía no existe WirePlumber lo engancha
# al dispositivo por defecto de ese instante. Visto en hardware el
# 2026-08-27: quedó enganchado a un micrófono Bluetooth y el nodo
# entregaba CEROS. Sin error, sin log: sordera total.
PUERTO_MIC         = f"{NODO_CRUDO}:capture_MONO" if NODO_CRUDO else None
PUERTO_AEC_ENTRADA = "mexa_aec_capture:input_MONO"

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
    return f'node.name = "{nombre}"' in _listar_nodos()


def links_entrantes() -> dict[str, list[str]]:
    """Mapa puerto_destino -> puertos de origen, leído de `pw-link -l`."""
    try:
        salida = subprocess.run(["pw-link", "-l"], capture_output=True,
                                text=True, timeout=10).stdout
    except Exception:
        return {}
    mapa: dict[str, list[str]] = {}
    destino = ""
    for linea in salida.splitlines():
        if linea[:1] and not linea[:1].isspace():
            destino = linea.strip()
        elif "|<-" in linea:
            mapa.setdefault(destino, []).append(linea.split("|<-", 1)[1].strip())
    return mapa


def entrada_del_aec() -> list[str]:
    """De qué puertos está leyendo el cancelador ahora mismo."""
    return links_entrantes().get(PUERTO_AEC_ENTRADA, [])


def reparar_cableado() -> bool:
    """Desengancha lo que sobra y enchufa el micrófono al cancelador.

    Un enlace hecho a mano se SOSTIENE: WirePlumber no vuelve a moverlo.
    Sólo hay que ganar la carrera del arranque una vez.
    """
    for malo in entrada_del_aec():
        subprocess.run(["pw-link", "-d", malo, PUERTO_AEC_ENTRADA],
                       capture_output=True, timeout=10)
    hecho = subprocess.run(["pw-link", PUERTO_MIC, PUERTO_AEC_ENTRADA],
                           capture_output=True, timeout=10)
    return hecho.returncode == 0


def elegir_nodo(existe=None, entrada=None, reparar=None) -> str:
    """El micrófono sin eco si está Y ESTÁ BIEN CABLEADO; el crudo si no.

    Degrada a propósito en vez de fallar. Las dos degradaciones avisan por
    consola, igual que hace vad.py cuando le falta el modelo de Silero:
    que MEXA no pueda ser interrumpida es un problema, que se quede sorda
    es OTRO, y hay que poder distinguirlos leyendo el arranque.
    """
    existe  = existe  or nodo_existe
    entrada = entrada or entrada_del_aec
    reparar = reparar or reparar_cableado

    # SIN MICRÓFONO NO SE DEGRADA: SE FRENA. Las degradaciones de abajo
    # eligen entre dos micrófonos que existen. "No hay ninguno" no es una
    # degradación, es una ausencia, y devolver cualquier nombre acá haría
    # que pw-record caiga al dispositivo por defecto y MEXA escuche otra
    # cosa creyendo que escucha bien — que es exactamente el modo de falla
    # que este módulo existe para evitar. Mejor no arrancar que arrancar
    # sorda sin saberlo.
    if NODO_CRUDO is None:
        raise RuntimeError(
            "[AUDIO] No hay ningún micrófono USB publicado en PipeWire. "
            "Revisá que el receptor esté enchufado (`arecord -l`) y que "
            "PipeWire lo vea (`pw-cli ls Node`). MEXA no arranca sorda.")

    if not existe(NODO_AEC):
        print(f"[AUDIO] El cancelador de eco no está cargado ({NODO_AEC} no "
              f"existe): escucho el micrófono crudo. MEXA no va a poder ser "
              f"interrumpida mientras habla.")
        return NODO_CRUDO

    if entrada() == [PUERTO_MIC]:
        return NODO_AEC

    # No se puede confiar en un cancelador enganchado a otro micrófono:
    # entrega ceros, y leer ceros es peor que no tener cancelador.
    print(f"[AUDIO] El cancelador está escuchando {entrada() or 'NADA'} en vez "
          f"del micrófono de MEXA. Reconectando...")
    if reparar() and entrada() == [PUERTO_MIC]:
        print("[AUDIO] Cableado del cancelador corregido.")
        return NODO_AEC

    print("[AUDIO] NO se pudo corregir: escucho el micrófono crudo. Sin "
          "cancelador, pero oyendo — leer el nodo mal cableado sería "
          "quedarse sorda sin enterarse.")
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
