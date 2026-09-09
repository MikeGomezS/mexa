# ============================================================
#  MEXA — ¿puede acercarse al visitante SIN la cámara?
#
#  HOY NO PUEDE, y ese es el agujero que este test cierra.
#  `acercarse_a_usuario()` está gateado de punta a punta por la
#  visión: `asegurar_avance()` (la única que manda 'F') vive
#  dentro de la rama `posicion == "centro"` de una lectura REAL
#  de cara. Sin cara, MEXA no manda un solo 'F' — medido en
#  hardware: 0.9 s de vida y un único comando, 'S'.
#
#  Y el empuje final tampoco rescata: su guarda `cerca and
#  centrada` se evalúa contra `ult_tamano = 0.0`, así que cubre
#  "vi la cara y la perdí de cerca", NUNCA "no vi ninguna cara".
#  MEXA tiene CUATRO ultrasónicos y ningún camino de movimiento
#  que no pase por los ojos.
#
#  LOS LÍMITES DE LO QUE ESTE SENTIDO PUEDE (medidos, no
#  supuestos), porque son los que hacen honesto al fallback:
#    · ALCANCE ~2 m — ECHO_TIMEOUT_FRENTE_US = 12000 us
#      (arduino/mexa/mexa.ino:196). Más lejos devuelve 999.0,
#      que NO es "no sé": es "no hay nadie dentro del alcance".
#    · SÓLO MIDE EN MARCHA — `vigilarFrente()` corre únicamente
#      durante un avance. Quieto no hay lectura, así que para
#      saber si hay alguien HAY que empezar a caminar.
#    · ~2.5 cm/s (calibrado 2026-06-23, ruedas chicas): cerrar
#      130 cm son ~52 s. El fallback acerca, no teletransporta.
#
#  Es LÓGICA PURA: los sensores y la cámara se reemplazan por
#  funciones de mentira, y los motores hablan por un serial que
#  no está abierto (conexion_arduino.enviar con _serial=None no
#  escribe nada, pero SÍ avisa al observador). Lo que se mide es
#  exactamente eso: la lista de comandos que MEXA quiso mandar.
#
#  Correr con:  python3 tests/test_acercamiento_sin_camara.py
# ============================================================

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos import navegacion
from modulos.telemetria import SIN_ECO_CM

_fallos: list[str] = []


def _revisar(ok: bool, titulo: str, detalle: str) -> None:
    print(f"  {'✓' if ok else '✗'} {titulo}: {detalle}")
    if not ok:
        _fallos.append(titulo)


# ── Sensores de mentira ───────────────────────────────────────
class FrenteFalso:
    """Ultrasónico frontal simulado.

    `secuencia` son las lecturas que va devolviendo, una por consulta;
    cuando se acaba, repite la última. Un `None` en la lista es "no sé"
    (sensor mudo o lectura vieja), 999.0 es "nadie dentro del alcance".
    """

    def __init__(self, secuencia, freno_en=None):
        self.secuencia = list(secuencia)
        self.freno_en = freno_en   # nº de consulta en la que el Arduino frena solo
        self.consultas = 0
        self.reinicios = 0

    def distancia(self):
        self.consultas += 1
        if not self.secuencia:
            return None
        if self.consultas <= len(self.secuencia):
            return self.secuencia[self.consultas - 1]
        return self.secuencia[-1]

    def freno(self):
        if self.freno_en is not None and self.consultas >= self.freno_en:
            return 22.0
        return None

    def reiniciar(self):
        self.reinicios += 1


class CamaraFalsa:
    """Cámara simulada. `lecturas` son los retornos de localizar_cara():
    None = no ve cara; (posicion, tamano) = la ve. Al agotarse, repite None
    para siempre (una cámara velada nunca se recupera sola)."""

    def __init__(self, lecturas=()):
        self.lecturas = list(lecturas)
        self.llamadas = 0

    def localizar(self):
        self.llamadas += 1
        if self.llamadas <= len(self.lecturas):
            return self.lecturas[self.llamadas - 1]
        return None


def _montar(camara, frente, **constantes):
    """Reemplaza sensores y constantes en navegacion. Devuelve una función
    que restaura TODO — un test que ensucia el módulo envenena al siguiente."""
    originales = {
        "localizar_cara": navegacion.localizar_cara,
        "reiniciar_objetivo": navegacion.reiniciar_objetivo,
        "distancia_frontal_cm": navegacion.distancia_frontal_cm,
        "freno_por_persona": navegacion.freno_por_persona,
        "reiniciar_frente": navegacion.reiniciar_frente,
    }
    originales.update({k: getattr(navegacion, k) for k in constantes})

    navegacion.localizar_cara = camara.localizar
    navegacion.reiniciar_objetivo = lambda: None
    navegacion.distancia_frontal_cm = frente.distancia
    navegacion.freno_por_persona = frente.freno
    navegacion.reiniciar_frente = frente.reiniciar
    for nombre, valor in constantes.items():
        setattr(navegacion, nombre, valor)

    def restaurar():
        for nombre, valor in originales.items():
            setattr(navegacion, nombre, valor)

    return restaurar


def _comandos(eventos):
    """De [(cmd, t), ...] a la cadena de comandos: 'FS', 'S', 'FRFS'..."""
    return "".join(cmd for cmd, _ in eventos)


# ── Etapa 1: el fallback solo, aislado ────────────────────────
def etapa_fallback():
    print("\n[1] El acercamiento a ciegas, aislado")

    # Alguien a 150cm que se va acercando conforme MEXA camina.
    frente = FrenteFalso([150.0, 140.0, 120.0, 100.0, 85.0, 72.0, 68.0])
    restaurar = _montar(CamaraFalsa(), frente)
    try:
        motivo = navegacion._acercamiento_a_ciegas(time.time() + 30)
    finally:
        restaurar()
    _revisar(motivo == "medido", "Llega y frena por medición",
             f"motivo={motivo!r} (esperado 'medido'), "
             f"{frente.consultas} consultas al frente")

    # El sensor no contesta NUNCA: no está conectado, o falló.
    # MEXA tiene que rendirse, NO empujar a ciegas: sin cámara Y sin
    # ultrasonido no queda un solo sentido que diga que hay alguien.
    frente = FrenteFalso([None])
    restaurar = _montar(CamaraFalsa(), frente, PACIENCIA_FRENTE_S=0.4)
    try:
        inicio = time.monotonic()
        motivo = navegacion._acercamiento_a_ciegas(time.time() + 30)
        duro = time.monotonic() - inicio
    finally:
        restaurar()
    _revisar(motivo == "sin_sensor", "Sensor mudo -> se rinde, no empuja ciego",
             f"motivo={motivo!r} (esperado 'sin_sensor'), duró {duro:.2f}s")
    _revisar(duro < 1.5, "Y se rinde RÁPIDO",
             f"{duro:.2f}s (tope de paciencia 0.4s + margen)")

    # El sensor contesta perfecto y dice: no hay NADIE dentro de los 2m.
    # Es un dato, no una falla. El visitante no está enfrente.
    frente = FrenteFalso([SIN_ECO_CM])
    restaurar = _montar(CamaraFalsa(), frente, PACIENCIA_FRENTE_S=0.4)
    try:
        motivo = navegacion._acercamiento_a_ciegas(time.time() + 30)
    finally:
        restaurar()
    _revisar(motivo == "nadie", "999cm sostenido -> nadie al frente, aborta",
             f"motivo={motivo!r} (esperado 'nadie')")

    # Un eco perdido suelto NO puede abortar la maniobra: un cuerpo es
    # blando y oblicuo, el ultrasónico lo pierde de a ratos.
    frente = FrenteFalso([120.0, SIN_ECO_CM, 110.0, SIN_ECO_CM, 90.0, 65.0])
    restaurar = _montar(CamaraFalsa(), frente, PACIENCIA_FRENTE_S=0.4)
    try:
        motivo = navegacion._acercamiento_a_ciegas(time.time() + 30)
    finally:
        restaurar()
    _revisar(motivo == "medido", "Ecos perdidos sueltos NO abortan",
             f"motivo={motivo!r} (esperado 'medido')")

    # El Arduino frena solo: alguien se metió delante.
    frente = FrenteFalso([150.0, 140.0, 130.0], freno_en=3)
    restaurar = _montar(CamaraFalsa(), frente)
    try:
        motivo = navegacion._acercamiento_a_ciegas(time.time() + 30)
    finally:
        restaurar()
    _revisar(motivo == "reflejo", "El reflejo del firmware manda",
             f"motivo={motivo!r} (esperado 'reflejo')")

    # Hay alguien, pero lejos y el tiempo se acaba antes de llegar.
    # A 2.5cm/s esto es lo NORMAL, no la excepción.
    frente = FrenteFalso([190.0])
    restaurar = _montar(CamaraFalsa(), frente, CIEGO_TIMEOUT_S=0.5)
    try:
        motivo = navegacion._acercamiento_a_ciegas(time.time() + 30)
    finally:
        restaurar()
    _revisar(motivo == "tope", "Se acaba el tiempo antes de llegar",
             f"motivo={motivo!r} (esperado 'tope')")

    # El presupuesto de TODA la maniobra manda sobre el del fallback.
    frente = FrenteFalso([190.0])
    restaurar = _montar(CamaraFalsa(), frente, CIEGO_TIMEOUT_S=30.0)
    try:
        inicio = time.monotonic()
        motivo = navegacion._acercamiento_a_ciegas(time.time() + 0.5)
        duro = time.monotonic() - inicio
    finally:
        restaurar()
    _revisar(motivo == "tope" and duro < 2.0, "Respeta el deadline de la maniobra",
             f"motivo={motivo!r}, duró {duro:.2f}s (deadline 0.5s)")


# ── Etapa 2: cableado dentro de acercarse_a_usuario ───────────
def etapa_cableado():
    print("\n[2] Cableado en acercarse_a_usuario()")

    # LA REGRESIÓN QUE ORIGINA TODO ESTO: cámara velada, visitante a 1.2m.
    # Antes: un solo 'S'. Ahora tiene que caminar.
    camara = CamaraFalsa()  # nunca ve una cara
    frente = FrenteFalso([120.0, 105.0, 90.0, 78.0, 66.0])
    restaurar = _montar(camara, frente)
    try:
        eventos = navegacion.acercarse_a_usuario()
    finally:
        restaurar()
    cmds = _comandos(eventos)
    _revisar("F" in cmds, "Cámara ciega + alguien a 1.2m -> MEXA CAMINA",
             f"comandos={cmds!r} (antes de esto era 'S' pelado)")
    _revisar(cmds.endswith("S"), "Y frena al terminar",
             f"comandos={cmds!r}")

    # Cámara ciega y NADIE al frente: no se mueve de más.
    camara = CamaraFalsa()
    frente = FrenteFalso([SIN_ECO_CM])
    restaurar = _montar(camara, frente, PACIENCIA_FRENTE_S=0.4)
    try:
        inicio = time.monotonic()
        eventos = navegacion.acercarse_a_usuario()
        duro = time.monotonic() - inicio
    finally:
        restaurar()
    _revisar(duro < 3.0, "Cámara ciega + sala vacía -> aborta rápido",
             f"duró {duro:.2f}s, comandos={_comandos(eventos)!r}")

    # NO REGRESIÓN: si la cámara VE, el fallback no se mete. La cara se ve
    # centrada y grande hasta el techo de seguridad.
    camara = CamaraFalsa([("centro", 0.10), ("centro", 0.25), ("centro", 0.45)])
    frente = FrenteFalso([None])
    restaurar = _montar(camara, frente)
    try:
        eventos = navegacion.acercarse_a_usuario()
    finally:
        restaurar()
    cmds = _comandos(eventos)
    _revisar(camara.llamadas == 3, "Con cara visible sigue mandando la cámara",
             f"{camara.llamadas} lecturas de cámara, comandos={cmds!r}")

    # NO REGRESIÓN: cara vista y perdida LEJOS = la persona se fue.
    # El fallback NO debe salir a buscarla: no es un buscador de gente.
    camara = CamaraFalsa([("centro", 0.05)])
    frente = FrenteFalso([None])
    restaurar = _montar(camara, frente, PACIENCIA_FRENTE_S=0.4)
    try:
        inicio = time.monotonic()
        navegacion.acercarse_a_usuario()
        duro = time.monotonic() - inicio
    finally:
        restaurar()
    _revisar(duro < 1.0, "Cara perdida LEJOS -> no sale a buscar a nadie",
             f"duró {duro:.2f}s (si el fallback se metiera, tardaría más)")


def main():
    print("=" * 62)
    print("  MEXA — ¿puede acercarse sin la cámara?")
    print("=" * 62)
    etapa_fallback()
    etapa_cableado()

    print("\n" + "=" * 62)
    if _fallos:
        print(f"  ✗ {len(_fallos)} verificación(es) fallaron:")
        for f in _fallos:
            print(f"      - {f}")
        return 1
    print("  ✓ Todas las verificaciones pasaron.")
    print("  · PENDIENTE de validar en hardware: parate a ~1.5m de MEXA con")
    print("    la cámara tapada, corré python3 main.py y mirá las líneas")
    print("    [NAV] A ciegas:. El sobre útil es ~70-200cm (el frontal no")
    print("    ve más lejos) y a 2.5cm/s cerrar 130cm son ~52s.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
