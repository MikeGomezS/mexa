"""
¿Puede MEXA ENTENDER a un visitante que le habla encima?

QUÉ PREGUNTA RESPONDE, Y POR QUÉ NO LA RESPONDE tests/calibrar_aec.py.
El calibrador mide ENERGÍA: cuánto baja el eco, cuánto sobrevive la voz.
Su PRUEBA C aprobó con 1830 RMS de salida en doble conversación — pero
ese número es compatible con la voz y el eco fugado MEZCLADOS, y con un
solo canal no hay forma de separarlos. Que la voz tenga volumen no prueba
que se entienda, y lo que MEXA necesita es entender.

Esto sólo lo contesta el reconocedor. Acá se mide la decisión REAL de
MEXA: `_dijo(texto, _PALABRAS_ACTIVACION)` sobre lo que devuelve
`escuchar_multilingue()`. No un proxy, no una transcripción parecida: si
despierta o no despierta.

EL DISEÑO, Y POR QUÉ ES ASÍ. Comparar "con cancelador" contra "sin
cancelador" pidiéndote que repitas la frase dos veces no sirve: tu voz no
es una fuente reproducible, y ese error ya invalidó un experimento entero
(tests/calibrar_distancia_voz.py). Acá, mientras MEXA escucha por su
camino REAL —el del cancelador—, se graba el micrófono CRUDO en paralelo.
Misma voz, mismo instante, dos caminos:

    camino real (AEC)  →  lo que MEXA oye AHORA
    micrófono crudo    →  lo que MEXA oía ANTES, sin cancelador

Si el AEC despierta y el crudo no, el cancelador compró el barge-in. Si
despiertan los dos, el eco no molestaba tanto como creíamos. Si no
despierta ninguno, no hay barge-in.

Y HAY UN TERCER MODO DE FALLA, opuesto y menos obvio: que MEXA se
despierte SOLA al oírse a sí misma. No es teórico. Midiendo con el video
sonando y NADIE hablando, Vosk sobre el micrófono crudo transcribió "one
resembles of they just get money" — siete palabras que nadie dijo. Basta
que una de esas alucinaciones caiga en el vocabulario de activación para
que MEXA se interrumpa a sí misma a mitad del video. Por eso hay un paso
de falso positivo, y no necesita voz humana: sólo hay que callarse.

TRES INTENTOS, NO UNO. Un reconocedor es estocástico: una sola corrida no
distingue "funciona" de "tuvo suerte".

EL WAKE WORD NO ALCANZA COMO MÉTRICA, y esto se aprendió midiendo. En la
primera corrida real el veredicto por wake word dio "el cancelador no
aporta": crudo 3/3 contra AEC 2/3. Pero mirando QUÉ devolvió cada uno:

    con cancelador   "comencemos"                    1 palabra,  0 fantasma
    micrófono crudo  "hoy vamos a de comprar el      9 palabras, 8 fantasma
                      imperio comencemos hola"

Los dos "despiertan", porque buscar UNA palabra clave entre ruido es la
tarea más fácil que hay para un reconocedor: basta con que una zafe. Pero
después de despertar, MEXA TRANSCRIBE PREGUNTAS para el LLM, y esa
segunda frase como pregunta es basura. La métrica del wake word satura y
favorece al micrófono sucio.

Por eso se mide también una PREGUNTA, y no sólo si aparece, sino cuántas
palabras aparecen QUE NADIE DIJO. Esa es la tarea real.

REQUISITOS: el AEC cableado (correr antes tests/calibrar_aec.py) y el
parlante encendido al volumen de exposición.

USO:  python3 tests/probar_barge_in.py
"""

import json
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audioop
import glob

from vosk import KaldiRecognizer

from modulos import modulo_audio as audio
from modulos.captura import RATE, abrir, NODO_CRUDO
from modulos.dialogo import _PALABRAS_ACTIVACION, _dijo, _normalizar

_FRASE    = "comencemos"
# Una pregunta plausible de visitante: es lo que MEXA tiene que entender
# DESPUÉS de despertar, y es la tarea donde una transcripción sucia deja
# de servir. Corta, para que se pueda decir de un tirón sobre el video.
_PREGUNTA = "qué comían los aztecas"
_INTENTOS = 3
_TIMEOUT  = 6.0

# Se usa un VIDEO y no el TTS como fuente de eco: es el caso más duro
# —audio continuo durante 10 s, sin las pausas de una frase hablada— y es
# donde el barge-in más falta hace, porque hoy hay que esperar el video
# entero para poder decir algo.
def _reproducir(video: str) -> subprocess.Popen:
    return subprocess.Popen(["cvlc", "--no-video", "--loop", video],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _esperar_eco(piso: int, limite_s: float = 12.0) -> bool:
    """Espera a que el parlante LLEGUE al micrófono, no al reloj.

    Mismo motivo que en tests/calibrar_aec.py: un sink Bluetooth se
    suspende ocioso y despertarlo lleva su tiempo. Medir contra un sleep
    fijo hace que la prueba caiga sobre un parlante que todavía no suena.
    """
    cap = abrir(NODO_CRUDO)
    try:
        fin = time.time() + limite_s
        while time.time() < fin:
            if audioop.rms(cap.read(RATE // 4), 2) > piso * 2:
                return True
        return False
    finally:
        cap.close()


class _GrabadorCrudo(threading.Thread):
    """Graba el micrófono SIN cancelador mientras MEXA escucha con él."""

    def __init__(self):
        super().__init__(daemon=True)
        self._cap = abrir(NODO_CRUDO)
        self._parar = threading.Event()
        self.pcm = b""

    def run(self) -> None:
        trozos = []
        while not self._parar.is_set():
            try:
                trozos.append(self._cap.read(1600))
            except OSError:
                break
        self.pcm = b"".join(trozos)

    def detener(self) -> bytes:
        self._parar.set()
        self.join(timeout=5)
        self._cap.close()
        return self.pcm


def _idiomas_disponibles() -> list[str]:
    return [i for i in ("es", "en") if audio.modelo_disponible(i)]


def _decodificar(pcm: bytes, idiomas: list[str]) -> dict[str, str]:
    """Pasa un PCM ya grabado por los mismos modelos que usa MEXA."""
    textos = {}
    for i in idiomas:
        rec = KaldiRecognizer(audio._cargar_modelo(i), audio._VOSK_RATE)
        rec.AcceptWaveform(pcm)
        textos[i] = json.loads(rec.FinalResult()).get("text", "").strip()
    return textos


def _exactitud(texto: str, esperado: str) -> tuple[int, int, int]:
    """(palabras acertadas, esperadas, fantasma) de una transcripción.

    FANTASMA es la medida que importa y la que el wake word no ve: cuántas
    palabras devolvió el reconocedor que nadie pronunció. Para despertar
    alcanza con que UNA palabra zafe entre ruido; para que el LLM entienda
    una pregunta, las que sobran la arruinan.
    """
    esperadas = _normalizar(esperado).split()
    dichas    = _normalizar(texto).split()
    aciertos  = sum(1 for e in esperadas if e in dichas)
    fantasma  = sum(1 for d in dichas if d not in esperadas)
    return aciertos, len(esperadas), fantasma


def _desperto(textos: dict[str, str]) -> bool:
    """La decisión REAL de MEXA, no una aproximación."""
    return any(_dijo(t, _PALABRAS_ACTIVACION) for t in textos.values())


def _mostrar(etiqueta: str, textos: dict[str, str], esperado: str = _FRASE) -> tuple[bool, int]:
    """Imprime lo oído y devuelve (despertó, palabras fantasma)."""
    ok = _desperto(textos)
    fantasma = sum(_exactitud(t, esperado)[2] for t in textos.values())
    oido = " | ".join(f"{i}: {t or '(nada)'}" for i, t in textos.items())
    print(f"    {etiqueta:<22} {'DESPIERTA' if ok else 'no despierta':<13} "
          f"[{fantasma:2d} fantasma] {oido}")
    return ok, fantasma


def _cuenta_regresiva(intento: int, total: int, frase: str | None) -> None:
    """Avisa CUÁNDO hablar, con tiempo de reaccionar.

    La primera versión imprimía "¡AHORA!" de golpe y pasaba directo a
    escuchar. No alcanza: para cuando la persona lee el aviso, el video ya
    está sonando fuerte y la ventana de escucha ya arrancó. Con la señal
    perdida se pierde la medición entera, y encima parece un fallo del
    cancelador cuando en realidad es un fallo del banco de pruebas.
    """
    if frase is None:
        print(f"\n  intento {intento}/{total} — CALLADO, no hables.", flush=True)
        return
    print(f"\n  intento {intento}/{total} — preparate para decir: "
          f"\"{frase}\"", flush=True)
    for n in (3, 2, 1):
        print(f"        {n}...", flush=True)
        time.sleep(0.7)
    print(f"\n  >>>>>>>>  ¡AHORA!  DECÍ: \"{frase}\"  <<<<<<<<\n", flush=True)


def _ronda(video: str, idiomas: list[str], intento: int, total: int,
           frase: str | None) -> tuple[dict, dict]:
    """Una medición con MEXA sonando: (lo que oyó por el AEC, por el crudo).

    Los dos caminos ven la MISMA voz en el MISMO instante, que es lo único
    que hace comparable esta prueba: la voz humana no es reproducible.

    ORDEN IMPORTANTE: la cuenta regresiva va ANTES de arrancar el grabador
    del micrófono crudo. Si arrancara antes, el crudo grabaría esos ~2 s
    de video que el camino del AEC no ve, y esas palabras de más contarían
    como fantasmas suyos. Sería inclinar la comparación a favor del
    cancelador con un detalle de implementación.
    """
    reproductor = _reproducir(video)
    if not _esperar_eco(int(audio.vad.piso_actual())):
        reproductor.terminate(); reproductor.wait()
        return {}, {}
    _cuenta_regresiva(intento, total, frase)
    grabador = _GrabadorCrudo()
    grabador.start()
    con_aec = audio.escuchar_multilingue(_TIMEOUT, idiomas)
    crudo_pcm = grabador.detener()
    reproductor.terminate(); reproductor.wait()
    return con_aec, _decodificar(crudo_pcm, idiomas)


def _buscar_video() -> str | None:
    videos = sorted(glob.glob("media/videos/*/*.mp4"))
    return videos[0] if videos else None


def main() -> int:
    print("\n=== ¿MEXA ENTIENDE A QUIEN LE HABLA ENCIMA? ===\n")
    idiomas = _idiomas_disponibles()
    if not idiomas:
        print("  No hay ningún modelo Vosk instalado.")
        return 1
    video = _buscar_video()
    if video is None:
        print("  No hay ningún video en media/videos/ para generar el eco.")
        return 1

    nodo, _ = audio._obtener_dispositivo()
    print(f"  MEXA escucha por: {nodo}")
    print(f"  Frase de activación: \"{_FRASE}\"\n")

    piso = audio.calibrar_ruido_ambiente(2.0)

    # ---------- CONTROL: sin eco, ¿te entiende? ----------
    # Sin esta vara, un fracaso en el barge-in no se puede atribuir: podría
    # ser el eco, o podría ser que estés lejos o hablando bajo.
    print(f"\nCONTROL — MEXA CALLADA. Vas a decir \"{_FRASE}\".")
    input("  Enter para empezar... ")
    _cuenta_regresiva(1, 1, _FRASE)
    control = audio.escuchar_multilingue(_TIMEOUT, idiomas)
    desperto_control, _ = _mostrar("con cancelador", control)
    if not desperto_control:
        print(f"\n  MEDICIÓN INVÁLIDA: MEXA no te entiende NI CON SILENCIO.")
        print("  El problema no es el eco. Acercate, hablá más fuerte o")
        print("  revisá el umbral con tests/calibrar_umbral_voz.py.")
        return 6

    # ---------- FALSO POSITIVO: ¿se despierta sola? ----------
    print(f"\nFALSO POSITIVO — MEXA suena sola. NO HABLES.")
    print(f"  {_INTENTOS} intentos. Nadie debería despertar a nadie.")
    input("  Enter para empezar... ")

    falsos_aec = falsos_crudo = 0
    for intento in range(1, _INTENTOS + 1):
        con_aec, sin_aec = _ronda(video, idiomas, intento, _INTENTOS, None)
        if not con_aec:
            print("\n  MEDICIÓN INVÁLIDA: el parlante no llegó al micrófono.")
            return 6
        falsos_aec   += _mostrar("con cancelador", con_aec)[0]
        falsos_crudo += _mostrar("micrófono crudo", sin_aec)[0]

    # ---------- BARGE-IN: ¿te oye por encima de sí misma? ----------
    print(f"\nBARGE-IN — MEXA va a sonar y vos vas a decir \"{_FRASE}\" encima.")
    print(f"  {_INTENTOS} intentos. Esperá el ¡AHORA! de cada uno.")
    input("  Enter para empezar... ")

    aciertos_aec = aciertos_crudo = 0
    fantasma_aec = fantasma_crudo = 0
    for intento in range(1, _INTENTOS + 1):
        con_aec, sin_aec = _ronda(video, idiomas, intento, _INTENTOS, _FRASE)
        if not con_aec:
            print("\n  MEDICIÓN INVÁLIDA: el parlante no llegó al micrófono.")
            return 6
        ok_a, f_a = _mostrar("con cancelador", con_aec)
        ok_c, f_c = _mostrar("micrófono crudo", sin_aec)
        aciertos_aec += ok_a; fantasma_aec += f_a
        aciertos_crudo += ok_c; fantasma_crudo += f_c

    # ---------- PREGUNTA: la tarea que de verdad importa ----------
    # Despertar es keyword spotting: basta con que UNA palabra zafe entre
    # ruido. Después de despertar MEXA transcribe preguntas para el LLM, y
    # ahí las palabras que sobran arruinan la frase. Esta es la medida que
    # el wake word no puede dar.
    print(f"\nPREGUNTA — MEXA suena y vos preguntás: \"{_PREGUNTA}\"")
    print(f"  {_INTENTOS} intentos. Decila completa y de un tirón.")
    input("  Enter para empezar... ")

    pal_aec = pal_crudo = esperadas_tot = 0
    ruido_aec = ruido_crudo = 0
    for intento in range(1, _INTENTOS + 1):
        con_aec, sin_aec = _ronda(video, idiomas, intento, _INTENTOS, _PREGUNTA)
        if not con_aec:
            print("\n  MEDICIÓN INVÁLIDA: el parlante no llegó al micrófono.")
            return 6
        for etiqueta, textos in (("con cancelador", con_aec),
                                 ("micrófono crudo", sin_aec)):
            # Sólo el modelo español: la pregunta se dice en español y el
            # modelo inglés sobre audio español sólo aporta alucinaciones.
            aciertos, esperadas, fantasma = _exactitud(textos.get("es", ""),
                                                       _PREGUNTA)
            print(f"    {etiqueta:<22} {aciertos}/{esperadas} palabras  "
                  f"[{fantasma:2d} fantasma]  \"{textos.get('es', '') or '(nada)'}\"")
            if etiqueta == "con cancelador":
                pal_aec += aciertos; ruido_aec += fantasma
                esperadas_tot += esperadas
            else:
                pal_crudo += aciertos; ruido_crudo += fantasma

    # ---------- VEREDICTO ----------
    print("\n--- VEREDICTO ---")
    print(f"  el visitante DESPERTÓ a MEXA   con cancelador {aciertos_aec}/{_INTENTOS}"
          f"   sin cancelador {aciertos_crudo}/{_INTENTOS}")
    print(f"  MEXA se despertó SOLA          con cancelador {falsos_aec}/{_INTENTOS}"
          f"   sin cancelador {falsos_crudo}/{_INTENTOS}")
    print(f"  PREGUNTA, palabras acertadas   con cancelador {pal_aec}/{esperadas_tot}"
          f"   sin cancelador {pal_crudo}/{esperadas_tot}")
    print(f"  PREGUNTA, palabras FANTASMA    con cancelador {ruido_aec}"
          f"   sin cancelador {ruido_crudo}")

    mayoria = _INTENTOS // 2 + 1

    # El falso positivo se juzga PRIMERO: una MEXA que se interrumpe sola a
    # mitad del video es peor que una que no puede ser interrumpida. El
    # visitante no lo lee como "no me escuchó" sino como "se volvió loca".
    if falsos_aec > 0:
        print("\n  NO SIRVE — MEXA SE DESPIERTA SOLA: oye su propio audio y")
        print("  lo toma por un visitante. Dejarla escuchando mientras habla")
        print("  la haría interrumpirse a sí misma a mitad del video.")
        return 8

    if aciertos_aec < mayoria:
        print("\n  NO SIRVE: MEXA no entiende a quien le habla encima, ni")
        print("  siquiera con el cancelador. El barge-in no es viable por")
        print("  esta vía — la voz sobrevive en energía pero no en contenido.")
        return 7

    if pal_aec < pal_crudo:
        print("\n  SIRVE, PERO EL CANCELADOR NO ES LO QUE LO LOGRA: el")
        print("  micrófono crudo transcribe la pregunta MEJOR. El eco no")
        print("  molestaba tanto como se creía; revisar si vale la pena.")
        return 0

    if ruido_crudo > ruido_aec * 2:
        print("\n  SIRVE, Y ES EL CANCELADOR. Los dos caminos pueden")
        print(f"  despertarla —para eso basta UNA palabra— pero el crudo mete")
        print(f"  {ruido_crudo} palabras que nadie dijo contra {ruido_aec} del")
        print("  cancelador. Esa diferencia no se ve al despertar y arruina")
        print("  la pregunta que viene después: el LLM recibiría basura.")
        return 0

    print("\n  SIRVE: MEXA entiende al visitante que le habla encima, y no")
    print("  se confunde consigo misma. El barge-in es viable.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCortado.")
        sys.exit(130)
