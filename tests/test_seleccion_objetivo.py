# ============================================================
#  MEXA — Verificación de la ELECCIÓN DE OBJETIVO de la cámara
#
#  MEXA no vive frente a una persona: vive en una sala donde la
#  gente anda en grupo. La pregunta que este test responde es
#  "¿a QUIÉN elige cuando hay varios?", y la respuesta que se
#  busca es "al que tiene en frente y la está mirando".
#
#  IMPORTANTE — el límite de lo medible: MEXA tiene UN micrófono
#  mono (modulo_audio: channels=1), así que no hay dirección de
#  llegada del sonido; y YuNet da 5 landmarks cuyas dos bocas son
#  las COMISURAS, que dan ancho y no apertura, así que tampoco se
#  puede ver quién mueve los labios. "Quién habla" NO es
#  observable con este hardware. Lo que sí se observa es quién
#  MIRA a MEXA, y eso es lo que acá se llama frontalidad.
#
#  Los datos son las fotos reales de tests/diag_frames/, tomadas
#  con MEXA en su sala. Como en esas fotos hay UNA sola persona,
#  los casos de varias personas se COMPONEN pegando caras reales
#  de esas mismas fotos en un lienzo: caras reales, arreglo
#  sintético. Lo que sigue sin estar validado con datos reales es
#  el caso de dos personas DISTINTAS (ver el resumen final).
#
#  Correr con:  python3 tests/test_seleccion_objetivo.py
# ============================================================

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos.modulo_camara import (Cara, _buscar_caras, _puntuar, _detector,
                                   _Seguidor, _DESVIO_FRONTAL, _DESVIO_PERFIL)

FRAMES = "tests/diag_frames"

# Frames clasificados A MANO mirando las fotos. Son la misma persona en la
# misma sala: lo único que cambia entre los dos grupos es hacia dónde mira.
_DE_FRENTE = ["frame_06", "frame_07", "frame_08", "frame_11", "frame_14"]
_DE_PERFIL = ["frame_12", "frame_13"]

_fallos: list[str] = []


def _revisar(ok: bool, titulo: str, detalle: str) -> None:
    print(f"  {'✓' if ok else '✗'} {titulo}: {detalle}")
    if not ok:
        _fallos.append(titulo)


def _cargar(nombre):
    ruta = os.path.join(FRAMES, f"{nombre}.jpg")
    img = cv2.imread(ruta)
    if img is None:
        raise FileNotFoundError(ruta)
    return img


def _cara_unica(img) -> Cara:
    """La única cara del frame. Los frames de diag tienen una sola persona."""
    caras = _buscar_caras(img)
    if not caras:
        raise AssertionError("frame sin cara")
    return max(caras, key=lambda c: c.score)


# ── 1. Frontalidad: ¿separa mirar de no mirar? ────────────────
def etapa_frontalidad() -> None:
    """La señal nueva. Si no separa estos dos grupos, no separa nada."""
    print("\n[TEST] 1/5 — FRONTALIDAD sobre fotos reales")
    for nombre in _DE_FRENTE:
        f = _cara_unica(_cargar(nombre)).frontalidad
        _revisar(f >= 0.9, f"{nombre} (mirando a MEXA)", f"frontalidad={f:.2f} (se espera >=0.90)")
    for nombre in _DE_PERFIL:
        f = _cara_unica(_cargar(nombre)).frontalidad
        _revisar(f <= 0.1, f"{nombre} (de perfil)", f"frontalidad={f:.2f} (se espera <=0.10)")
    print(f"  · umbrales calibrados: frente<={_DESVIO_FRONTAL}, perfil>={_DESVIO_PERFIL}")


# ── 2. Composición de escenas con varias personas ─────────────
def _recorte(nombre, margen=1.0):
    """Recorta la cara de un frame real con margen alrededor, para poder
    pegarla en otro lienzo sin que quede un parche cuadrado sobre la cara."""
    img = _cargar(nombre)
    c = _cara_unica(img)
    px, py = int(c.w * margen), int(c.h * margen)
    return img[max(0, c.y - py):c.y + c.h + py,
               max(0, c.x - px):c.x + c.w + px]


def _escena(*personas, ancho=1280, alto=720):
    """Lienzo con varias caras reales pegadas. Cada persona es
    (nombre_frame, centro_x_relativo, escala)."""
    lienzo = np.full((alto, ancho, 3), 60, np.uint8)
    for nombre, cx_rel, escala in personas:
        rec = _recorte(nombre)
        if escala != 1.0:
            rec = cv2.resize(rec, None, fx=escala, fy=escala)
        # Al escalar, el recorte puede pasarse del lienzo: se lo recorta a lo
        # que entra (la cara queda igual; sólo se pierde margen de fondo).
        rec = rec[:alto, :ancho]
        h, w = rec.shape[:2]
        x, y = int(ancho * cx_rel) - w // 2, alto // 2 - h // 2
        x, y = max(0, min(x, ancho - w)), max(0, min(y, alto - h))
        lienzo[y:y + h, x:x + w] = rec
    return lienzo


def _objetivo(escena) -> Cara:
    """La cara que MEXA elegiría en esta escena (sin enganche previo)."""
    alto, ancho = escena.shape[:2]
    caras = _buscar_caras(escena)
    assert caras, "la escena compuesta no produjo ninguna cara"
    return max(caras, key=lambda c: _puntuar(c, ancho, alto))


def etapa_eleccion() -> None:
    """El caso que motivó todo esto: dos personas, MEXA tiene que elegir una."""
    print("\n[TEST] 2/5 — ELECCIÓN entre dos personas")

    # (a) Mismo tamaño, misma distancia al centro: decide sólo la mirada.
    #     Con la regla vieja (cara más grande) esto era un volado.
    escena = _escena(("frame_13", 0.30, 1.0), ("frame_14", 0.70, 1.0))
    obj = _objetivo(escena)
    _revisar(obj.frontalidad >= 0.9,
             "empate de tamaño -> gana el que mira",
             f"elegido con frontalidad={obj.frontalidad:.2f}, cx={(obj.x + obj.w / 2) / 1280:.2f}")

    # (b) El de perfil está MÁS CERCA (cara más grande). Aun así debe ganar
    #     el que mira: es el que le está hablando a MEXA.
    escena = _escena(("frame_13", 0.30, 1.25), ("frame_14", 0.70, 1.0))
    obj = _objetivo(escena)
    _revisar(obj.frontalidad >= 0.9,
             "el de perfil está más cerca -> igual gana el que mira",
             f"elegido con frontalidad={obj.frontalidad:.2f}, tam={obj.h / 720:.0%}")

    # (c) Los DOS miran de frente: ahí sí manda la cercanía.
    escena = _escena(("frame_08", 0.30, 1.30), ("frame_14", 0.70, 0.75))
    obj = _objetivo(escena)
    _revisar((obj.x + obj.w / 2) / 1280 < 0.5,
             "los dos miran -> gana el más cercano",
             f"elegido cx={(obj.x + obj.w / 2) / 1280:.2f}, tam={obj.h / 720:.0%}")


# ── 3. ¿Hasta dónde aguanta la frontalidad? ───────────────────
def etapa_limite() -> None:
    """Dato de calibración: cuánto más cerca tiene que estar el de perfil para
    darle vuelta al que mira. No falla el test; informa el margen real."""
    print("\n[TEST] 3/5 — MARGEN: cuánto gana la mirada sobre la cercanía")
    quiebre = None
    for escala in [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2.0]:
        obj = _objetivo(_escena(("frame_13", 0.30, escala), ("frame_14", 0.70, 1.0)))
        if obj.frontalidad < 0.5:
            quiebre = escala
            break
    if quiebre is None:
        print("  · el que mira gana hasta 2.0x de tamaño del otro (no se dio vuelta)")
    else:
        print(f"  · el de perfil se impone recién a {quiebre:.1f}x el tamaño del que mira")
    _revisar(quiebre is None or quiebre >= 1.4,
             "la mirada no se pierde por diferencias chicas de distancia",
             f"quiebre={'nunca' if quiebre is None else f'{quiebre:.1f}x'} (se espera >=1.4x)")


# ── 4. Enganche: no cambiar de persona a mitad de camino ──────
def etapa_enganche() -> None:
    """El zigzagueo: sin enganche, dos puntajes parecidos hacen que la elección
    se dé vuelta frame a frame y MEXA no llega a ninguna de las dos."""
    print("\n[TEST] 4/5 — ENGANCHE temporal")
    seg = _Seguidor()
    izq = Cara(300, 300, 150, 150, 1.0, 0.9)      # a quien MEXA enganchó
    der = Cara(800, 300, 152, 152, 1.0, 0.9)      # rival, apenas MÁS GRANDE

    # Se engancha a `izq` estando sola, y recién entonces aparece `der`. Sin
    # enganche, `der` ganaría por ser más grande y MEXA cambiaría de persona a
    # mitad del acercamiento; con enganche, la ventaja mínima no alcanza.
    seg.elegir([izq], 1280, 720)
    elegidos = [seg.elegir([izq, der], 1280, 720).x for _ in range(6)]
    _revisar(set(elegidos) == {izq.x}, "no suelta al objetivo por una ventaja mínima",
             f"eligió siempre x={elegidos[0]} en {len(elegidos)} lecturas "
             f"(el rival x={der.x} era más grande)")

    # Un rival CLARAMENTE mejor sí debe robarle el objetivo.
    seg.reiniciar()
    seg.elegir([Cara(300, 300, 120, 120, 0.0, 0.9)], 1280, 720)   # engancha al de perfil
    nuevo = seg.elegir([Cara(300, 300, 120, 120, 0.0, 0.9),
                        Cara(800, 300, 200, 200, 1.0, 0.9)], 1280, 720)
    _revisar(nuevo.x == 800, "sí cambia si otro es claramente mejor",
             f"pasó al objetivo x={nuevo.x}")

    # Si el objetivo desaparece, lo suelta tras unas lecturas y engancha otro.
    seg.reiniciar()
    seg.elegir([izq], 1280, 720)
    sueltas = [seg.elegir([der], 1280, 720) for _ in range(5)]
    _revisar(sueltas[0] is None and sueltas[-1] is not None,
             "suelta al objetivo perdido y engancha al que queda",
             f"lecturas: {['-' if s is None else s.x for s in sueltas]}")


# ── 5. Regresión de color ─────────────────────────────────────
def etapa_color() -> None:
    """Este test existe porque el bug ya pasó: se le entregaba a YuNet la
    imagen con R y B cruzados y el detector se quedaba ciego en la mayoría de
    los frames. Si alguien vuelve a meter un cvtColor de más, esto lo caza."""
    print("\n[TEST] 5/5 — REGRESIÓN de orden de canales (R/B)")
    _detector.setScoreThreshold(0.5)
    try:
        nombres = sorted(f[:-4] for f in os.listdir(FRAMES) if f.endswith(".jpg"))
        bien = sum(1 for n in nombres if _buscar_caras(_cargar(n)))
        cruzado = sum(1 for n in nombres
                      if _buscar_caras(cv2.cvtColor(_cargar(n), cv2.COLOR_BGR2RGB)))
    finally:
        _detector.setScoreThreshold(0.7)
    print(f"  · {len(nombres)} frames: con canales correctos detecta en {bien}, "
          f"cruzados en {cruzado}")
    _revisar(bien > cruzado, "los canales correctos detectan más caras",
             f"{bien} vs {cruzado}")


def main() -> int:
    if not os.path.isdir(FRAMES) or not os.listdir(FRAMES):
        print(f"[TEST] No hay fotos en {FRAMES}/. Generalas con MEXA y la cámara:")
        print("[TEST]   python3 tests/diagnostico_deteccion.py")
        return 2

    print("=" * 62)
    print("  MEXA — ¿a quién elige la cámara cuando hay varias personas?")
    print("=" * 62)
    etapa_frontalidad()
    etapa_eleccion()
    etapa_limite()
    etapa_enganche()
    etapa_color()

    print("\n" + "=" * 62)
    if _fallos:
        print(f"  ✗ {len(_fallos)} verificación(es) fallaron:")
        for f in _fallos:
            print(f"      - {f}")
        return 1
    print("  ✓ Todas las verificaciones pasaron.")
    print("  · PENDIENTE de validar en hardware: dos personas DISTINTAS de")
    print("    verdad (las escenas de varias personas se componen con caras")
    print("    de la misma persona). Parate con alguien frente a MEXA y corré")
    print("    python3 tests/diagnostico_deteccion.py para confirmarlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
