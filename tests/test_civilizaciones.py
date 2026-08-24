"""
MEXA — Verificación de la elección de civilización por voz.

QUÉ PRUEBA
----------
El paso donde el visitante contesta "¿sobre cuál civilización quieres
aprender?". Desde que se oye con los DOS modelos y gramática cerrada, ese
paso depende de tres cosas que este test vigila:

  1. GRAMÁTICA VÁLIDA — cada palabra de `GRAMATICA_CIVILIZACIONES` debe
     existir en el léxico de SU modelo. Una palabra fuera del léxico rompe
     la gramática entera, y el error no se ve leyendo el código.

  2. ACIERTO — el visitante dice el nombre y MEXA proyecta ESE video.
     Se prueba el nombre en español y en inglés, cada uno con su voz, sobre
     audio limpio y degradado a condiciones de sala.

  3. QUE NO SE EQUIVOQUE — la gramática cerrada le quita al decodificador la
     posibilidad de decir "esto no estaba en la lista": forzado a elegir,
     contesta la opción más parecida. Un CRUZADO (proyectar el video de otra
     civilización) es el fallo caro; un MUDO sólo cuesta una repregunta.

Correr con:  python3 tests/test_civilizaciones.py

OJO: usa TTS de estudio, que pronuncia mejor que cualquier visitante. Lo que
falla acá falla seguro en la sala; lo que pasa acá todavía hay que confirmarlo
con `python3 tests/calibrar_vocabulario.py mic`.
"""

import audioop
import importlib.util
import json
import os
import random
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vosk import KaldiRecognizer, SetLogLevel

from modulos import contenido
from modulos.modulo_audio import _VOSK_RATE, _cargar_modelo, modelo_disponible

SetLogLevel(-1)

# (nombre canónico, cómo lo pide un hispanohablante, cómo lo pide un angloparlante)
CASOS = [
    ("los Mayas",       "los mayas",       "the mayas"),
    ("los Aztecas",     "los aztecas",     "the aztecs"),
    ("Teotihuacán",     "teotihuacán",     "teotihuacan"),
    ("los Olmecas",     "los olmecas",     "the olmecs"),
    ("los Toltecas",    "los toltecas",    "tula"),
    ("los Zapotecas",   "los zapotecas",   "the zapotecs"),
    ("los Mixtecas",    "los mixtecas",    "the mixtecs"),
]

# Condiciones de sala: de estudio a micrófono lejano con ruido.
CONDICIONES = [("limpio", 0.0, 1.0), ("ruido .06", 0.06, 0.55),
               ("ruido .10", 0.10, 0.42), ("ruido .14", 0.14, 0.35)]


def _sintetizador():
    """Toma `_sintetizar` de test_idioma.py — fuente única de síntesis.

    Por ruta y no con `from tests.test_idioma import ...`: hay un paquete
    `tests` de terceros en site-packages que secuestra el nombre.
    """
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_idioma.py")
    spec = importlib.util.spec_from_file_location("_mexa_test_idioma", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._sintetizar


def _degradar(pcm: bytes, ruido: float, ganancia: float, semilla: int = 7) -> bytes:
    """Atenúa y ensucia. Semilla fija: el test no puede ser intermitente."""
    if ganancia != 1.0:
        pcm = audioop.mul(pcm, 2, ganancia)
    if ruido <= 0:
        return pcm
    n = len(pcm) // 2
    rng = random.Random(semilla)
    amp = int(32767 * ruido)
    sucio = [max(-32768, min(32767, m + rng.randint(-amp, amp)))
             for m in struct.unpack(f"<{n}h", pcm)]
    return struct.pack(f"<{n}h", *sucio)


def _oir_con_ambos(pcm: bytes, gramaticas: dict[str, str]) -> dict[str, str]:
    """Replica `escuchar_multilingue` sin micrófono: mismo audio a cada modelo."""
    textos = {}
    for idioma, gram in gramaticas.items():
        if not modelo_disponible(idioma):
            continue
        rec = KaldiRecognizer(_cargar_modelo(idioma), _VOSK_RATE, gram)
        rec.AcceptWaveform(pcm)
        textos[idioma] = json.loads(rec.FinalResult()).get("text", "").strip()
    return textos


def probar_gramatica() -> list[str]:
    """Cada palabra de la gramática debe vivir en el léxico de su modelo."""
    print("1) GRAMÁTICA vs LÉXICO")
    errores = []
    for idioma, palabras in contenido.GRAMATICA_CIVILIZACIONES.items():
        if not modelo_disponible(idioma):
            print(f"   [{idioma}] sin modelo instalado, se omite")
            continue
        modelo = _cargar_modelo(idioma)
        muertas = [p for p in palabras if p != "[unk]"
                   and any(modelo.vosk_model_find_word(w) == -1 for w in p.split())]
        if muertas:
            errores.append(f"[{idioma}] fuera del léxico: {', '.join(muertas)}")
            print(f"   FALLA [{idioma}] fuera del léxico: {', '.join(muertas)}")
        else:
            print(f"   OK    [{idioma}] {len(palabras) - 1} palabras, todas en el léxico")
    return errores


def probar_reconocimiento() -> tuple[dict, list[str]]:
    """Mide acierto / mudo / cruzado sobre todas las civilizaciones."""
    print("\n2) RECONOCIMIENTO (dos modelos + gramática cerrada)")
    sintetizar = _sintetizador()
    gramaticas = {i: json.dumps(g)
                  for i, g in contenido.GRAMATICA_CIVILIZACIONES.items()}

    conteo = {"OK": 0, "MUDO": 0, "CRUZADO": 0}
    cruzados = []
    for nombre, frase_es, frase_en in CASOS:
        celdas = []
        for lang, frase in (("es", frase_es), ("en", frase_en)):
            base = sintetizar(frase, lang)
            for etiqueta, ruido, ganancia in CONDICIONES:
                pcm = _degradar(base, ruido, ganancia)
                textos = _oir_con_ambos(pcm, gramaticas)
                elegido = contenido.detectar_civilizacion_multi(textos, lang)
                obtenido = elegido[1] if elegido else None

                if obtenido == nombre:
                    estado = "OK"
                elif obtenido is None:
                    estado = "MUDO"
                else:
                    estado = "CRUZADO"
                    cruzados.append(
                        f"[{lang}/{etiqueta}] {frase!r} → {obtenido} "
                        f"(esperado {nombre}); oyó {textos}")
                conteo[estado] += 1
                celdas.append(estado[:4])
        print(f"   {nombre:<16} es[{' '.join(f'{c:<4}' for c in celdas[:4])}]"
              f" en[{' '.join(f'{c:<4}' for c in celdas[4:])}]")
    return conteo, cruzados


def main() -> int:
    """Contrato del test, por severidad:

    CRÍTICO  → gramática inválida, o un CRUZADO. Proyectar el video que nadie
               pidió es el peor final posible: el visitante no tiene forma de
               saber que MEXA se equivocó, y se lleva la civilización que no era.
    TOLERADO → MUDO. Es el camino de repregunta que el diálogo ya contempla:
               cuesta unos segundos y el visitante repite.

    La distinción no maquilla el rojo: equivocarse y repreguntar cuestan
    cosas distintas, y el diseño elige repreguntar.
    """
    errores = probar_gramatica()
    conteo, cruzados = probar_reconocimiento()

    total = sum(conteo.values())
    print(f"\n   acierto {conteo['OK']}/{total}   "
          f"mudo {conteo['MUDO']} (tolerado)   CRUZADO {conteo['CRUZADO']}")

    if cruzados:
        print("\n   CRUZADOS — proyectan el video equivocado:")
        for c in cruzados:
            print(f"     {c}")
    if errores:
        print("\n   GRAMÁTICA INVÁLIDA:")
        for e in errores:
            print(f"     {e}")

    critico = bool(errores) or conteo["CRUZADO"] > 0
    print(f"\n{'FALLA' if critico else 'PASA'} — "
          f"{conteo['CRUZADO']} cruzado(s), {len(errores)} error(es) de gramática")
    return 1 if critico else 0


if __name__ == "__main__":
    sys.exit(main())
