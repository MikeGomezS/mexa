# ============================================================
#  MEXA — Registro de camino (para que pueda RETROCEDER)
#
#  Mientras MEXA se acerca al visitante va emitiendo comandos de
#  motor (F/B/R/L/S). Si anotamos cada comando con su timestamp,
#  podemos DESHACER el recorrido: recorrerlo al revés invirtiendo
#  cada tramo (F<->B, R<->L) para volver al punto de partida.
#
#  DISEÑO EN DOS CAPAS:
#    1. calcular_camino_inverso() — LÓGICA PURA y determinista. No
#       toca hardware ni serial, así que se prueba con aserciones
#       (ver tests/test_registro_camino.py). Es el corazón.
#    2. RegistroCamino + retroceder() — la parte que SÍ habla con el
#       robot. Se enganchan a la capa serial e importan el hardware
#       de forma PEREZOSA, para que importar este módulo siga siendo
#       seguro en una máquina sin el robot (lo exige el test).
# ============================================================

import time

# Cada comando de desplazamiento tiene su opuesto. 'S' (stop) y
# cualquier otra cosa NO son desplazamiento: no se invierten ni
# generan un tramo que deshacer.
_MOV_INVERSO = {"F": "B", "B": "F", "R": "L", "L": "R"}


def calcular_camino_inverso(registro, duracion_min=0.05):
    """Convierte un registro de (comando, timestamp) en los tramos que
    DESHACEN el recorrido.

    El comando de cada entrada estuvo activo hasta la entrada SIGUIENTE,
    así que su duración es la diferencia de timestamps. Por eso:
      - el último comando no tiene sucesor: no se le puede medir duración
        y se ignora (no inventamos un tramo),
      - los 'S' (y cualquier no-desplazamiento) no generan tramo,
      - los tramos más cortos que `duracion_min` se descartan como ruido
        (un parpadeo de pocos ms no es movimiento real).

    Devuelve la lista de (comando_invertido, duracion) en ORDEN INVERSO:
    lo último que MEXA hizo es lo primero que deshace.
    """
    segmentos = []
    for (cmd, t_inicio), (_, t_fin) in zip(registro, registro[1:]):
        inverso = _MOV_INVERSO.get(cmd)
        if inverso is None:          # 'S' u otro: no hubo desplazamiento
            continue
        duracion = t_fin - t_inicio
        if duracion < duracion_min:  # ruido: ignorar
            continue
        segmentos.append((inverso, duracion))
    segmentos.reverse()
    return segmentos


class RegistroCamino:
    """Anota los comandos de motor con su timestamp para poder deshacer
    el recorrido más tarde.

    Se engancha a la capa serial: al llamar `iniciar()`, cada comando que
    pase por conexion_arduino.enviar() queda registrado automáticamente,
    sin importar qué función de alto nivel lo haya emitido (avance
    continuo, pulsos de giro o empuje ciego). `finalizar()` cierra el
    último tramo y deja de escuchar.
    """

    def __init__(self, reloj=time.monotonic):
        # `reloj` se inyecta para poder testear con un tiempo controlado.
        self._reloj = reloj
        self._eventos = []

    def registrar(self, cmd):
        self._eventos.append((cmd, self._reloj()))

    def iniciar(self):
        """Empieza a registrar enganchándose a la capa serial."""
        from . import conexion_arduino
        self._eventos.clear()
        conexion_arduino.set_observador(self.registrar)

    def finalizar(self):
        """Deja de registrar y cierra el último tramo con un 'S' para que
        tenga duración medible."""
        from . import conexion_arduino
        conexion_arduino.set_observador(None)
        if self._eventos and self._eventos[-1][0] != "S":
            self.registrar("S")

    @property
    def eventos(self):
        return list(self._eventos)

    def camino_inverso(self, duracion_min=0.05):
        return calcular_camino_inverso(self._eventos, duracion_min)


# Comando crudo -> dirección que entiende modulo_motores.mover_por_tiempo.
_DIRECCION = {"F": "adelante", "B": "atras", "R": "derecha", "L": "izquierda"}


def retroceder(registro, duracion_min=0.05, pausa_entre_tramos=0.15,
               factor_duracion=1.0):
    """Deshace el recorrido: ejecuta los tramos inversos, uno por uno, en
    orden inverso, para devolver a MEXA a su punto de partida.

    `registro` es la lista de (comando, timestamp) acumulada durante el
    acercamiento. Devuelve los tramos ejecutados (útil para log/tests).

    `factor_duracion` (calibración de hardware) escala TODAS las duraciones
    del retroceso. El avance y la reversa NO son simétricos: inercia,
    patinaje y el motor rindiendo distinto en reversa hacen que un 'B' de la
    misma duración que el 'F' no recorra lo mismo. Si MEXA se queda CORTO al
    volver, subí el factor (>1.0); si se PASA, bajalo (<1.0). 1.0 = sin
    corrección. Se calibra en tests/calibrar_retroceso.py.
    """
    from .modulo_motores import mover_por_tiempo, detener

    segmentos = calcular_camino_inverso(registro, duracion_min)
    if not segmentos:
        print("[CAMINO] Nada que deshacer: no se registró desplazamiento.")
        return segmentos

    print(f"[CAMINO] Retrocediendo {len(segmentos)} tramo(s) al punto de "
          f"partida (factor={factor_duracion:.2f}).")
    for cmd, duracion in segmentos:
        mover_por_tiempo(_DIRECCION[cmd], duracion * factor_duracion)
        time.sleep(pausa_entre_tramos)  # asienta entre tramos (anti-blur/inercia)
    detener()
    return segmentos
