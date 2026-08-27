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
from modulos.dialogo import _PALABRAS_ACTIVACION, _dijo

_FRASE    = "comencemos"
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


def _desperto(textos: dict[str, str]) -> bool:
    """La decisión REAL de MEXA, no una aproximación."""
    return any(_dijo(t, _PALABRAS_ACTIVACION) for t in textos.values())


def _mostrar(etiqueta: str, textos: dict[str, str]) -> bool:
    ok = _desperto(textos)
    oido = " | ".join(f"{i}: {t or '(nada)'}" for i, t in textos.items())
    print(f"    {etiqueta:<22} {'DESPIERTA' if ok else 'no despierta':<13} {oido}")
    return ok


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
    print(f"\nCONTROL — MEXA CALLADA. Decí \"{_FRASE}\" cuando aparezca ¡AHORA!")
    input("  Enter para empezar... ")
    print("  ¡AHORA!")
    control = audio.escuchar_multilingue(_TIMEOUT, idiomas)
    if not _mostrar("con cancelador", control):
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
        reproductor = _reproducir(video)
        if not _esperar_eco(int(audio.vad.piso_actual())):
            reproductor.terminate(); reproductor.wait()
            print("\n  MEDICIÓN INVÁLIDA: el parlante no llegó al micrófono.")
            return 6
        grabador = _GrabadorCrudo()
        grabador.start()
        print(f"\n  intento {intento}/{_INTENTOS} — callado")
        sola_aec = audio.escuchar_multilingue(_TIMEOUT, idiomas)
        crudo_pcm = grabador.detener()
        reproductor.terminate(); reproductor.wait()
        falsos_aec   += _mostrar("con cancelador", sola_aec)
        falsos_crudo += _mostrar("micrófono crudo",
                                 _decodificar(crudo_pcm, idiomas))

    # ---------- BARGE-IN: los dos a la vez, tres veces ----------
    print(f"\nBARGE-IN — MEXA va a sonar y vos vas a decir \"{_FRASE}\" encima.")
    print(f"  {_INTENTOS} intentos. Esperá el ¡AHORA! de cada uno.")
    input("  Enter para empezar... ")

    aciertos_aec = aciertos_crudo = 0
    for intento in range(1, _INTENTOS + 1):
        reproductor = _reproducir(video)
        if not _esperar_eco(int(audio.vad.piso_actual())):
            reproductor.terminate(); reproductor.wait()
            print("\n  MEDICIÓN INVÁLIDA: el parlante no llegó al micrófono.")
            return 6

        grabador = _GrabadorCrudo()
        grabador.start()
        print(f"\n  intento {intento}/{_INTENTOS} — ¡AHORA!")
        con_aec = audio.escuchar_multilingue(_TIMEOUT, idiomas)
        crudo_pcm = grabador.detener()
        reproductor.terminate(); reproductor.wait()

        sin_aec = _decodificar(crudo_pcm, idiomas)
        aciertos_aec   += _mostrar("con cancelador", con_aec)
        aciertos_crudo += _mostrar("micrófono crudo", sin_aec)

    # ---------- VEREDICTO ----------
    print("\n--- VEREDICTO ---")
    print(f"  el visitante DESPERTÓ a MEXA   con cancelador {aciertos_aec}/{_INTENTOS}"
          f"   sin cancelador {aciertos_crudo}/{_INTENTOS}")
    print(f"  MEXA se despertó SOLA          con cancelador {falsos_aec}/{_INTENTOS}"
          f"   sin cancelador {falsos_crudo}/{_INTENTOS}")

    mayoria = _INTENTOS // 2 + 1

    # El falso positivo se juzga PRIMERO: una MEXA que se interrumpe sola
    # a mitad del video es peor que una que no puede ser interrumpida.
    # Escuchar mientras habla sólo tiene sentido si no se confunde consigo
    # misma, y este error no lo ve el visitante como "no me escuchó" sino
    # como "se volvió loca".
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
    if aciertos_crudo >= mayoria:
        print("\n  SIRVE, PERO EL CANCELADOR NO ES LO QUE LO LOGRA: el")
        print("  micrófono crudo entiende casi igual. El eco no molestaba")
        print("  tanto como se creía. Revisar si vale la pena el AEC.")
        return 0
    print("\n  SIRVE, Y ES EL CANCELADOR: con él MEXA entiende al visitante")
    print("  que le habla encima; sin él, no. El barge-in es viable.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCortado.")
        sys.exit(130)
