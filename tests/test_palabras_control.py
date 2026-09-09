"""
Test de las PALABRAS DE CONTROL: cuándo "no" es una respuesta y cuándo es
parte de una pregunta.

EL PROBLEMA QUE RESUELVE. MEXA pregunta "¿tienes alguna pregunta?" y escucha
con VOCABULARIO ABIERTO: lo que vuelve puede ser una respuesta corta ("no",
"nada") o una pregunta entera. `_dijo` matchea por palabra completa en
CUALQUIER parte de la frase, así que "¿por qué NO usaban la rueda?" — una
pregunta legítima sobre Mesoamérica — se leía como "no tengo preguntas" y MEXA
se despedía. Peor: "¿cuándo va a TERMINAR el video?" APAGABA el robot.

LA DISTINCIÓN. Un "no" solo significa "no tengo preguntas". Un "no" adentro de
seis palabras significa lo contrario: ES la pregunta. Por eso `_es_respuesta`
exige que la frase SEA esa respuesta —lo que sobra tiene que ser cortesía—
en vez de apenas contenerla.

ASIMETRÍA DE COSTOS, que es la que fija el criterio. Irse de más es caro: MEXA
abandona a un visitante que estaba preguntando. Irse de menos es barato: MEXA
contesta de más y el visitante dice "adiós" o se va, y el PIR lo resuelve. Ante
la duda, NO irse.

Corre sin micrófono ni robot (carga los modelos por el import de dialogo):
  python3 tests/test_palabras_control.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.dialogo import (_es_respuesta, _PALABRAS_APAGAR, _PALABRAS_SALIDA,
                             _PALABRAS_REINICIO)


def _accion(frase):
    """La misma cadena de decisión que _ciclo_preguntas, en el mismo orden."""
    if _es_respuesta(frase, _PALABRAS_REINICIO):
        return "REINICIAR"
    if _es_respuesta(frase, _PALABRAS_APAGAR):
        return "APAGAR"
    if _es_respuesta(frase, _PALABRAS_SALIDA):
        return "SALIR"
    return "RESPONDER"


# ── Preguntas REALES que MEXA tiene que contestar, no huir de ellas ──
# Todas éstas disparaban una acción de control antes del arreglo.

def test_pregunta_con_no_se_responde():
    assert _accion("por qué no usaban la rueda") == "RESPONDER"
    assert _accion("los mayas no tenían escritura") == "RESPONDER"
    assert _accion("no entendí, me lo repites") == "RESPONDER"
    assert _accion("qué comían, no sé si sembraban maíz") == "RESPONDER"


def test_pregunta_con_nada_se_responde():
    assert _accion("no sé nada de los olmecas, cuéntame") == "RESPONDER"


def test_pregunta_con_terminar_NO_apaga_a_mexa():
    """El peor de todos: apagaba el robot entero en plena visita."""
    assert _accion("cuándo va a terminar el video") == "RESPONDER"
    assert _accion("cómo hicieron para terminar la pirámide") == "RESPONDER"


def test_pregunta_con_empecemos_no_reinicia():
    assert _accion("empecemos por los mayas si te parece") == "RESPONDER"


def test_pregunta_en_ingles_con_no_se_responde():
    assert _accion("did they have no writing system") == "RESPONDER"
    assert _accion("why did they not use the wheel") == "RESPONDER"


# ── Respuestas de verdad: lo que SÍ tiene que seguir funcionando ──

def test_respuestas_cortas_de_salida():
    for frase in ("no", "nada", "ninguna", "no gracias", "adios", "adiós",
                  "hasta luego", "bye", "goodbye", "see you", "nothing",
                  "none", "no thanks"):
        assert _accion(frase) == "SALIR", frase


def test_salida_con_cortesia_alrededor():
    # Lo que sobra es cortesía, no contenido: sigue siendo una despedida.
    assert _accion("no, gracias") == "SALIR"
    assert _accion("no muchas gracias") == "SALIR"
    assert _accion("adios mexa") == "SALIR"
    assert _accion("no, thank you") == "SALIR"
    assert _accion("nada, gracias") == "SALIR"
    assert _accion("no, nada") == "SALIR"


def test_apagado_deliberado_sigue_funcionando():
    for frase in ("terminar", "terminemos", "shut down", "shutdown", "power off"):
        assert _accion(frase) == "APAGAR", frase


def test_reinicio_deliberado_sigue_funcionando():
    for frase in ("empecemos", "empecemos de nuevo", "empezar de nuevo",
                  "reiniciar", "start over", "start again", "restart"):
        assert _accion(frase) == "REINICIAR", frase


def test_el_orden_de_prioridad_se_respeta():
    # "empecemos de nuevo" contiene "empecemos"; gana REINICIAR igual.
    assert _accion("empecemos de nuevo") == "REINICIAR"


def test_preguntas_normales_no_disparan_nada():
    for frase in ("cuéntame de los aztecas", "tell me about the mayas",
                  "qué comían los olmecas", "how tall is the pyramid"):
        assert _accion(frase) == "RESPONDER", frase


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
