"""
Test de LÓGICA PURA del registro de camino (sin hardware).

calcular_camino_inverso() es determinista: recibe una lista de
(comando, timestamp) y devuelve los tramos que DESHACEN el recorrido
(orden inverso + comando invertido F<->B, R<->L). Como no toca motores
ni serial, se puede probar con aserciones simples.

USO (en cualquier máquina, no hace falta el robot):
  python3 tests/test_registro_camino.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.registro_camino import calcular_camino_inverso


def _aprox(segmentos, esperado, tol=1e-6):
    """Compara listas de (cmd, dur) con tolerancia en la duración."""
    if len(segmentos) != len(esperado):
        return False
    for (c1, d1), (c2, d2) in zip(segmentos, esperado):
        if c1 != c2 or abs(d1 - d2) > tol:
            return False
    return True


def test_registro_vacio():
    assert calcular_camino_inverso([]) == []


def test_solo_paradas_no_genera_tramos():
    # Sólo S: no hubo desplazamiento, nada que deshacer.
    reg = [("S", 0.0), ("S", 1.0), ("S", 2.0)]
    assert calcular_camino_inverso(reg) == []


def test_avance_simple_se_invierte_a_retroceso():
    # Avanza 2s y para -> volver = retroceder 2s.
    reg = [("F", 0.0), ("S", 2.0)]
    assert _aprox(calcular_camino_inverso(reg), [("B", 2.0)])


def test_giro_derecha_se_invierte_a_izquierda():
    reg = [("R", 0.0), ("S", 0.25)]
    assert _aprox(calcular_camino_inverso(reg), [("L", 0.25)])


def test_camino_compuesto_se_deshace_en_orden_inverso():
    # Avanza 1s, gira derecha 0.25s, avanza 1.5s.
    reg = [
        ("F", 0.0), ("S", 1.0),     # avance 1.0s
        ("R", 1.0), ("S", 1.25),    # giro derecha 0.25s
        ("F", 1.5), ("S", 3.0),     # avance 1.5s
    ]
    # Deshacer: último primero -> retroceder 1.5, girar izquierda 0.25,
    # retroceder 1.0.
    esperado = [("B", 1.5), ("L", 0.25), ("B", 1.0)]
    assert _aprox(calcular_camino_inverso(reg), esperado)


def test_descarta_tramos_mas_cortos_que_duracion_min():
    # Un parpadeo de 10ms no debe generar un tramo (ruido, no movimiento real).
    reg = [("F", 0.0), ("S", 0.01), ("F", 0.5), ("S", 2.0)]
    # Sólo el segundo avance (1.5s) supera duracion_min=0.05.
    assert _aprox(calcular_camino_inverso(reg, duracion_min=0.05), [("B", 1.5)])


def test_ultimo_comando_sin_sucesor_se_ignora():
    # Si el registro NO termina en S, el último comando no tiene duración
    # medible y se ignora (no se inventa un tramo).
    reg = [("F", 0.0), ("S", 1.0), ("F", 1.0)]
    assert _aprox(calcular_camino_inverso(reg), [("B", 1.0)])


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
