"""
Test de que la base de conocimiento responde EN LOS DOS IDIOMAS.

EL PROBLEMA QUE RESUELVE. MEXA contesta las preguntas libres con
`llama3.2:1b` — mil millones de parámetros, un modelo diminuto. En español
funciona porque `buscar_contexto()` le inyecta HECHOS VERIFICADOS y el modelo
apenas los reformula. Sin esos hechos, un modelo de ese tamaño improvisa.

Y las 170 palabras clave de `conocimiento.py` estaban TODAS en español. Medido
antes del arreglo, con la transcripción PERFECTA en inglés:

    what did the aztecs eat      -> SIN CONTEXTO
    who were the olmecs          -> SIN CONTEXTO
    tell me about the toltecs    -> SIN CONTEXTO
    what about the zapotecs      -> SIN CONTEXTO
    were the mixtecs farmers     -> SIN CONTEXTO
    tell me about the mayas      -> contexto (coincidencia ortográfica)
    where is teotihuacan         -> contexto (coincidencia ortográfica)

Seis de ocho sin un solo hecho. Lo que el visitante vive como "MEXA no me
entiende en inglés" NO es el reconocimiento de voz: es que se queda muda de
contenido y el modelito rellena con lo que puede.

Corre sin micrófono, sin robot y sin Ollama:
  python3 tests/test_conocimiento_bilingue.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.conocimiento import _BASE, _resumir, buscar_contexto


# Una pregunta REAL por tema, en los dos idiomas. Escritas como las diría un
# visitante, no como las escribiría un programador buscando que pasen.
PREGUNTAS = {
    "teotihuacan":    ("dónde queda teotihuacán",       "where is teotihuacan"),
    "aztecas":        ("qué comían los aztecas",        "what did the aztecs eat"),
    "mayas":          ("háblame de los mayas",          "tell me about the mayas"),
    "olmecas":        ("quiénes eran los olmecas",      "who were the olmecs"),
    "toltecas":       ("háblame de los toltecas",       "tell me about the toltecs"),
    "zapotecas":      ("qué hacían los zapotecas",      "what about the zapotecs"),
    "mixtecas":       ("los mixtecas eran agricultores", "were the mixtecs farmers"),
    "independencia":  ("cuándo fue la independencia",   "when was mexican independence"),
    "revolucion":     ("qué fue la revolución mexicana", "what was the mexican revolution"),
    "mexico_general": ("háblame de méxico",             "tell me about mexico"),
}


def test_hay_una_pregunta_por_cada_tema():
    """Si alguien agrega un tema, este test lo obliga a cubrirlo acá."""
    temas = {t["tema"] for t in _BASE}
    assert temas == set(PREGUNTAS), (
        f"temas sin pregunta de prueba: {temas - set(PREGUNTAS)}; "
        f"preguntas sin tema: {set(PREGUNTAS) - temas}")


def _trae_su_propio_tema(tema: str, pregunta: str) -> bool:
    """¿El contexto devuelto incluye los hechos DE ESE tema?

    No alcanza con preguntar "¿vino algo?". `buscar_contexto` matchea por
    SUBCADENA, así que "mexican" contiene "mexica" y una pregunta sobre la
    Revolución Mexicana en inglés devolvía, feliz, los hechos de los AZTECAS.
    Un test que sólo mira si la respuesta está vacía da verde con el tema
    equivocado — y eso es peor que dar rojo.
    """
    propios = next(_resumir(e["hechos"]) for e in _BASE if e["tema"] == tema)
    return propios in buscar_contexto(pregunta)


def test_todos_los_temas_responden_en_espanol():
    mudos = [tema for tema, (es, _en) in PREGUNTAS.items()
             if not _trae_su_propio_tema(tema, es)]
    assert not mudos, f"temas que no traen SUS hechos en español: {mudos}"


def test_todos_los_temas_responden_en_INGLES():
    """El que fallaba en 7 de 10 temas.

    Sin contexto, `llama3.2:1b` contesta sobre historia mesoamericana sin un
    solo hecho verificado. En español nunca pasó porque las claves estaban en
    español; en inglés pasaba casi siempre.
    """
    mudos = [tema for tema, (_es, en) in PREGUNTAS.items()
             if not _trae_su_propio_tema(tema, en)]
    assert not mudos, f"temas que no traen SUS hechos en INGLÉS: {mudos}"


def test_mexican_no_arrastra_los_hechos_de_los_aztecas():
    """La trampa de la subcadena, otra vez: "mexica" vive dentro de "mexican".

    Preguntar por la Revolución Mexicana en inglés devolvía los hechos de los
    AZTECAS. Es el mismo footgun que `detectar_civilizacion` ya había pagado
    ("mexica" dentro de "mexicana" proyectaba el video de los Aztecas), y la
    solución es la misma: comparar por PALABRA COMPLETA.
    """
    aztecas = next(_resumir(e["hechos"]) for e in _BASE if e["tema"] == "aztecas")
    for pregunta in ("what was the mexican revolution",
                     "when was mexican independence",
                     "i love mexican food"):
        assert aztecas not in buscar_contexto(pregunta), pregunta


def test_cada_tema_tiene_alguna_clave_en_ingles():
    """La REGLA: ningún tema puede depender de que el inglés y el español se
    escriban igual. 'mayas' y 'teotihuacan' coinciden por casualidad — el
    resto no, y esa casualidad no es una estrategia.
    """
    sin_ingles = []
    for entrada in _BASE:
        claves = {c.lower() for c in entrada["palabras_clave"]}
        # una clave "en inglés" es la que hace match con la pregunta inglesa
        pregunta = PREGUNTAS[entrada["tema"]][1].lower()
        if not any(c in pregunta for c in claves):
            sin_ingles.append(entrada["tema"])
    assert not sin_ingles, f"temas inalcanzables en inglés: {sin_ingles}"


def main():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"  OK  {prueba.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"FALLO {prueba.__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasaron.")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
