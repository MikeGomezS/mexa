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

# Traslación y rotación se corrigen POR SEPARADO (ver escalar_segmentos).
_TRASLACION = ("F", "B")
_ROTACION   = ("R", "L")


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


def escalar_segmentos(segmentos, factor_avance=1.0, factor_giro=1.0):
    """Aplica la corrección de hardware a cada tramo, SEGÚN SU TIPO.

    Por qué dos factores y no uno. La ida y la vuelta NO son simétricas en
    TRASLACIÓN: inercia, patinaje y el motor rindiendo distinto en reversa
    hacen que un 'B' de la misma duración que el 'F' no recorra lo mismo.
    Eso es real y se corrige con `factor_avance`.

    En ROTACIÓN no pasa. Mirá el firmware (arduino/mexa/mexa.ino:352-353):
    'R' es ladoIzq(+1)+ladoDer(-1) y 'L' es ladoIzq(-1)+ladoDer(+1). En
    CUALQUIER giro la mitad de los motores va para adelante y la otra mitad
    para atrás, así que la asimetría adelante/reversa se CANCELA adentro del
    giro. Invertir un giro es espejarlo, no revertirlo.

    Por eso un factor único es un ERROR de modelo: calibrarlo para que cierre
    el avance le mete ese mismo porcentaje de error angular a cada giro. Y el
    error angular es el caro — no se suma al final, ROTA todos los tramos que
    vienen después. `factor_giro` arranca en 1.0 y casi siempre se queda ahí.

    Función PURA: no toca hardware, se prueba en tests/test_registro_camino.py.
    """
    escalados = []
    for cmd, duracion in segmentos:
        if cmd in _ROTACION:
            escalados.append((cmd, duracion * factor_giro))
        else:
            escalados.append((cmd, duracion * factor_avance))
    return escalados


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
               factor_avance=1.0, factor_giro=1.0, factor_duracion=None):
    """Deshace el recorrido: ejecuta los tramos inversos, uno por uno, en
    orden inverso, para devolver a MEXA a su punto de partida.

    `registro` es la lista de (comando, timestamp) acumulada durante el
    acercamiento. Devuelve los tramos EJECUTADOS, ya escalados (log/tests).

    `factor_avance` y `factor_giro` son la calibración de hardware, y van
    SEPARADOS a propósito: la reversa no rinde como el avance, pero un giro
    invertido es el mismo giro espejado (ver escalar_segmentos). Si MEXA se
    queda CORTA al volver, subí `factor_avance` (>1.0); si se PASA, bajalo.
    Tocá `factor_giro` sólo si queda mal ORIENTADA con la distancia bien.
    Se calibran en tests/calibrar_retroceso.py.

    `factor_duracion` es el parámetro VIEJO, que escalaba avance y giro con
    el mismo número. Se acepta por compatibilidad y aplica a los dos.

    POR QUÉ TRAMO POR TRAMO Y NO DE UN TIRÓN. Tienta fusionar tramos
    consecutivos del mismo comando (pasa siempre: la fase visual cierra con
    'S' y el empuje final manda otro 'F'). Sería más rápido y es INCORRECTO:
    dos pulsos de 1s pagan DOS rampas de aceleración y uno de 2s paga UNA,
    así que el fusionado recorre MÁS. La réplica es exacta porque conserva la
    estructura de arranques de la ida. Por lo mismo `pausa_entre_tramos` NO
    es tiempo muerto: garantiza que cada tramo arranque DESDE EL REPOSO, como
    en la ida. Bajarla compra velocidad pagando con exactitud.
    """
    from .modulo_motores import mover_por_tiempo, detener

    if factor_duracion is not None:   # compatibilidad con la firma vieja
        factor_avance = factor_giro = factor_duracion

    segmentos = calcular_camino_inverso(registro, duracion_min)
    if not segmentos:
        print("[CAMINO] Nada que deshacer: no se registró desplazamiento.")
        return segmentos
    segmentos = escalar_segmentos(segmentos, factor_avance, factor_giro)

    print(f"[CAMINO] Retrocediendo {len(segmentos)} tramo(s) al punto de "
          f"partida (avance={factor_avance:.2f}, giro={factor_giro:.2f}).")
    ultimo = len(segmentos) - 1
    for i, (cmd, duracion) in enumerate(segmentos):
        mover_por_tiempo(_DIRECCION[cmd], duracion)
        # La pausa sirve para que el tramo SIGUIENTE arranque desde el reposo.
        # Después del último no hay siguiente: era 0.15s regalados, siempre.
        if i != ultimo:
            time.sleep(pausa_entre_tramos)
    detener()
    return segmentos
