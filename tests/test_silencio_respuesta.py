# ============================================================
#  MEXA — Cuánto espera antes de darse por contestada
#
#  MEXA tiene DOS tiempos de silencio configurables —respuesta cerrada
#  y pregunta abierta— que HOY valen lo mismo (0.9 s), porque se pidió
#  que todo el robot respondiera igual de rápido. El cableado se
#  mantiene separado a propósito: son casos con tolerancias distintas y
#  volver a separarlos tiene que costar cambiar un número.
#
#  Este test cuida lo que importa de ese compromiso:
#
#    1. Ninguna espera se va por encima de la que se decidió (si sube,
#       el robot volvió a sentirse lento y nadie se enteró).
#    2. Y ninguna corta tan pronto como para truncar a alguien que
#       duda: "los... eh... olmecas" es una frase de museo normal.
#    3. Y el cableado sigue en su lugar: cada camino pide la espera que
#       le corresponde, así separarlos de nuevo es cambiar un número.
#
#  No necesita micrófono ni audio: `_SeguimientoHabla` recibe BOOLEANOS
#  ("hay voz en este chunk"), así que la regla de tiempo se prueba con
#  escenas armadas, exactamente como recomienda su propia docstring.
#
#  Correr con:  python3 tests/test_silencio_respuesta.py
# ============================================================

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.vad import SILENCIO_CERRADO, _SILENCIO_SEG, _SeguimientoHabla

_PASO = 0.032          # 512 muestras a 16 kHz: el chunk que ve el VAD
_TOLERANCIA = 0.05


def _cortar(silencio, escena) -> float | None:
    """Corre una escena [(segundos, hay_voz), ...] y devuelve cuándo cortó."""
    seguimiento = _SeguimientoHabla(silencio)
    t = 0.0
    for duracion, hay_voz in escena:
        fin = t + duracion
        while t < fin:
            if seguimiento.observar(hay_voz, t):
                return t
            t += _PASO
    return None


def _check(ok: bool, texto: str, fallos: list) -> None:
    print(f"  {'PASA ' if ok else 'FALLA'}  {texto}")
    if not ok:
        fallos.append(texto)


def main() -> int:
    fallos: list[str] = []
    print(f"abierta/wake word={_SILENCIO_SEG}s  cerrada={SILENCIO_CERRADO}s\n")

    # 1. Una palabra y listo: nadie puede tardar más de lo decidido.
    #    El techo es 1.2 s porque a partir de ahí la espera se NOTA: es el
    #    valor viejo (1.5 s) el que motivó todo este trabajo.
    TECHO = 1.2
    escena = [(0.5, False), (1.0, True), (4.0, False)]
    fin_habla = 1.5
    for etiqueta, silencio in (("pregunta abierta / wake word", _SILENCIO_SEG),
                               ("respuesta cerrada", SILENCIO_CERRADO)):
        corte = _cortar(silencio, escena)
        demora = corte - fin_habla
        _check(demora <= TECHO,
               f"{etiqueta}: corta +{demora:.2f}s tras la última palabra "
               f"(techo {TECHO}s)", fallos)

    # 2. El que duda: no se le puede cortar la respuesta a la mitad.
    #    La pausa se elige con margen bajo SILENCIO_CERRADO a propósito: sobre
    #    audio real, Silero da por terminada la voz un poco antes que el corte
    #    nominal, así que apretarse contra el límite no sobrevive al ruido.
    for etiqueta, silencio in (("pregunta abierta / wake word", _SILENCIO_SEG),
                               ("respuesta cerrada", SILENCIO_CERRADO)):
        pausa = round(silencio - 0.3, 2)
        escena = [(0.4, False), (0.6, True), (pausa, False), (0.8, True), (3.0, False)]
        fin_real = 0.4 + 0.6 + pausa + 0.8
        corte = _cortar(silencio, escena)
        _check(corte is not None and corte >= fin_real - _TOLERANCIA,
               f"{etiqueta}: 'los... eh... olmecas' (pausa de {pausa}s) no se "
               f"trunca (corta {corte:.2f}s, termina {fin_real:.2f}s)", fallos)

    # 3. Sin habla previa no se corta nunca: el silencio inicial no cuenta.
    _check(_cortar(SILENCIO_CERRADO, [(5.0, False)]) is None,
           "silencio puro no dispara el corte (se espera al timeout)", fallos)

    # 4. El cableado: quién pide cada tiempo.
    print()
    import modulos.modulo_audio as A
    visto = {}

    def _falso_escuchar(timeout, recognizers, silencio=None):
        visto["silencio"] = silencio
        return {clave: "" for clave in recognizers}

    A._escuchar         = _falso_escuchar
    A._cargar_modelo    = lambda idioma="es": object()
    A.modelo_disponible = lambda idioma: True
    A.KaldiRecognizer   = lambda *a, **k: object()

    A.escuchar_idioma(timeout=1)
    _check(visto.get("silencio") == SILENCIO_CERRADO,
           f"escuchar_idioma pide la espera corta (pidió {visto.get('silencio')})", fallos)

    A.escuchar_multilingue(1, ["es"], {"es": '["maya"]'})
    _check(visto.get("silencio") == SILENCIO_CERRADO,
           f"civilizaciones (con gramática) pide la corta (pidió {visto.get('silencio')})",
           fallos)

    A.escuchar_multilingue(1, ["es"])
    _check(visto.get("silencio") is None,
           f"wake word (sin gramática) usa el valor por defecto del VAD "
           f"(pidió {visto.get('silencio')}), no uno propio", fallos)

    print()
    if fallos:
        print(f"{len(fallos)} FALLA(S):")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("Todo bien: ninguna espera pasa el techo, ninguna trunca al que duda.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
