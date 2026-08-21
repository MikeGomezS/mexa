# ============================================================
#  MEXA — Telemetría del Arduino (lógica PURA, sin hardware)
#
#  El Arduino no sólo obedece: TAMBIÉN informa. Manda líneas por
#  serial con lo que sienten sus sensores:
#
#    "PRES:0/1"          presencia (OR de los 2 PIR)
#    "DIST:<izq>,<der>"  distancia frontal en cm (999 = nada a la vista)
#    "STOP:<cm>"         frenó SOLO: alguien demasiado cerca al frente
#    "WALL:I/D"          frenó por pared lateral al girar
#    "OK <cmd>"          eco del comando recibido
#
#  Este módulo NO abre puertos ni mueve motores: sólo traduce ese
#  texto a datos y decide si una lectura todavía vale. Por eso se
#  prueba con aserciones en cualquier máquina (tests/test_telemetria.py),
#  misma división de capas que registro_camino.py.
#
#  LA DISTINCIÓN QUE SOSTIENE TODO: `None` es "NO SÉ" y 999 es "no
#  hay nadie cerca". Confundirlas es lo que haría que MEXA frene
#  contra un fantasma, o que empuje contra una persona porque el
#  sensor dejó de hablar. Quien no sabe, no frena: sigue con la
#  cámara, que es el comportamiento que MEXA ya tenía.
# ============================================================

# Centinela del firmware: no hubo eco dentro del timeout del ECHO
# (nada dentro de ~2m para los frontales). Es un DATO, no un error.
SIN_ECO_CM = 999.0

# Cuánto vale una lectura frontal antes de considerarla vieja. El
# firmware sólo mide MIENTRAS MEXA avanza y refresca cada frontal cada
# ~120ms; medio segundo sin noticias significa que dejó de avanzar (o
# que el sensor no está conectado), no que la persona siga ahí.
FRESCURA_S = 0.5


def interpretar_linea(linea):
    """Traduce UNA línea del Arduino a `(tipo, valor)`, o None si no es
    telemetría accionable (eco de comando, banner, ruido, línea rota).

    Tipos y valores:
      ("presencia", bool)            de "PRES:0/1"
      ("distancia", (izq, der))      de "DIST:<izq>,<der>", en cm
      ("freno",     cm)              de "STOP:<cm>"
      ("pared",     "I" | "D")       de "WALL:I/D"

    NUNCA lanza: el serial trae ruido y líneas partidas a la mitad, y un
    byte corrupto no puede tumbar un acercamiento en curso.
    """
    if not linea:
        return None
    linea = linea.strip()

    if linea.startswith("PRES:"):
        return ("presencia", linea.endswith("1"))

    if linea.startswith("DIST:"):
        partes = linea[len("DIST:"):].split(",")
        if len(partes) != 2:
            return None
        try:
            return ("distancia", (float(partes[0]), float(partes[1])))
        except ValueError:
            return None

    if linea.startswith("STOP:"):
        try:
            return ("freno", float(linea[len("STOP:"):]))
        except ValueError:
            return None

    if linea.startswith("WALL:"):
        lado = linea[len("WALL:"):]
        return ("pared", lado) if lado in ("I", "D") else None

    return None


class EstadoFrente:
    """Qué hay delante de MEXA AHORA, según los ultrasónicos frontales.

    Acumula los eventos que llegan del Arduino y responde dos preguntas:
      - `distancia_cm()`: a cuántos cm está lo más cercano al frente
        (None si no hay lectura fresca: el sensor no está hablando).
      - `freno_cm()`: si el Arduino ya cortó los motores por su cuenta.

    `reiniciar()` se llama al arrancar CADA avance, en espejo con
    `reiniciarFrente()` del firmware: la maniobra anterior no dice nada
    de ésta.
    """

    def __init__(self, frescura_s=FRESCURA_S):
        self._frescura_s = frescura_s
        self.reiniciar()

    def reiniciar(self):
        self._izq = None
        self._der = None
        self._sello = None   # cuándo llegó la última lectura de distancia
        self._freno = None   # cm del último "STOP:" (hecho, no medición)

    def anotar(self, evento, ahora):
        """Incorpora un evento de `interpretar_linea` (ignora los ajenos:
        presencia y pared no son asunto del frente)."""
        if not evento:
            return
        tipo, valor = evento
        if tipo == "distancia":
            self._izq, self._der = valor
            self._sello = ahora
        elif tipo == "freno":
            self._freno = valor

    def distancia_cm(self, ahora):
        """Distancia al obstáculo frontal MÁS CERCANO, en cm.

        Manda el más cercano de los dos sensores, no el promedio: si un
        hombro entra antes que el otro, vale el que está más cerca. Es un
        freno, no una estadística.

        Devuelve None si no hay lectura o si la última ya envejeció
        (`FRESCURA_S`). None significa "no sé", y quien no sabe no frena.
        """
        if self._sello is None or ahora - self._sello > self._frescura_s:
            return None
        return min(self._izq, self._der)

    def freno_cm(self):
        """cm a los que el Arduino frenó SOLO, o None si no frenó.

        No caduca por tiempo: "frenó" es un hecho consumado, no una
        medición. Se limpia con `reiniciar()`, al arrancar el avance
        siguiente.
        """
        return self._freno
