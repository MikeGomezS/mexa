"""
Test de LÓGICA PURA de la elección de civilización (sin modelos ni audio).

Cubre las dos reglas que deciden QUÉ video se proyecta:

  1. `nombres_ofrecidos(idioma)` — qué civilizaciones NOMBRA MEXA en voz alta.
     La REGLA DE ORO de contenido.py: no se ofrece lo que no se puede
     reconocer. Con gramática cerrada, el decodificador no sabe contestar
     "eso no estaba en la lista": devuelve la opción más parecida, y MEXA
     proyecta un video que nadie pidió.

  2. `detectar_civilizacion_multi` — cómo se combinan los dos oídos, y en
     particular CUÁNDO un "[unk]" es silencio y cuándo es un desmentido.

  3. Que cada video del catálogo EXISTA en disco. Un nombre de archivo mal
     escrito no rompe nada visible en los logs, pero delante del visitante
     MEXA anuncia un video y proyecta un cartel de error.

Como no toca Vosk ni el micrófono, corre en cualquier máquina:
  python3 tests/test_deteccion_civilizacion.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos import contenido
from modulos.contenido import (CIVILIZACIONES, GRAMATICA_CIVILIZACIONES,
                               detectar_civilizacion_multi, nombres_ofrecidos)
from modulos.modulo_proyector import CARPETA_VIDEOS


def _nombre(textos, idioma="es"):
    """Sólo el nombre elegido (o None), que es lo que decide el video."""
    elegido = detectar_civilizacion_multi(textos, idioma)
    return elegido[1] if elegido else None


# ── La oferta: no prometer lo que no se puede oír ────────────

def test_en_espanol_se_ofrecen_las_siete():
    assert len(nombres_ofrecidos("es")) == 7


def test_en_ingles_no_se_ofrecen_olmecas_ni_toltecas():
    # Medido en tests/test_civilizaciones.py: en inglés dan 0/4. `olmec` y
    # `toltec` no existen en el léxico en-us, y el rescate por oído español
    # no llega. Ofrecerlas es prometer algo que MEXA no puede cumplir.
    ofrecidos = nombres_ofrecidos("en")
    assert "the Olmecs" not in ofrecidos
    assert "the Toltecs" not in ofrecidos


def test_en_ingles_se_ofrece_lo_que_si_se_alcanza():
    assert set(nombres_ofrecidos("en")) == {
        "the Mayas", "the Aztecs", "Teotihuacán", "the Zapotecs", "the Mixtecs"}


def test_regla_de_oro_todo_lo_ofrecido_es_reconocible():
    """Cada nombre ofrecido DEBE tener una palabra en alguna gramática.

    Es la REGLA DE ORO hecha ejecutable: si alguien agrega una civilización a
    la oferta sin agregarla a la gramática, esto lo caza acá y no en la sala.
    """
    palabras = set(GRAMATICA_CIVILIZACIONES["es"]) | set(GRAMATICA_CIVILIZACIONES["en"])
    alcanzables = {nombre for clave, (_es, _en, nombre) in CIVILIZACIONES.items()
                   if clave in palabras}
    for idioma in ("es", "en"):
        for ofrecido in nombres_ofrecidos(idioma):
            # los nombres en inglés se comparan por su original en español
            en_es = next((k for k, v in contenido.NOMBRES_EN.items() if v == ofrecido),
                         ofrecido)
            assert en_es in alcanzables, f"[{idioma}] se ofrece {ofrecido!r} sin gramática"


# ── Los videos: que el catálogo apunte a archivos que EXISTEN ────

def test_todo_video_del_catalogo_existe_en_disco():
    """Cada ruta de CIVILIZACIONES tiene que ser un archivo real.

    POR QUÉ ESTO ES UN TEST Y NO UNA REVISIÓN A OJO. Cuando el archivo no
    está, MEXA no se cae: `reproducir_video` proyecta "Video no disponible"
    y sigue. Pero `dialogo.py` no mira ese resultado, así que MEXA igual
    anuncia "te voy a mostrar un video sobre los Aztecas", muestra el cartel
    de error y a los tres segundos pregunta "¿disfrutaste el video?". El
    fallo es SILENCIOSO en los logs y ESTRUENDOSO delante del visitante.

    Encontrados así (2026-08-31): 'Aztecas Español.mp4' en vez de
    'Aztecas_esp.mp4', y 'Olmecas_eng .mp4' con un espacio antes del punto.
    Dos nombres, y los Aztecas son la civilización que MÁS se pide.

    Se SALTA si no hay carpeta de videos: el repo la excluye por tamaño
    (.gitignore), así que en una máquina de desarrollo recién clonada la
    ausencia no es un defecto. En el robot la carpeta está, y ahí sí mide.
    """
    if not os.path.isdir(CARPETA_VIDEOS):
        print("      (sin carpeta de videos: se omite)", end=" ")
        return
    faltan = sorted({
        f"[{idioma}] {nombre} -> {os.path.basename(ruta)}"
        for _clave, (ruta_es, ruta_en, nombre) in CIVILIZACIONES.items()
        for idioma, ruta in (("es", ruta_es), ("en", ruta_en))
        if not os.path.isfile(ruta)
    })
    assert not faltan, "videos del catálogo que NO existen: " + "; ".join(faltan)


# ── Los dos oídos: cuándo "[unk]" es silencio y cuándo es un NO ──

def test_los_dos_modelos_coinciden():
    assert _nombre({"es": "quiero los mayas", "en": "mayas"}) == "los Mayas"


def test_se_contradicen_no_se_elige_nada():
    assert _nombre({"es": "aztecas", "en": "mayas"}) is None


def test_un_modelo_calla_y_el_otro_reconoce():
    # Texto vacío = no se oyó nada. No es un desmentido.
    assert _nombre({"es": "los toltecas", "en": ""}) == "los Toltecas"


def test_unk_del_modelo_que_NO_tenia_la_palabra_es_silencio():
    """El rescate por oído español, que TIENE que seguir funcionando.

    `mixteca` no está en la gramática inglesa, así que el modelo inglés no
    podía nombrarla ni queriendo: su "[unk]" no desmiente nada.
    """
    assert _nombre({"es": "mixteca", "en": "[unk]"}, "en") == "los Mixtecas"


def test_unk_del_modelo_que_SI_tenia_la_palabra_es_un_desmentido():
    """El caso que proyectaba el video equivocado.

    `teotihuacan` SÍ está en la gramática inglesa. Que el modelo inglés diga
    "[unk]" teniéndola disponible no es silencio: es un NO. Fue el CRUZADO
    real medido — 'the olmecs' -> Teotihuacán, oyó {'es': 'teotihuacán',
    'en': '[unk]'}. Mejor repreguntar que proyectar cualquier cosa.
    """
    assert _nombre({"es": "teotihuacán", "en": "[unk]"}, "en") is None


def test_unk_del_oido_EXTRANJERO_no_veta_aunque_tuviera_la_palabra():
    """El visitante habla español; el oído inglés se abstiene, como corresponde.

    'mayas' está en las DOS gramáticas, pero el modelo inglés está escuchando
    español: su "[unk]" es lo esperable, no una opinión. Sin esta distinción
    los aciertos se derrumbaban de 42 a 30 sobre 56 (medido).
    """
    assert _nombre({"es": "los mayas", "en": "[unk]"}, "es") == "los Mayas"


def test_unk_no_desmiente_si_el_otro_modelo_tambien_lo_confirma():
    # Si los dos la nombran, el acuerdo manda: no hay "[unk]" que valga.
    assert _nombre({"es": "teotihuacán", "en": "teotihuacan"}, "en") == "Teotihuacán"


def test_nadie_reconoce_nada():
    assert _nombre({"es": "[unk]", "en": "[unk]"}) is None
    assert _nombre({"es": "", "en": ""}) is None


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
