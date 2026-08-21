"""
Test de LÓGICA PURA de la telemetría del Arduino (sin hardware).

El Arduino manda líneas por serial: 'PRES:0/1' (PIR), 'DIST:<izq>,<der>'
(ultrasónicos frontales, cm), 'STOP:<cm>' (frenó solo por tener a alguien
demasiado cerca) y 'WALL:I/D' (frenó por pared lateral al girar).

Interpretar esas líneas y decidir si una lectura sigue siendo VÁLIDA es
lógica determinista: no toca serial ni motores, así que se prueba con
aserciones simples. Ahí es donde se esconden los bugs (el centinela 999,
una línea partida a la mitad, una lectura vieja de hace 10 segundos).

USO (en cualquier máquina, no hace falta el robot):
  python3 tests/test_telemetria.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.telemetria import (
    SIN_ECO_CM,
    EstadoFrente,
    interpretar_linea,
)


# ── interpretar_linea: de texto crudo a evento ────────────────

def test_interpreta_presencia():
    assert interpretar_linea("PRES:1") == ("presencia", True)
    assert interpretar_linea("PRES:0") == ("presencia", False)


def test_interpreta_distancia_frontal():
    assert interpretar_linea("DIST:12.5,80.0") == ("distancia", (12.5, 80.0))


def test_interpreta_distancia_sin_eco():
    # 999 es el centinela del firmware: "no hay nada dentro del alcance".
    assert interpretar_linea("DIST:999.0,999.0") == ("distancia", (999.0, 999.0))


def test_interpreta_freno_por_persona():
    assert interpretar_linea("STOP:23.4") == ("freno", 23.4)


def test_interpreta_pared_lateral():
    assert interpretar_linea("WALL:D") == ("pared", "D")
    assert interpretar_linea("WALL:I") == ("pared", "I")


def test_ignora_lineas_que_no_son_telemetria():
    # El eco de comando y el banner de arranque no son datos accionables.
    assert interpretar_linea("OK F") is None
    assert interpretar_linea("MEXA firmware listo: 4 motores") is None
    assert interpretar_linea("") is None


def test_linea_malformada_no_revienta():
    # Serial con ruido: media línea, números rotos, campos de menos.
    # NUNCA debe lanzar: un byte corrupto no puede tumbar el acercamiento.
    assert interpretar_linea("DIST:") is None
    assert interpretar_linea("DIST:abc,12.0") is None
    assert interpretar_linea("DIST:12.0") is None
    assert interpretar_linea("STOP:") is None
    assert interpretar_linea("STOP:x") is None


def test_tolera_espacios_alrededor():
    assert interpretar_linea("  DIST:40.0,50.0  ") == ("distancia", (40.0, 50.0))


# ── EstadoFrente: qué distancia hay AHORA (y si es confiable) ──

def test_sin_lecturas_la_distancia_es_desconocida():
    # None = "no sé", que NO es lo mismo que "no hay nadie".
    estado = EstadoFrente()
    assert estado.distancia_cm(ahora=0.0) is None


def test_distancia_es_la_del_sensor_MAS_CERCANO():
    # Es un freno, no un promedio: si un hombro entra antes que el otro,
    # vale el que está más cerca.
    estado = EstadoFrente()
    estado.anotar(("distancia", (35.0, 90.0)), ahora=10.0)
    assert estado.distancia_cm(ahora=10.0) == 35.0


def test_lectura_fresca_sigue_valiendo_dentro_de_la_ventana():
    estado = EstadoFrente(frescura_s=0.5)
    estado.anotar(("distancia", (40.0, 999.0)), ahora=10.0)
    assert estado.distancia_cm(ahora=10.4) == 40.0


def test_lectura_VIEJA_se_descarta():
    # El firmware sólo mide mientras MEXA avanza. Si dejó de avanzar, la
    # última lectura envejece y ya no dice dónde está la persona AHORA.
    estado = EstadoFrente(frescura_s=0.5)
    estado.anotar(("distancia", (40.0, 999.0)), ahora=10.0)
    assert estado.distancia_cm(ahora=10.6) is None


def test_sin_eco_es_dato_valido_no_desconocido():
    # 999 significa "nadie dentro del alcance": es información, y distinta
    # de None ("el sensor no me está hablando").
    estado = EstadoFrente()
    estado.anotar(("distancia", (999.0, 999.0)), ahora=5.0)
    assert estado.distancia_cm(ahora=5.0) == SIN_ECO_CM


def test_reiniciar_olvida_las_lecturas():
    # Cada avance nuevo arranca a ciegas: la distancia de la maniobra
    # anterior no dice nada de esta.
    estado = EstadoFrente()
    estado.anotar(("distancia", (30.0, 30.0)), ahora=1.0)
    estado.reiniciar()
    assert estado.distancia_cm(ahora=1.0) is None


# ── EstadoFrente: el freno reflejo del Arduino ────────────────

def test_sin_freno_no_hay_freno():
    estado = EstadoFrente()
    assert estado.freno_cm() is None


def test_anota_el_freno_reflejo_del_arduino():
    # STOP: significa que el Arduino YA cortó los motores por su cuenta.
    estado = EstadoFrente()
    estado.anotar(("freno", 22.0), ahora=3.0)
    assert estado.freno_cm() == 22.0


def test_el_freno_NO_caduca_por_tiempo():
    # A diferencia de la distancia, "frenó" es un HECHO consumado, no una
    # medición: no envejece. Se limpia al arrancar el avance siguiente.
    estado = EstadoFrente(frescura_s=0.5)
    estado.anotar(("freno", 22.0), ahora=3.0)
    assert estado.freno_cm() == 22.0
    assert estado.distancia_cm(ahora=99.0) is None


def test_reiniciar_olvida_el_freno():
    estado = EstadoFrente()
    estado.anotar(("freno", 22.0), ahora=3.0)
    estado.reiniciar()
    assert estado.freno_cm() is None


def test_anotar_ignora_eventos_ajenos_y_nulos():
    # EstadoFrente sólo mira al frente: presencia y pared no son asunto suyo.
    estado = EstadoFrente()
    estado.anotar(None, ahora=1.0)
    estado.anotar(("presencia", True), ahora=1.0)
    estado.anotar(("pared", "D"), ahora=1.0)
    assert estado.distancia_cm(ahora=1.0) is None
    assert estado.freno_cm() is None


def main():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"  OK  {prueba.__name__}")
        except AssertionError:
            fallos += 1
            print(f"FALLO {prueba.__name__}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasaron.")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
