"""
Verificación en hardware del CANCELADOR DE ECO (AEC) de MEXA.

EL PROBLEMA QUE RESUELVE: mientras MEXA habla o proyecta un video, su
propio sonido sale por el parlante y vuelve a entrar por el micrófono. El
reconocedor no distingue esa voz de la de un visitante, así que hasta
ahora MEXA se tapaba los oídos mientras hablaba
(`modulo_audio._vaciar_buffer`). El costo: nadie puede interrumpirla. Hay
que esperar los 15 segundos del video completo.

QUÉ HACE EL AEC: PipeWire toma como REFERENCIA lo que sale por el sink
por defecto (monitor.mode) y se lo RESTA a lo que entra por el micrófono.
Puede hacerlo porque es el único que ve los dos lados con el mismo reloj
— una app no puede: pygame, cvlc y PyAudio no comparten tiempo entre sí.

POR QUÉ ESTE SCRIPT EXISTE: que el AEC cargue NO significa que sirva.

QUÉ SE MIDE Y EN QUÉ ORDEN. Cada paso existe porque sin él el siguiente
mentiría:

Cada medición captura TRES canales a la vez: el micrófono crudo, la
salida del cancelador, y la REFERENCIA (lo que sale por el parlante,
leído del monitor del sink). El tercero es el que evita adivinar: "MEXA
no sonó" y "MEXA sonó y el filtro se comió la voz" dan las dos salida
cero, y sin la referencia no hay forma de distinguirlas.

  PASO 0 — PISO DE LA SALA, en silencio. Es la vara. Sin conocerlo no se
    puede saber si en la PRUEBA A hubo eco de verdad o el parlante estaba
    mudo. Esa distinción hundió la primera corrida de este script: midió
    401 RMS de "eco" sobre un piso de 401 RMS, o sea nada, dividió por
    cero y celebró un `inf` como si fuera cancelación perfecta.

  PRUEBA A — MEXA sola. Mide el RESIDUO: cuánto eco queda cuando nadie
    habla. Ese residuo es el ruido de fondo que la voz del visitante va a
    tener que superar. NO es un examen que el AEC pueda reprobar (ver
    abajo), es una vara para la PRUEBA C.
  PRUEBA B — el visitante solo. ¿Deja pasar su voz?
  PRUEBA C — LOS DOS A LA VEZ. Esto es el barge-in, y esto es lo que
    decide el veredicto.

POR QUÉ LA PRUEBA A NO PUEDE JUZGAR EL BARGE-IN. Medido en hardware el
2026-08-27, con MEXA sonando sola y el micrófono entre 1000 y 2500 RMS,
la salida del cancelador se desploma a ~130 RMS en pocos segundos y a
veces a CERO EXACTO:

    t=0.8s -> 609    t=3.8s -> 128    t=7.2s -> 125    t=11.2s -> 184

Eso no es un cancelador excelente ni un nodo roto: es el supresor no
lineal de WebRTC, que cuando solo hay señal del lado LEJANO concluye que
todo lo que entra es eco y suprime al máximo. Por diseño. O sea que en la
PRUEBA A este filtro va a lucir espectacular SIEMPRE, sin importar si
sirve o no para lo que nos interesa.

LA PREGUNTA REAL es si ese mismo supresor deja pasar al visitante cuando
habla ENCIMA de MEXA. Eso se llama DOBLE CONVERSACIÓN, es donde estos
filtros se rompen, y solo lo mide la PRUEBA C. Un veredicto de barge-in
sacado de A y B es un veredicto sobre un escenario que nunca ocurre.

DOS MANERAS DE FALLAR, y un solo número no las distingue:
  1. NO CANCELA — el eco pasa igual. El AEC no compró nada.
  2. CANCELA DE MÁS — se come también al visitante. Esto es PEOR que no
     tener AEC, porque MEXA queda sorda y encima parece que anda.

Y una tercera que no es del cancelador sino del banco de pruebas: MEDIR
NADA — eco que nunca llegó al micrófono porque el parlante estaba mudo o
todavía despertándose. Eso no es un resultado, es una medición inválida,
y acá se rechaza en vez de convertirse en número.

REQUISITO: la config del AEC tiene que estar instalada y cargada:
  cp config/pipewire/99-mexa-aec.conf ~/.config/pipewire/pipewire.conf.d/
  systemctl --user restart pipewire

USO (MEXA en su lugar, parlante encendido y con volumen de exposición):
  python3 tests/calibrar_aec.py

Ctrl+C corta en cualquier momento.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audioop
import glob
import math
import re
import subprocess
import threading
import time
from typing import NamedTuple

# Nodos de PipeWire. El crudo es el micrófono tal como entra; el AEC es el
# mismo micrófono después de restarle lo que salió por el parlante. Se
# importan de modulos/captura.py, que es de donde los lee MEXA de verdad:
# si acá se midiera un nodo y MEXA escuchara otro, este banco de pruebas
# estaría calibrando algo que nadie usa.
from modulos.captura import NODO_AEC as _NODO_AEC, NODO_CRUDO as _NODO_CRUDO

# Puertos que TIENEN que estar enchufados al cancelador. Esto no es
# paranoia: el módulo se carga junto con el daemon de PipeWire, ANTES de
# que los dispositivos estén publicados. Si el micrófono todavía no
# existe, `target.object` no encuentra a quién apuntar y WirePlumber
# engancha el AEC a lo que sea el dispositivo por defecto en ese
# instante. Cuando eso pasa, el nodo entrega CEROS y el calibrador
# informaría "cancela infinito" — sordera perfecta disfrazada de éxito.
_PUERTO_MIC          = f"{_NODO_CRUDO}:capture_MONO"
_PUERTO_AEC_ENTRADA  = "mexa_aec_capture:input_MONO"
_NODO_REFERENCIA     = "echo-cancel-sink"

# 16 kHz mono s16: exactamente la señal que termina viendo el VAD y Vosk.
# Medir en otro formato sería juzgar con una regla que MEXA no usa.
_RATE   = 16000
_ANCHO  = 2
_CHUNK  = 4096

_MEDICION_S = 6.0
_PISO_S     = 4.0

# El AEC de WebRTC es un filtro ADAPTATIVO: arranca sin saber nada de la
# sala y aprende la respuesta del recinto sobre la marcha. Los primeros
# segundos cancela mal por diseño. Medir ahí sería culpar al AEC de estar
# aprendiendo.
_CONVERGENCIA_S = 2.5

# CRITERIOS DE VEREDICTO. No son leyes de la física: son el mínimo que
# hace que el barge-in valga la pena. 6 dB es dividir la amplitud del eco
# a la mitad; 3 dB sobre la voz es lo que se acepta perder del visitante.
_ATENUACION_MINIMA_ECO_DB = 6.0
_ATENUACION_MAXIMA_VOZ_DB = 3.0

# Cuánto se le permite perder a la voz del visitante cuando MEXA está
# sonando encima. Se tolera más que en la PRUEBA B (3 dB) porque en doble
# conversación cualquier cancelador sufre; 6 dB es la mitad de amplitud,
# que el VAD todavía puede levantar sobre el piso de la sala.
_PERDIDA_MAXIMA_DOBLE_DB = 6.0

# El eco tiene que superar al piso de la sala por este factor para que la
# PRUEBA A signifique algo. Menos que esto y no se está midiendo un
# cancelador: se está midiendo una sala en silencio. 2.0 son 6 dB: alcanza
# para separar "hubo eco" de "no sonó nada", que es lo que esta guarda
# tiene que decidir. Se probó 2.5 y rechazaba mediciones buenas de 14.7 dB
# nada más que porque la sala estaba ruidosa ese rato.
_MARGEN_ECO_SOBRE_PISO = 2.0

# Una medición de piso contaminada por un transitorio deja la vara alta y
# hace que un eco perfectamente bueno parezca insuficiente. Mismo criterio
# y mismo umbral que tests/calibrar_umbral_voz.py: p80/p20 del ruido.
_SPREAD_MAX = 3.0

# En la PRUEBA C suena el MISMO video, por el MISMO parlante y al MISMO
# volumen que en la A. Si el micrófono oye bastante menos que en la A, el
# parlante no estaba reproduciendo igual y las dos pruebas no son
# comparables. 0.8 deja margen para la variación del propio video.
_ECO_REPETIBLE = 0.8

# Nivel de referencia por debajo del cual se considera que NO está
# saliendo audio por el parlante. El monitor en silencio mide 0 exacto.
_REF_MINIMA = 200


class Medicion(NamedTuple):
    """Lo que sale de una captura simultánea crudo/cancelado."""
    crudo: int
    aec: int
    pico_crudo: int
    pico_aec: int
    p20_crudo: int
    ref: int

    @property
    def db(self) -> float:
        """Cuántos dB bajó la señal al pasar por el cancelador."""
        if self.aec <= 0:
            return math.inf
        if self.crudo <= 0:
            return 0.0
        return 20.0 * math.log10(self.crudo / self.aec)

    @property
    def muda(self) -> bool:
        """True si el cancelador entregó SILENCIO DIGITAL.

        Pico cero significa que todas las muestras fueron cero exacto. Un
        cancelador real jamás produce eso: resta el eco, no el ruido de
        la sala, así que siempre queda residuo. Cero absoluto es un nodo
        que dejó de entregar — mal cableado, o el módulo caído.
        """
        return self.pico_aec == 0

    @property
    def spread(self) -> float:
        """p80/p20 del micrófono: cuánto se despega de su propio piso."""
        return self.crudo / self.p20_crudo if self.p20_crudo else 0.0


def _nodo_existe(nombre: str) -> bool:
    """True si PipeWire tiene ese nodo cargado ahora mismo."""
    try:
        salida = subprocess.run(["pw-cli", "ls", "Node"], capture_output=True,
                                text=True, timeout=10).stdout
    except Exception:
        return False
    return f'node.name = "{nombre}"' in salida


def _sink_por_defecto() -> str:
    """node.name del sink por defecto: por ahí sale el audio de MEXA.

    Importa porque ni el TTS (`pw-play`) ni el video (`cvlc`) eligen
    destino: los dos van al sink por defecto. Ese, y no otro, es el
    parlante cuyo eco hay que restar.
    """
    try:
        salida = subprocess.run(["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                                capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""
    hallado = re.search(r'node\.name = "([^"]+)"', salida)
    return hallado.group(1) if hallado else ""


def _links_entrantes() -> dict[str, list[str]]:
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


def _reconectar(destino: str, origen_bueno: str, origenes_malos: list[str]) -> bool:
    """Desengancha lo que sobra y enchufa lo que corresponde."""
    for malo in origenes_malos:
        subprocess.run(["pw-link", "-d", malo, destino],
                       capture_output=True, timeout=10)
    hecho = subprocess.run(["pw-link", origen_bueno, destino],
                           capture_output=True, timeout=10)
    return hecho.returncode == 0


def _verificar_cableado() -> bool:
    """Comprueba de dónde toma el AEC el micrófono y la referencia.

    Un cancelador mal cableado no da error: da un número. Ese número
    parece una medición y no lo es. Antes de creerle al veredicto hay que
    ver los dos cables con los ojos.
    """
    print("Cableado del cancelador:")
    entrantes = _links_entrantes()
    sano = True

    # --- micrófono -> AEC ---
    origenes = entrantes.get(_PUERTO_AEC_ENTRADA, [])
    if origenes == [_PUERTO_MIC]:
        print(f"  micrófono   OK   {_PUERTO_MIC}")
    else:
        print(f"  micrófono   MAL  el AEC escucha {origenes or 'NADA'}")
        print(f"               debería escuchar {_PUERTO_MIC}")
        if input("  ¿Reconecto? [S/n] ").strip().lower() in ("", "s", "si", "sí"):
            sano = _reconectar(_PUERTO_AEC_ENTRADA, _PUERTO_MIC, origenes)
            print("  reconectado." if sano else "  NO se pudo reconectar.")
        else:
            sano = False

    # --- referencia (monitor del sink por defecto) -> AEC ---
    sink = _sink_por_defecto()
    if not sink:
        print("  referencia  ?    no se pudo leer el sink por defecto.")
        return False
    puertos_ref = {p: o for p, o in entrantes.items()
                   if p.startswith(f"{_NODO_REFERENCIA}:")}
    if not puertos_ref:
        print(f"  referencia  MAL  {_NODO_REFERENCIA} no recibe nada.")
        return False
    ajenos = sorted({o.split(":")[0] for orig in puertos_ref.values()
                     for o in orig} - {sink})
    if ajenos:
        print(f"  referencia  MAL  toma el eco de {', '.join(ajenos)}")
        print(f"               pero MEXA suena por {sink}")
        print("               → el AEC restaría un sonido que nadie oye.")
        sano = False
    else:
        print(f"  referencia  OK   monitor de {sink}")

    return sano


def _capturar_trio(segundos: float) -> tuple[bytes, bytes, bytes]:
    """Captura de los TRES nodos a la vez: (crudo, cancelado, referencia).

    La REFERENCIA es lo que sale por el parlante, leído del monitor del
    sink. Sin ella no se puede distinguir "MEXA no sonó" de "MEXA sonó y
    el filtro se comió la voz": las dos cosas dan salida cero y sin este
    tercer canal el veredicto sería una adivinanza.

    Simultáneo a propósito: comparar dos grabaciones tomadas en momentos
    distintos no mediría el AEC, mediría la diferencia entre dos instantes
    de la sala. Ese fue justamente el error que invalidó el experimento de
    tests/calibrar_distancia_voz.py — la fuente no era reproducible.

    Los dos pw-record no arrancan en el mismo microsegundo, y el AEC
    agrega latencia propia. No importa: acá se compara ENERGÍA AGREGADA
    sobre varios segundos, no muestra contra muestra.
    """
    n_bytes = int(segundos * _RATE * _ANCHO)
    descarte = int(_CONVERGENCIA_S * _RATE * _ANCHO)
    resultados: dict[str, bytes] = {}
    procesos: dict[str, subprocess.Popen] = {}
    comun = ["--rate", str(_RATE), "--channels", "1", "--format", "s16",
             "--raw", "-"]

    for clave, nodo in (("crudo", _NODO_CRUDO), ("aec", _NODO_AEC)):
        procesos[clave] = subprocess.Popen(
            ["pw-record", "--target", nodo] + comun,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
    # El monitor de un sink se captura con stream.capture.sink: sin esa
    # propiedad, --target sobre un sink no engancha el monitor y devuelve
    # silencio — que se confundiría con "el parlante está mudo".
    procesos["ref"] = subprocess.Popen(
        ["pw-record", "-P", "stream.capture.sink=true",
         "--target", _sink_por_defecto()] + comun,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    def _leer(clave: str) -> None:
        salida = procesos[clave].stdout
        salida.read(descarte)          # se tira el tramo de convergencia
        resultados[clave] = salida.read(n_bytes)

    hilos = [threading.Thread(target=_leer, args=(c,)) for c in procesos]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    for p in procesos.values():
        p.terminate()
        p.wait()

    return (resultados.get("crudo", b""), resultados.get("aec", b""),
            resultados.get("ref", b""))


def _esperar_eco(piso: int, limite_s: float = 12.0) -> float | None:
    """Espera a que el eco LLEGUE AL MICRÓFONO. Devuelve cuánto tardó.

    No se usa un sleep fijo porque el retardo no es constante. Un sink
    Bluetooth se SUSPENDE cuando está ocioso — verificado en hardware:
    `state: "suspended"` tras 20 s de silencio — y despertar el enlace
    A2DP lleva su tiempo, además de lo que tarde cvlc en arrancar. Medir
    contra el reloj hace que la ventana caiga sobre un parlante que
    todavía no suena: así se midieron 819 RMS de "eco" en una sala donde
    el mismo parlante, ya despierto, da 2975.

    Se espera la EVIDENCIA FÍSICA, no el reloj: que el micrófono oiga el
    doble del piso. None si nunca llega.
    """
    umbral = piso * 2
    paso = int(0.25 * _RATE * _ANCHO)
    p = subprocess.Popen(
        ["pw-record", "--target", _NODO_CRUDO, "--rate", str(_RATE),
         "--channels", "1", "--format", "s16", "--raw", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        inicio = time.time()
        while time.time() - inicio < limite_s:
            datos = p.stdout.read(paso)
            if not datos:
                return None
            if audioop.rms(datos, _ANCHO) > umbral:
                return time.time() - inicio
        return None
    finally:
        p.terminate()
        p.wait()


def _rms_por_chunk(datos: bytes) -> list[int]:
    """RMS de cada chunk, igual que lo mide el VAD."""
    paso = _CHUNK
    return [audioop.rms(datos[i:i + paso], _ANCHO)
            for i in range(0, len(datos) - paso, paso)]


def _percentil(ordenadas: list[int], q: float) -> int:
    """Percentil q (0..1) de una lista YA ordenada."""
    if not ordenadas:
        return 0
    return ordenadas[min(int(len(ordenadas) * q), len(ordenadas) - 1)]


def _nivel(muestras: list[int]) -> int:
    """Nivel representativo: percentil 80.

    No se usa el promedio ni el pico. El promedio lo hunde el silencio
    entre palabras y el pico lo dispara cualquier golpe: los dos mienten
    sobre cuánta señal hay realmente. El p80 describe los tramos con
    sonido, que es lo que se quiere comparar.
    """
    return _percentil(sorted(muestras), 0.80)


def _medir(titulo: str, segundos: float = _MEDICION_S) -> Medicion | None:
    """Corre una medición simultánea y la reporta. None si no entró audio."""
    crudo_raw, aec_raw, ref_raw = _capturar_trio(segundos)
    if not crudo_raw or not aec_raw:
        print("  ERROR: no entró audio de alguno de los dos nodos.")
        return None

    crudo, aec = _rms_por_chunk(crudo_raw), _rms_por_chunk(aec_raw)
    ref = _rms_por_chunk(ref_raw)
    m = Medicion(_nivel(crudo), _nivel(aec), max(crudo), max(aec),
                 _percentil(sorted(crudo), 0.20), _nivel(ref))

    print(f"  {titulo}")
    print(f"    sale por el parlante  p80 {m.ref:>6} RMS")
    print(f"    micrófono crudo       p80 {m.crudo:>6} RMS   pico {m.pico_crudo:>6}")
    print(f"    con cancelador        p80 {m.aec:>6} RMS   pico {m.pico_aec:>6}")
    if m.muda:
        print("    → SILENCIO DIGITAL a la salida del cancelador.")
    else:
        print(f"    → atenuación {m.db:.1f} dB")
    return m


def _energia_propia(total: int, piso: int) -> int:
    """Cuánta señal aportó la fuente, descontando el ruido de la sala.

    El RMS suma en POTENCIA, no en amplitud: dos sonidos de 100 RMS cada
    uno no dan 200 sino 141. Restar a secas (total - piso) sobrestima lo
    que aportó la fuente, y en una sala ruidosa la sobrestima tanto que
    el juicio deja de valer. Lo que corresponde es despejar la potencia.
    """
    return int(math.sqrt(max(total * total - piso * piso, 0)))


def _buscar_video() -> str | None:
    """Un video cualquiera del catálogo: sirve como fuente de eco real."""
    videos = sorted(glob.glob("media/videos/*/*.mp4"))
    return videos[0] if videos else None


def _reproducir(video: str) -> subprocess.Popen:
    """Arranca el video EN BUCLE como fuente de eco.

    En bucle a propósito: los videos del catálogo duran ~10 s y una
    medición se lleva 8.5 s más el arranque de cvlc. Sin `--loop` el
    último tramo se mide sobre un parlante que ya se calló, y el promedio
    reporta menos eco del que hubo.
    """
    return subprocess.Popen(
        ["cvlc", "--no-video", "--loop", video],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def main() -> int:
    print("\n=== CALIBRACIÓN DEL CANCELADOR DE ECO (AEC) ===\n")

    if not _nodo_existe(_NODO_AEC):
        print(f"  El nodo '{_NODO_AEC}' NO está cargado.")
        print("  Falta cargar la config del AEC:")
        print("    cp config/pipewire/99-mexa-aec.conf \\")
        print("       ~/.config/pipewire/pipewire.conf.d/")
        print("    systemctl --user restart pipewire")
        return 1

    if not _verificar_cableado():
        print("\n  El cancelador está mal enchufado. Cualquier número que")
        print("  saliera de acá sería mentira. Corregí el cableado y volvé.")
        return 1

    video = _buscar_video()
    if video is None:
        print("  No hay ningún video en media/videos/ para generar el eco.")
        return 1

    # ---------- PASO 0: la vara ----------
    print("\nPASO 0 — PISO DE LA SALA. Silencio total, no hables.")
    while True:
        input("  Enter para empezar... ")
        piso = _medir("sala en reposo", _PISO_S)
        if piso is None:
            return 1
        if piso.muda:
            print("\n  El cancelador entrega silencio digital CON LA SALA")
            print("  QUIETA. No cancela nada: está roto. Revisá el cableado.")
            return 5
        if piso.ref >= _REF_MINIMA:
            print(f"\n  !! ALGO ESTÁ SONANDO por el parlante ({piso.ref} RMS de")
            print("     referencia) mientras mido el piso. La vara queda alta")
            print("     y arrastra el error a todas las pruebas siguientes.")
            if input("     ¿Repito? [S/n] ").strip().lower() in ("", "s", "si", "sí"):
                continue
        if piso.spread <= _SPREAD_MAX:
            break
        print(f"\n  !! MEDICIÓN CONTAMINADA: p80/p20 = {piso.spread:.1f}x "
              f"(sano: menos de {_SPREAD_MAX:.0f}x)")
        print("     Algo sonó mientras medía el piso. Con la vara alta, un")
        print("     eco perfectamente bueno se rechazaría por insuficiente.")
        if input("     ¿Repito? [S/n] ").strip().lower() not in ("", "s", "si", "sí"):
            print("     Sigo con el piso contaminado. Anotalo.")
            break

    # ---------- PRUEBA A: ¿cancela el eco propio? ----------
    print("\nPRUEBA A — MEXA suena sola (NO hables durante esta prueba).")
    print(f"  Reproduciendo en bucle: {video}")
    input("  Enter para empezar... ")
    reproductor = _reproducir(video)
    espera = _esperar_eco(piso.crudo)
    if espera is None:
        reproductor.terminate()
        reproductor.wait()
        print("\n  MEDICIÓN INVÁLIDA: el micrófono no oyó NADA del parlante.")
        print("  Revisá que esté encendido, conectado y con volumen. Sin eco")
        print("  no hay nada que cancelar y el AEC no puede ser juzgado.")
        return 6
    print(f"  el eco llegó al micrófono en {espera:.1f} s")
    eco = _medir("eco del parlante")
    reproductor.terminate()
    reproductor.wait()
    if eco is None:
        return 1

    # GUARDA: sin eco no hay nada que cancelar, y el número que salga de
    # acá no describe al cancelador sino a una sala callada.
    # La referencia distingue las dos causas de un eco flojo: si no sale
    # audio del parlante el problema es la reproducción; si sale y el
    # micrófono no lo oye, el problema es acústico (volumen o distancia).
    if eco.ref < _REF_MINIMA:
        print(f"\n  MEDICIÓN INVÁLIDA: por el parlante no salió audio "
              f"({eco.ref} RMS).")
        print("  No es el micrófono ni el cancelador: MEXA no sonó. Revisá")
        print("  que el parlante siga conectado como salida por defecto.")
        return 6

    minimo = int(piso.crudo * _MARGEN_ECO_SOBRE_PISO)
    eco_propio = _energia_propia(eco.crudo, piso.crudo)
    if eco_propio < minimo:
        print(f"\n  MEDICIÓN INVÁLIDA: descontado el ruido de la sala, el eco")
        print(f"  aportó {eco_propio} RMS sobre un piso de {piso.crudo}.")
        print(f"  Hacen falta {minimo} o más.")
        # Dos causas muy distintas piden dos acciones muy distintas. Decir
        # "subí el volumen" cuando lo que pasa es que la sala está ruidosa
        # manda a arreglar lo que no está roto.
        if eco_propio < piso.crudo // 2:
            print("  El parlante prácticamente NO LLEGA al micrófono: revisá")
            print("  que esté encendido, conectado, cerca y con volumen.")
        else:
            print("  El eco se oye, pero no se despega del ruido de la sala.")
            print("  O el parlante está bajo, o la sala está demasiado")
            print("  ruidosa para juzgar nada. Subí el volumen, o esperá a")
            print("  que baje el ruido y repetí.")
        return 6

    if eco.muda:
        print("  (residuo NULO. Con MEXA sonando sola, el supresor de WebRTC")
        print("   aplica cancelación máxima: es su comportamiento normal, no")
        print("   una falla. Tampoco dice nada sobre el barge-in — eso lo")
        print("   decide la PRUEBA C.)")

    # ---------- PRUEBA B: ¿deja pasar al visitante? ----------
    print("\nPRUEBA B — MEXA CALLADA. Hablá vos, parado donde va el visitante.")
    print("  Hablá sin parar hasta que diga que terminó.")
    input("  Enter para empezar... ")
    voz = _medir("voz del visitante")
    if voz is None:
        return 1
    voz_propia = _energia_propia(voz.crudo, piso.crudo)
    if voz_propia < minimo:
        print(f"\n  MEDICIÓN INVÁLIDA: descontado el ruido, tu voz aportó")
        print(f"  {voz_propia} RMS sobre un piso de {piso.crudo}; hacen falta")
        print(f"  {minimo}. Acercate o hablá más fuerte y repetí.")
        return 6

    # ---------- PRUEBA C: doble conversación. ESTO es el barge-in ----------
    print("\nPRUEBA C — LOS DOS A LA VEZ. Esto es el barge-in de verdad.")
    print("  MEXA va a sonar Y vos vas a hablar encima, sin parar.")
    input("  Enter para empezar... ")
    reproductor = _reproducir(video)
    if _esperar_eco(piso.crudo) is None:
        reproductor.terminate()
        reproductor.wait()
        print("\n  MEDICIÓN INVÁLIDA: el parlante no llegó al micrófono.")
        return 6
    print("  ¡AHORA! Hablá sin parar.")
    doble = _medir("MEXA hablando + visitante hablando")
    reproductor.terminate()
    reproductor.wait()
    if doble is None:
        return 1

    # DOS GUARDAS, porque la PRUEBA C es la que decide y una medición
    # inválida acá se convierte en un veredicto sobre el barge-in.
    if doble.ref < _REF_MINIMA:
        print(f"\n  MEDICIÓN INVÁLIDA: por el parlante no salió audio "
              f"({doble.ref} RMS).")
        print("  Sin MEXA sonando esto no es doble conversación: es la")
        print("  PRUEBA B otra vez. Repetí.")
        return 6

    # El micrófono tiene que oír AL MENOS lo que oyó en la PRUEBA A: mismo
    # video, mismo parlante, mismo volumen, y encima la voz sumada. Si oye
    # menos, las dos fuentes no estaban sonando juntas y comparar A con C
    # no significa nada. Dos fuentes suman en potencia: nunca pueden dar
    # menos que la más fuerte de las dos.
    minimo_doble = int(eco.crudo * _ECO_REPETIBLE)
    if doble.crudo < minimo_doble:
        print(f"\n  MEDICIÓN INVÁLIDA: el micrófono oyó {doble.crudo} RMS con")
        print(f"  las dos fuentes juntas, menos que los {eco.crudo} RMS que oyó")
        print("  con el parlante SOLO. Eso es imposible si las dos sonaban:")
        print("  la suma de dos fuentes nunca da menos que la más fuerte.")
        print("  El parlante bajó, se alejó o se cortó a mitad de la prueba.")
        return 6

    # Cuánto de la voz sobrevive cuando MEXA suena encima. Se compara
    # contra la voz SOLA a la salida del cancelador, no contra el crudo:
    # la pregunta no es cuánto se pierde en total, es cuánto MÁS se
    # pierde por el hecho de que MEXA esté hablando.
    if doble.aec <= 0:
        perdida_doble = math.inf
    elif voz.aec <= 0:
        perdida_doble = 0.0
    else:
        perdida_doble = 20.0 * math.log10(voz.aec / doble.aec)

    # ---------- VEREDICTO ----------
    print("\n--- VEREDICTO ---")
    print(f"  piso de la sala               {piso.crudo:>6} RMS")
    print(f"  atenuación sobre el ECO       {eco.db:>6.1f} dB "
          f"(mínimo de cordura: {_ATENUACION_MINIMA_ECO_DB:.0f})")
    print(f"  atenuación sobre la VOZ sola  {voz.db:>6.1f} dB "
          f"(tolerable hasta {_ATENUACION_MAXIMA_VOZ_DB:.0f})")
    print(f"  voz PERDIDA en doble convers. {perdida_doble:>6.1f} dB "
          f"(tolerable hasta {_PERDIDA_MAXIMA_DOBLE_DB:.0f})")
    print(f"  residuo de eco solo           {eco.aec:>6} RMS")
    print(f"  salida en doble conversación  {doble.aec:>6} RMS")

    cancela   = eco.db >= _ATENUACION_MINIMA_ECO_DB
    respeta   = voz.db <= _ATENUACION_MAXIMA_VOZ_DB
    sobrevive = perdida_doble <= _PERDIDA_MAXIMA_DOBLE_DB
    # Si en doble conversación no sale más que el residuo del eco, lo que
    # "sobrevivió" no es la voz del visitante: es el eco mal cancelado.
    distingue = doble.aec > eco.aec

    if not cancela:
        # Reprobar ACÁ es difícil: con señal solo del lado lejano el
        # supresor de WebRTC cancela al máximo por diseño. Si ni siquiera
        # así baja el eco, el filtro no está alineando nada — el retardo
        # del enlace excede su ventana, o el parlante satura el micrófono.
        print("\n  NO SIRVE — NO CANCELA ni en el caso más fácil: MEXA")
        print("  sonando sola, que es donde este filtro suprime al máximo.")
        print("  → el eco vuelve más tarde de lo que el filtro puede seguir,")
        print("    o el parlante satura el micrófono.")
        return 3
    if not respeta:
        print("\n  NO SIRVE — CANCELA DE MÁS: se come al visitante aun")
        print("  cuando MEXA está callada.")
        print("  → MEXA quedaría más sorda que antes. NO seguir con el")
        print("    barge-in hasta ajustar el AEC.")
        return 2
    if not sobrevive or not distingue:
        print("\n  NO SIRVE PARA BARGE-IN — el cancelador se porta bien con")
        print("  cada fuente por separado, pero cuando MEXA habla encima")
        print("  del visitante se come la voz.")
        print("  → esto es DOBLE CONVERSACIÓN. A y B pasaban; sin la PRUEBA")
        print("    C el barge-in se habría dado por bueno y MEXA habría")
        print("    quedado sorda justo cuando la interrumpen.")
        return 7

    print("\n  SIRVE: baja el eco, deja pasar al visitante, y lo sigue")
    print("  dejando pasar CUANDO MEXA HABLA ENCIMA.")
    print("  → se puede seguir con el barge-in.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCortado.")
        sys.exit(130)
