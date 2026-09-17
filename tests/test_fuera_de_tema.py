"""
Test de que MEXA SÓLO habla de las siete civilizaciones — y de que igual
entiende los seguimientos.

EL PROBLEMA QUE RESUELVE. La restricción "hablá sólo de las civilizaciones"
vivía en el prompt de sistema de `modulo_ia.py`, redactada como prohibición
negativa dirigida a `llama3.2:1b`. Un modelo de mil millones de parámetros no
la sostiene, y peor: si `buscar_contexto()` no encontraba palabras clave,
devolvía "" y la pregunta llegaba al modelo SIN UN SOLO HECHO. Ahí no hay
barrera, hay una máquina de improvisar.

Y arreglarlo con el candado obvio —"si no nombra una civilización, rechazá"—
rompía la otra mitad de la conversación: "¿y quién la construyó?" no nombra
nada. Por eso el filtro tiene DOS PASOS y el orden es el diseño:

    1. ¿nombra una civilización?  -> ese tema, y la lista negra NO se aplica
    2. ¿no?                       -> hereda el tema anterior, salvo dominio ajeno

Lo que este test cuida es justamente el borde entre los dos: que un
seguimiento legítimo no se rechace, y que una palabra de la lista negra no
se coma una pregunta real. El caso testigo es "mundial": suena a fútbol, pero
"¿es Patrimonio Mundial?" está literalmente en los hechos de Teotihuacán.

Corre sin micrófono, sin robot y sin Ollama:
  python3 tests/test_fuera_de_tema.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos import contenido
from modulos.conocimiento import (_BASE, _DOMINIOS_AJENOS, _IDENTIDAD,
                                  CIVILIZACIONES_VALIDAS, contexto_de,
                                  es_pregunta_de_identidad, resolver_tema)


# ── Las siete, nombradas explícitamente ──────────────────────
# Una pregunta por civilización, como la diría un visitante.
NOMBRADAS = {
    "teotihuacan": ("dónde queda teotihuacán",       "where is teotihuacan"),
    "aztecas":     ("qué comían los aztecas",        "what did the aztecs eat"),
    "mayas":       ("háblame de los mayas",          "tell me about the mayas"),
    "olmecas":     ("quiénes eran los olmecas",      "who were the olmecs"),
    "toltecas":    ("háblame de los toltecas",       "tell me about the toltecs"),
    "zapotecas":   ("qué hacían los zapotecas",      "what about the zapotecs"),
    "mixtecas":    ("los mixtecas eran agricultores", "were the mixtecs farmers"),
}

# ── Seguimientos ─────────────────────────────────────────────
# Preguntas SIN nombre propio, que sólo significan algo si se hereda el tema.
# Son la mitad real de la conversación: nadie repite "los mayas" cinco veces.
SEGUIMIENTOS = [
    "¿y quién la construyó?",
    "¿cuándo fue?",
    "¿por qué?",
    "¿y cómo escribían?",
    "¿cuánta gente vivía ahí?",
    "¿qué les pasó?",
    "and how did they write?",
    "who built it?",
    "why did they disappear?",
]

# ── Fuera de tema ────────────────────────────────────────────
# Lo que un visitante de museo pregunta de verdad cuando se va del tema.
AJENAS = [
    "¿quién ganó la copa del mundo?",
    "¿qué hora es?",
    "¿cómo está el clima?",
    "¿tienes wifi?",
    "¿conoces minecraft?",
    "¿cuánto cuesta el boleto?",
    "¿dónde está el baño?",
    "¿cuántos años tienes?",
    "cuéntame un chiste",
    "¿cuánto es la raíz cuadrada de 144?",
    "do you have internet?",
    "what time is it?",
    "tell me a joke",
    "how much does it cost?",
]

# ── Los footguns ─────────────────────────────────────────────
# Preguntas LEGÍTIMAS que tocan palabras sospechosas. Si alguna de éstas se
# rechaza, la lista negra se pasó de ambiciosa. Cada una está acá porque la
# palabra que la hace sospechosa ESTÁ en los hechos de su civilización.
LEGITIMAS_SOSPECHOSAS = [
    ("¿es Patrimonio Mundial?",              "teotihuacan"),  # 'mundial' ≠ fútbol
    ("¿jugaban con una pelota?",             "mayas"),        # juego de pelota
    ("¿usaban el cacao como moneda?",        "aztecas"),      # moneda de cambio
    ("¿son más grandes que las de Egipto?",  "teotihuacan"),  # comparar es LA pregunta
    ("¿tenían presidente?",                  "mayas"),        # la respuesta es el tlatoani
    ("¿Tláloc traía la lluvia?",             "aztecas"),      # dios de la lluvia
    ("¿por qué se llama Pirámide del Sol?",  "teotihuacan"),  # 'sol' ≠ clima
    ("¿cuánto tiempo duró el imperio?",      "aztecas"),      # 'tiempo' ≠ clima
]


def test_las_siete_se_reconocen_nombradas():
    """Nombrar la civilización manda, en los dos idiomas y sin tema previo."""
    for tema, (es, en) in NOMBRADAS.items():
        for pregunta in (es, en):
            obtenido = resolver_tema(pregunta, None)
            assert obtenido == tema, f"{pregunta!r} → {obtenido}, esperaba {tema}"


def test_la_pregunta_manda_sobre_la_inercia():
    """Nombrar otra civilización CAMBIA de tema; el visitante no queda preso."""
    obtenido = resolver_tema("y los aztecas?", "mayas")
    assert obtenido == "aztecas", f"no cambió de tema: {obtenido}"


def test_gana_la_civilizacion_que_aparece_primero():
    """'¿Los mayas conocían a los aztecas?' es una pregunta sobre los MAYAS."""
    assert resolver_tema("¿los mayas conocían a los aztecas?", None) == "mayas"
    assert resolver_tema("¿los aztecas conocían a los mayas?", None) == "aztecas"


def test_los_seguimientos_heredan_el_tema():
    """Sin esto la mitad de la conversación llega al modelo sin un solo hecho."""
    for tema in CIVILIZACIONES_VALIDAS:
        for pregunta in SEGUIMIENTOS:
            obtenido = resolver_tema(pregunta, tema)
            assert obtenido == tema, f"{pregunta!r} con tema {tema} → {obtenido}"


def test_sin_tema_previo_un_seguimiento_no_se_inventa_uno():
    """Un seguimiento huérfano se rechaza: es mejor repreguntar que adivinar."""
    for pregunta in SEGUIMIENTOS:
        assert resolver_tema(pregunta, None) is None, pregunta


def test_las_ajenas_se_rechazan():
    """Con tema previo y todo: el desvío claro no se contesta."""
    for tema in ("mayas", "teotihuacan"):
        for pregunta in AJENAS:
            obtenido = resolver_tema(pregunta, tema)
            assert obtenido is None, f"{pregunta!r} pasó como {obtenido}"


def test_las_legitimas_sospechosas_pasan():
    """La lista negra no se come preguntas reales. Si esto falla, se pasó."""
    for pregunta, tema in LEGITIMAS_SOSPECHOSAS:
        obtenido = resolver_tema(pregunta, tema)
        assert obtenido == tema, f"RECHAZADA una pregunta legítima: {pregunta!r}"


def test_ninguna_palabra_ajena_vive_en_los_hechos():
    """LA PRUEBA QUE IMPORTA, y la única estructural.

    Los casos de arriba son ejemplos: cubren los footguns que ya conocemos.
    Éste cubre los que todavía no. Si una palabra de la lista negra aparece
    en los hechos de una civilización, entonces existe una pregunta legítima
    sobre esa civilización que el filtro rechaza — y nadie se va a acordar de
    agregarla a LEGITIMAS_SOSPECHOSAS.

    Es lo que habría atajado "mundial" el día que se escribió, sin tener que
    haberse acordado de 'Patrimonio Mundial'.
    """
    hechos = " ".join(e["hechos"].lower() for e in _BASE
                      if e["tema"] in CIVILIZACIONES_VALIDAS)
    claves = " ".join(c.lower() for e in _BASE
                      if e["tema"] in CIVILIZACIONES_VALIDAS
                      for c in e["palabras_clave"])
    corpus = hechos + " " + claves
    choques = [p for p in _DOMINIOS_AJENOS
               if re.search(rf"\b{re.escape(p)}\b", corpus)]
    assert not choques, (
        f"estas palabras de _DOMINIOS_AJENOS aparecen en los hechos de las "
        f"civilizaciones, así que rechazan preguntas legítimas: {sorted(choques)}")


def test_los_temas_que_no_son_civilizaciones_se_rechazan():
    """independencia, revolucion y mexico_general tienen hechos pero no video.

    Siguen en `_BASE` a propósito —los hechos son buenos— pero MEXA no los
    ofrece, así que tampoco los contesta.
    """
    no_civilizaciones = {e["tema"] for e in _BASE} - CIVILIZACIONES_VALIDAS
    assert no_civilizaciones == {"independencia", "revolucion", "mexico_general"}, \
        f"cambió el set de temas no-civilización: {no_civilizaciones}"

    for pregunta in ("háblame de la independencia", "quién fue Hidalgo",
                     "qué fue la revolución mexicana", "quién fue Zapata"):
        assert resolver_tema(pregunta, None) is None, pregunta


def test_contexto_de_solo_sirve_civilizaciones():
    """La frontera se chequea dos veces a propósito: es el requisito, no un detalle."""
    for tema in CIVILIZACIONES_VALIDAS:
        assert contexto_de(tema).startswith("Hechos verificados"), tema
    for tema in ("independencia", "revolucion", "mexico_general", "pokemon", ""):
        assert contexto_de(tema) == "", f"{tema!r} filtró hechos"
    assert contexto_de(None) == ""


def test_resolver_tema_es_idempotente():
    """`dialogo` consulta para decidir y `modulo_ia` vuelve a consultar para
    generar. Si las dos llamadas no dan lo mismo, se desincronizan."""
    for pregunta in SEGUIMIENTOS + [p for p, _ in LEGITIMAS_SOSPECHOSAS]:
        primero  = resolver_tema(pregunta, "mayas")
        segundo  = resolver_tema(pregunta, primero or "mayas")
        assert primero == segundo, f"{pregunta!r}: {primero} != {segundo}"


def test_el_mapa_de_temas_esta_sincronizado():
    """Tres listas hablan de las mismas siete civilizaciones. Si se
    desincronizan, `dialogo` explota con KeyError en plena demo."""
    assert set(contenido.TEMAS_CONOCIMIENTO) == set(contenido.NOMBRES_DISPONIBLES), (
        "TEMAS_CONOCIMIENTO y NOMBRES_DISPONIBLES no coinciden: "
        f"{set(contenido.TEMAS_CONOCIMIENTO) ^ set(contenido.NOMBRES_DISPONIBLES)}")
    assert set(contenido.TEMAS_CONOCIMIENTO.values()) == CIVILIZACIONES_VALIDAS, (
        "TEMAS_CONOCIMIENTO apunta a temas que no son civilizaciones válidas: "
        f"{set(contenido.TEMAS_CONOCIMIENTO.values()) ^ CIVILIZACIONES_VALIDAS}")
    # Todo nombre que `detectar_civilizacion_multi` puede devolver tiene que
    # tener tema: es el valor que `dialogo` le pasa a `establecer_tema`.
    devolvibles = {n for _es, _en, n in contenido.CIVILIZACIONES.values()}
    faltantes = devolvibles - set(contenido.TEMAS_CONOCIMIENTO)
    assert not faltantes, f"sin tema de conocimiento: {faltantes}"


def test_la_frase_de_redireccion_existe_en_los_dos_idiomas():
    """Y acepta {oferta}: rechazar sin volver a ofrecer es una pared, no un guía."""
    for idioma in ("es", "en"):
        frase = contenido.FRASES[idioma].get("fuera_de_tema")
        assert frase, f"falta fuera_de_tema en {idioma}"
        assert "{oferta}" in frase, f"fuera_de_tema en {idioma} no enumera la oferta"
        # Que formatee sin explotar
        frase.format(oferta=", ".join(contenido.nombres_ofrecidos(idioma)))


# ── Identidad ────────────────────────────────────────────────
# La única pregunta fuera de tema con respuesta FIJA. No la contesta el
# modelo: la contesta `contenido.FRASES[*]["identidad"]`.
IDENTIDAD = [
    "¿cómo te llamas?",
    "¿cuál es tu nombre?",
    "¿quién eres?",
    "¿qué eres?",
    "¿eres un robot?",
    "¿quién te hizo?",
    "¿cómo te hicieron?",
    "what is your name?",
    "what's your name?",
    "who are you?",
    "what are you?",
    "are you a robot?",
    "who made you?",
]

# Preguntas REALES que rozan las claves de identidad. Las claves están en
# SEGUNDA PERSONA justamente para que éstas no matcheen — si alguna de éstas
# se lee como identidad, MEXA contesta "me llamo MEXA" a una pregunta de
# historia, que es peor que rechazarla.
NO_SON_IDENTIDAD = [
    "¿de qué eran las pirámides?",
    "¿quién construyó las pirámides?",
    "¿quién era Moctezuma?",
    "¿qué eran los cenotes?",
    "¿quiénes eran los mayas?",
    "who were the olmecs?",
    "who are your gods?",          # \byou\b no entra en "your"
    "who built the pyramid?",
    "what are the chinampas?",
]


def test_las_preguntas_de_identidad_se_reconocen():
    """En los dos idiomas, y con o sin tema previo: la identidad no depende
    de qué se venía hablando."""
    for pregunta in IDENTIDAD:
        assert es_pregunta_de_identidad(pregunta), f"no reconocida: {pregunta!r}"


def test_las_preguntas_de_historia_no_son_identidad():
    """LA prueba que justifica que las claves estén en segunda persona."""
    for pregunta in NO_SON_IDENTIDAD:
        assert not es_pregunta_de_identidad(pregunta), (
            f"leída como identidad una pregunta de historia: {pregunta!r}")
    # Y los seguimientos normales tampoco.
    for pregunta in SEGUIMIENTOS:
        assert not es_pregunta_de_identidad(pregunta), pregunta


def test_identidad_esta_dentro_de_la_lista_negra():
    """UNA sola fuente de verdad. Si `dialogo` no intercepta la pregunta —bug,
    o alguien llamando a la IA directo—, el filtro la rechaza igual en vez de
    dejar que llama3.2:1b improvise quién es MEXA."""
    assert _IDENTIDAD <= _DOMINIOS_AJENOS, (
        f"claves de identidad fuera de la lista negra: {_IDENTIDAD - _DOMINIOS_AJENOS}")
    for pregunta in IDENTIDAD:
        assert resolver_tema(pregunta, "mayas") is None, (
            f"la IA habría contestado con hechos mayas: {pregunta!r}")


def test_la_edad_y_los_chistes_NO_tienen_respuesta_fija():
    """Se decidió a propósito: "¿cómo te llamas?" tiene una respuesta correcta
    y corta; "¿cuántos años tienes?" y "cantá algo" no, y contestarlas abriría
    una charla que MEXA no puede sostener. Siguen rechazándose."""
    for pregunta in ("¿cuántos años tienes?", "cuéntame un chiste",
                     "canta una canción", "how old are you?", "tell me a joke"):
        assert not es_pregunta_de_identidad(pregunta), pregunta
        assert resolver_tema(pregunta, "mayas") is None, pregunta


def test_la_frase_de_identidad_existe_en_los_dos_idiomas():
    """Y NO lleva {oferta}: cuando se dispara, el visitante ya eligió
    civilización y vio el video."""
    for idioma in ("es", "en"):
        frase = contenido.FRASES[idioma].get("identidad")
        assert frase, f"falta identidad en {idioma}"
        assert "MEXA" in frase, f"la frase de identidad en {idioma} no dice el nombre"
        assert "{" not in frase, (
            f"identidad en {idioma} tiene un placeholder; `dialogo` la dice "
            f"sin .format() y explotaría")


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
