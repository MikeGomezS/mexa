#!/usr/bin/env python3
"""
MEXA — Proceso de animación de la cara.
Se lanza como subproceso desde modulo_proyector.pantalla_bienvenida().
Uso: python3 _cara_animada.py W H X Y [expresion]

Recibe comandos por stdin para cambiar de estado en tiempo real:
  expresion:<nombre>\n     -> cambia de pose (transición animada, sin saltos)
  volumen:<0.0-1.0>\n      -> sincroniza la boca con el audio que está saliendo

Expresiones: idle, hablando, escuchando, pensando, feliz, sorprendido, triste,
             confundido, guino, emocionado, dormido.

NO HAY "enojado", y es a propósito: MEXA es una guía de museo y no tiene
ninguna rama del diálogo donde enojarse. La pose existía sin cablear, así
que era una cara que nadie iba a ver nunca. `tests/test_expresiones.py`
avisa si alguien pide una expresión que no está.

ARQUITECTURA
────────────
La cara NO se dibuja con un if/elif por expresión. Se separa en tres capas:

  1. TABLA DE POSES (datos)   — cada emoción es un juego de valores objetivo.
  2. MOTOR DE RESORTES        — persigue esos objetivos con inercia y rebote,
                                así ninguna expresión "salta": entra con snap
                                de dibujo animado.
  3. CAPA DE VIDA             — parpadeo irregular, microsacadas de mirada,
                                respiración, squash & stretch y micro-gestos
                                espontáneos. Corre siempre, por encima de la
                                pose: es lo que evita que una cara quieta se
                                lea como un LOOP.
  4. CANAL DE VOZ             — el volumen del audio no mueve solo la boca:
                                con envolvente lenta levanta las cejas, abre
                                los ojos y hace cabecear. Hablar es actuar,
                                no abrir y cerrar una boca.

Agregar una expresión nueva = una línea más en POSES. Nada más.
"""
import math
import os
import random
import select
import signal
import sys
import time
from dataclasses import dataclass, fields, replace

import pygame
from pygame import gfxdraw

# ── Paleta ───────────────────────────────────────────────────
# Único lugar donde vive el color de la cara. Tocar acá, no en los dibujos.
FONDO_ARRIBA = (16, 62, 148)     # degradado del lienzo: arriba
FONDO_ABAJO  = (42, 150, 238)    # degradado del lienzo: abajo
TINTA        = (16, 20, 32)      # contornos, pupilas, cejas y línea de párpado
ESCLERA      = (255, 255, 255)   # blanco del ojo y brillo grande
IRIS         = (96, 210, 240)    # iris (lo que le da "alma" a la mirada)
IRIS_BORDE   = (28, 112, 166)    # anillo exterior del iris
BRILLO       = (176, 232, 255)   # brillo secundario, abajo a la derecha
BOCA         = (214, 64, 88)
LENGUA       = (240, 126, 142)
RUBOR        = (255, 96, 116)
SIMBOLO      = (255, 232, 140)   # símbolos flotantes (?, !, Z, estrellas)
GOTA         = (168, 224, 255)

W         = int(sys.argv[1]) if len(sys.argv) > 1 else 1920
H         = int(sys.argv[2]) if len(sys.argv) > 2 else 1080
X         = int(sys.argv[3]) if len(sys.argv) > 3 else 0
Y         = int(sys.argv[4]) if len(sys.argv) > 4 else 0
expresion = sys.argv[5]       if len(sys.argv) > 5 else "idle"

if not os.environ.get("DISPLAY"):
    os.environ["DISPLAY"] = ":0"
os.environ["SDL_VIDEO_WINDOW_POS"] = f"{X},{Y}"

pygame.init()
pantalla = pygame.display.set_mode((W, H), pygame.NOFRAME | pygame.FULLSCREEN)
pygame.mouse.set_visible(False)

e     = H / 1080.0               # escala: todos los valores están en px @1080p
FPS   = 30
DT    = 1.0 / FPS
clock = pygame.time.Clock()
t     = 0.0

# Geometría base de la cara, en px @1080p.
R_OJO    = 132.0
SEP_OJOS = 232.0
OJO_DY   = -74.0                 # los ojos, sobre el centro
BOCA_DY  = 206.0                 # la boca, bajo el centro
CEJA_W   = 182.0
CEJA_GR  = 24.0
BOCA_AMP = 62.0                  # cuánto curva la sonrisa a curva=1.0
BOCA_GR  = 19.0                  # grosor del labio con la boca cerrada
LINEA    = 0.62                  # altura donde se encuentran los dos párpados
ARCO_CIERRE = 0.11               # arco del ojo cerrado (recto se ve muerto)

_volumen:          float = 0.0
_volumen_suave:    float = 0.0   # rápida: sigue sílabas, mueve la boca
_voz_lenta:        float = 0.0   # lenta: sigue la FRASE, mueve cejas y cabeza
_t_ultimo_volumen: float = 0.0


def _salir(signum, frame):
    pygame.quit()
    sys.exit(0)


signal.signal(signal.SIGTERM, _salir)
signal.signal(signal.SIGINT,  _salir)


# ── 1. TABLA DE POSES ────────────────────────────────────────
@dataclass
class Pose:
    """Un gesto congelado. Todo float, para que el motor pueda interpolarlo."""
    ojo_esc:        float = 1.00   # tamaño del ojo
    ojo_ancho:      float = 1.00   # achatado horizontal
    parp_sup:       float = 0.00   # 0 abierto … 1 párpado superior cerrado
    parp_inf:       float = 0.00   # 0 abierto … 1 párpado inferior cerrado
    parp_sup_curva: float = 0.00   # − arquea hacia ARRIBA -> ojo feliz ^^
    parp_inf_curva: float = 0.00   # + arquea hacia arriba el párpado de abajo
    guino:          float = 0.00   # cierra SOLO el ojo derecho
    pupila_esc:     float = 1.00   # dilatada = emoción; contraída = enojo
    ceja_alt:       float = 0.00   # altura sobre el ojo
    ceja_ang:       float = 0.00   # grados; + = punta interna ABAJO (enojo)
    ceja_asim:      float = 0.00   # extra de altura solo en la ceja izquierda
    ceja_arco:      float = 12.0   # curvatura de la ceja
    boca_ancho:     float = 1.00
    boca_curva:     float = 0.40   # −1 tristeza … +1 sonrisa
    boca_abre:      float = 0.00   # apertura base
    boca_sesgo:     float = 0.00   # boca torcida (una comisura más alta)
    boca_vol:       float = 0.00   # cuánto responde la BOCA al audio
    ceja_vol:       float = 0.00   # cuánto suben las CEJAS con el énfasis
    ojo_vol:        float = 0.00   # cuánto se abren los OJOS con el énfasis
    bob_vol:        float = 0.00   # cuánto cabecea de más al hablar fuerte
    gestos:         float = 0.00   # cuánto se permite gestos espontáneos
    rubor:          float = 0.00
    mirada_x:       float = 0.00   # dirección fija de la mirada (−1 … 1)
    mirada_y:       float = 0.00
    vaga:           float = 1.00   # cuánto deambula la mirada sola
    bob_amp:        float = 9.00   # rebote vertical de la cabeza
    bob_vel:        float = 1.10
    tilt:           float = 0.00   # inclinación de la cabeza, en grados
    parpadea:       float = 1.00   # 0 = no parpadea


_N = Pose()

POSES: dict[str, Pose] = {
    # — las cinco de siempre, ahora con vida —
    # Una cara en reposo perfectamente simétrica se lee como un ícono, no como
    # alguien. La asimetría chica de la ceja es lo que le da carácter.
    "idle": replace(
        _N, boca_curva=0.62, boca_ancho=1.02, ceja_arco=16, ceja_asim=8,
        bob_amp=12, bob_vel=1.1, vaga=1.0, gestos=1.0,
    ),
    # Hablar NO es abrir y cerrar la boca: son las cejas subiendo con el
    # énfasis y la cabeza cabeceando en las sílabas fuertes. Eso lo hacen
    # ceja_vol / ojo_vol / bob_vol, enganchados a la envolvente lenta de voz.
    "hablando": replace(
        _N, boca_curva=0.38, boca_abre=14, boca_vol=1.0, boca_ancho=1.08,
        ceja_alt=10, ceja_arco=15, ceja_vol=30, ojo_vol=0.55, bob_vol=11,
        bob_amp=8, bob_vel=2.0, vaga=0.45, pupila_esc=1.06, gestos=0.6,
    ),
    # Escuchar se dibuja INCLINANDO la cabeza y levantando UNA ceja. Con las
    # dos cejas parejas queda cara de sorpresa, no de atención.
    "escuchando": replace(
        _N, ojo_esc=1.24, pupila_esc=1.20, ceja_alt=34, ceja_arco=20,
        ceja_asim=18, boca_curva=0.60, boca_ancho=0.84, tilt=-13,
        bob_amp=6, bob_vel=0.9, vaga=0.60, gestos=0.85,
    ),
    # Pensar no es MIRAR fijo a un punto: es la mirada buscando. Por eso vaga
    # sube de 0.12 a 0.34 — sigue sesgada arriba-derecha, pero se mueve.
    "pensando": replace(
        _N, parp_sup=0.30, parp_sup_curva=-0.10, pupila_esc=0.88, ceja_alt=8,
        ceja_asim=40, ceja_ang=-8, mirada_x=0.55, mirada_y=-0.58, vaga=0.34,
        boca_curva=-0.12, boca_ancho=0.66, boca_sesgo=0.80, tilt=8,
        bob_amp=6, bob_vel=0.75, gestos=0.5,
    ),
    "feliz": replace(
        _N, parp_sup=0.88, parp_sup_curva=-0.62, parp_inf=1.00,
        boca_curva=1.00, boca_abre=32, boca_ancho=1.28, rubor=1.0,
        boca_vol=0.80, ceja_vol=18, bob_vol=10,
        ceja_alt=18, ceja_arco=20, bob_amp=24, bob_vel=2.6, vaga=0.30, gestos=0.5,
    ),
    # — nuevas —
    "sorprendido": replace(
        _N, ojo_esc=1.34, pupila_esc=0.58, ceja_alt=44, ceja_arco=26,
        boca_abre=60, boca_ancho=0.66, boca_curva=0.0, bob_amp=16,
        bob_vel=3.2, vaga=0.15,
    ),
    "triste": replace(
        _N, parp_sup=0.26, parp_sup_curva=0.14, pupila_esc=1.18, ceja_ang=-18,
        ceja_alt=0, ceja_arco=4, boca_curva=-0.80, boca_ancho=0.86,
        boca_vol=0.70, ceja_vol=10, bob_vol=4,
        mirada_y=0.45, vaga=0.25, tilt=4, bob_amp=5, bob_vel=0.6, gestos=0.30,
    ),
    "confundido": replace(
        _N, ceja_asim=44, ceja_ang=11, parp_sup=0.14, tilt=-15,
        boca_sesgo=0.95, boca_curva=-0.18, boca_ancho=0.62, mirada_x=-0.38,
        boca_vol=0.90, ceja_vol=20, bob_vol=6,
        mirada_y=-0.28, vaga=0.40, bob_amp=7, bob_vel=0.9, gestos=0.55,
    ),
    "guino": replace(
        _N, guino=1.0, parp_sup=0.40, parp_sup_curva=-0.34, parp_inf=0.55,
        boca_curva=0.88, boca_abre=18, boca_ancho=1.10, boca_sesgo=0.55,
        rubor=0.7, ceja_alt=15, tilt=-7, bob_amp=14, bob_vel=2.2, vaga=0.25,
    ),
    "emocionado": replace(
        _N, ojo_esc=1.20, pupila_esc=1.34, ceja_alt=30, ceja_arco=22,
        boca_curva=0.92, boca_abre=52, boca_ancho=1.20, rubor=0.85,
        boca_vol=0.60, ceja_vol=22, bob_vol=14,
        bob_amp=26, bob_vel=3.4, vaga=0.20,
    ),
    "dormido": replace(
        _N, parp_sup=1.0, parp_inf=1.0, parp_sup_curva=-ARCO_CIERRE,
        parp_inf_curva=ARCO_CIERRE, ceja_alt=-6, boca_curva=0.20,
        boca_ancho=0.52, boca_abre=8, bob_amp=8, bob_vel=0.45,
        parpadea=0.0, vaga=0.0,
    ),
}

# Símbolo flotante que acompaña a cada expresión (el recurso más caricaturesco).
SIMBOLOS: dict[str, str] = {
    "pensando":    "?",
    "confundido":  "?",
    "sorprendido": "!",
    "triste":      "gota",
    "emocionado":  "estrellas",
    "dormido":     "Z",
}


# ── 2. MOTOR DE RESORTES ─────────────────────────────────────
# Un resorte subamortiguado: el valor pasa un poco de largo y vuelve. Ese
# sobrepaso del ~20 % es EXACTAMENTE el "snap" del dibujo animado. Con un lerp
# común la cara llega suave, pero muerta.
K_RESORTE = 140.0
AMORTIGUA = 0.72

_CAMPOS = tuple(f.name for f in fields(Pose))
_actual = replace(POSES.get(expresion, POSES["idle"]))
_vel    = Pose(**{c: 0.0 for c in _CAMPOS})


def _avanzar_resortes(objetivo: Pose) -> None:
    for c in _CAMPOS:
        a = getattr(_actual, c)
        v = (getattr(_vel, c) + (getattr(objetivo, c) - a) * K_RESORTE * DT) * AMORTIGUA
        setattr(_vel, c, v)
        setattr(_actual, c, a + v * DT)


# ── 3. CAPA DE VIDA ──────────────────────────────────────────
# Parpadeo IRREGULAR. Un `t % periodo` parpadea como metrónomo y delata a la
# máquina; un ojo real cierra rápido, aguanta un instante y abre más lento.
_CIERRA, _AGUANTA, _ABRE = 0.07, 0.05, 0.14
_prox_parpadeo  = random.uniform(1.5, 3.5)
_parpadeo_t     = -1.0
_parpadeo_doble = False


def _parpadeo(ahora: float, activo: float) -> float:
    """Devuelve 0 (ojo abierto) … 1 (ojo cerrado)."""
    global _prox_parpadeo, _parpadeo_t, _parpadeo_doble

    if _parpadeo_t < 0 and activo > 0.5 and ahora >= _prox_parpadeo:
        _parpadeo_t = ahora
        if not _parpadeo_doble and random.random() < 0.22:
            _parpadeo_doble = True        # de a ratos, parpadeo doble

    if _parpadeo_t < 0:
        return 0.0

    u = ahora - _parpadeo_t
    if u < _CIERRA:
        return u / _CIERRA
    if u < _CIERRA + _AGUANTA:
        return 1.0
    if u < _CIERRA + _AGUANTA + _ABRE:
        return 1.0 - (u - _CIERRA - _AGUANTA) / _ABRE

    _parpadeo_t = -1.0
    if _parpadeo_doble:
        _parpadeo_doble = False
        _prox_parpadeo  = ahora + 0.13
    else:
        _prox_parpadeo = ahora + random.uniform(1.8, 5.5)
    return 0.0


# Microsacadas: la mirada salta a un punto cercano cada tanto y tiembla apenas.
# Es el recurso más barato y más potente para que una cara parezca consciente.
_mirada      = [0.0, 0.0]
_mirada_obj  = [0.0, 0.0]
_prox_sacada = 1.0


def _mirar(ahora: float, vaga: float) -> tuple[float, float]:
    global _prox_sacada
    if vaga > 0.05 and ahora >= _prox_sacada:
        ang = random.uniform(0, math.tau)
        rad = random.uniform(0.15, 0.75)
        _mirada_obj[0] = math.cos(ang) * rad
        _mirada_obj[1] = math.sin(ang) * rad * 0.7
        _prox_sacada   = ahora + random.uniform(0.7, 3.2)

    for i in (0, 1):                      # la sacada es rápida, no elástica
        _mirada[i] += (_mirada_obj[i] - _mirada[i]) * 0.35

    temblor = math.sin(ahora * 13.0) * 0.012
    return _mirada[0] * vaga + temblor, _mirada[1] * vaga


# Micro-gestos: cada tantos segundos la cara hace algo chico y espontáneo —
# levanta las cejas, ladea la cabeza, entrecierra los ojos. Sin esto una pose
# quieta se vuelve un LOOP, y el ojo humano detecta un loop en segundos.
_GESTOS       = ("ceja", "tilt", "bizqueo")
_gesto_nombre: str | None = None
_gesto_t      = -1.0
_gesto_dur    = 0.0
_gesto_mag    = 0.0
_gesto_signo  = 1.0
_prox_gesto   = 4.0


def _micro_gesto(ahora: float, permiso: float) -> tuple[float, float, float]:
    """Devuelve el desvío del cuadro: (ceja en px, tilt en grados, párpado)."""
    global _gesto_nombre, _gesto_t, _gesto_dur, _gesto_mag, _gesto_signo, _prox_gesto

    if _gesto_nombre is None:
        if permiso > 0.2 and ahora >= _prox_gesto:
            _gesto_nombre = random.choice(_GESTOS)
            _gesto_t      = ahora
            _gesto_dur    = random.uniform(0.55, 1.20)
            _gesto_mag    = random.uniform(0.6, 1.0) * permiso
            _gesto_signo  = random.choice((-1.0, 1.0))
        return 0.0, 0.0, 0.0

    u = (ahora - _gesto_t) / _gesto_dur
    if u >= 1.0:
        _gesto_nombre = None
        _prox_gesto   = ahora + random.uniform(2.5, 7.0)
        return 0.0, 0.0, 0.0

    # Campana: entra y sale suave, con el pico en el medio del gesto.
    k = math.sin(math.pi * u) * _gesto_mag
    if _gesto_nombre == "ceja":
        return 18.0 * k, 0.0, 0.0
    if _gesto_nombre == "tilt":
        return 0.0, 5.0 * k * _gesto_signo, 0.0
    return 0.0, 0.0, 0.17 * k


# ── Recursos que se calculan una sola vez ────────────────────
_CACHE_HALO: dict = {}
_CACHE_SILUETA: dict = {}


def _color_fondo(y: int) -> tuple[int, int, int]:
    k = (y / max(1, H - 1)) ** 0.85
    return tuple(int(a + (b - a) * k) for a, b in zip(FONDO_ARRIBA, FONDO_ABAJO))


def _construir_fondo() -> pygame.Surface:
    s = pygame.Surface((W, H))
    for y in range(H):
        pygame.draw.line(s, _color_fondo(y), (0, y), (W, y))

    # Viñeta: se arma chiquita y se estira. Oscurece los bordes y empuja la
    # atención al centro, que es donde está la cara.
    vw, vh = 96, 54
    v = pygame.Surface((vw, vh), pygame.SRCALPHA)
    for vy in range(vh):
        for vx in range(vw):
            dx = (vx - vw / 2) / (vw / 2)
            dy = (vy - vh / 2) / (vh / 2)
            d  = min(1.0, math.hypot(dx, dy) / 1.30)
            v.set_at((vx, vy), (0, 0, 0, int(115 * d ** 2.2)))
    s.blit(pygame.transform.smoothscale(v, (W, H)), (0, 0))
    return s


def _halo(r: int, color: tuple[int, int, int]) -> pygame.Surface:
    """Resplandor radial, en aditivo: el negro suma cero y hace de fondo."""
    key = (r, color)
    g = _CACHE_HALO.get(key)
    if g is None:
        n = 160
        g = pygame.Surface((n * 2, n * 2))
        for i in range(n, 0, -1):
            k = 0.17 * (1 - i / n) ** 1.7
            pygame.draw.circle(g, tuple(int(c * k) for c in color), (n, n), i)
        g = pygame.transform.smoothscale(g, (max(2, r * 2), max(2, r * 2)))
        _CACHE_HALO[key] = g
    return g


def _silueta_ojo(rx: int, ry: int) -> pygame.Surface:
    """Máscara con la forma del ojo: recorta los párpados contra el contorno."""
    key = (rx, ry)
    m = _CACHE_SILUETA.get(key)
    if m is None:
        m = pygame.Surface((rx * 2 + 2, ry * 2 + 2), pygame.SRCALPHA)
        gfxdraw.filled_ellipse(m, rx, ry, rx, ry, (255, 255, 255, 255))
        gfxdraw.aaellipse(m, rx, ry, rx, ry, (255, 255, 255, 255))
        _CACHE_SILUETA[key] = m
    return m


FONDO  = _construir_fondo()
FUENTE = pygame.font.Font(None, max(48, int(230 * e)))


def _rotar(px: float, py: float, cx: float, cy: float, grados: float):
    if not grados:
        return px, py
    a = math.radians(grados)
    dx, dy = px - cx, py - cy
    c, s = math.cos(a), math.sin(a)
    return cx + dx * c - dy * s, cy + dx * s + dy * c


# ── Dibujo: ojos ─────────────────────────────────────────────
def _borde_parpado(rx: int, ry: int, sup: float, inf: float,
                   curva_sup: float, curva_inf: float):
    """Puntos del borde de cada párpado, en coordenadas de la silueta del ojo.

    Los dos se cierran contra la misma LINEA, así un ojo totalmente cerrado
    queda como un trazo curvo y no como un disco negro.
    """
    n = 24
    arriba = abajo = None
    if sup > 0.004:
        arriba = [(rx + u * rx * 1.25,
                   sup * 2 * ry * LINEA + curva_sup * ry * (1 - u * u))
                  for u in (-1.0 + 2.0 * i / (n - 1) for i in range(n))]
    if inf > 0.004:
        abajo = [(rx + u * rx * 1.25,
                  2 * ry - inf * 2 * ry * (1 - LINEA) - curva_inf * ry * (1 - u * u))
                 for u in (-1.0 + 2.0 * i / (n - 1) for i in range(n))]
    return arriba, abajo


def _dibujar_ojo(centro, p: Pose, rx: int, ry: int, mx: float, my: float,
                 cierre: float) -> None:
    pad = int(16 * e)
    w, h = rx * 2 + pad * 2, ry * 2 + pad * 2
    ojo = pygame.Surface((w, h), pygame.SRCALPHA)
    cx, cy = w // 2, h // 2

    borde = max(3, int(11 * e))
    gfxdraw.filled_ellipse(ojo, cx, cy, rx, ry, TINTA)
    gfxdraw.aaellipse(ojo, cx, cy, rx, ry, TINTA)
    ix, iy = rx - borde, ry - borde
    gfxdraw.filled_ellipse(ojo, cx, cy, ix, iy, ESCLERA)
    gfxdraw.aaellipse(ojo, cx, cy, ix, iy, ESCLERA)

    # Iris + pupila + DOS brillos. El brillo grande arriba y uno chico abajo es
    # lo que separa un ojo "lindo" de un círculo negro.
    r_iris = max(6, int(min(ix, iy) * 0.66))
    px = cx + int(mx * (ix - r_iris) * 0.92)
    py = cy + int(my * (iy - r_iris) * 0.92)
    gfxdraw.filled_circle(ojo, px, py, r_iris, IRIS_BORDE)
    gfxdraw.aacircle(ojo, px, py, r_iris, IRIS_BORDE)
    gfxdraw.filled_circle(ojo, px, py, int(r_iris * 0.84), IRIS)
    gfxdraw.aacircle(ojo, px, py, int(r_iris * 0.84), IRIS)

    r_pup = max(3, int(r_iris * 0.54 * p.pupila_esc))
    gfxdraw.filled_circle(ojo, px, py, r_pup, TINTA)
    gfxdraw.aacircle(ojo, px, py, r_pup, TINTA)

    b1 = max(3, int(r_iris * 0.38))
    bx, by = px - int(r_iris * 0.34), py - int(r_iris * 0.44)
    gfxdraw.filled_circle(ojo, bx, by, b1, ESCLERA)
    gfxdraw.aacircle(ojo, bx, by, b1, ESCLERA)
    b2 = max(2, int(r_iris * 0.18))
    bx, by = px + int(r_iris * 0.42), py + int(r_iris * 0.36)
    gfxdraw.filled_circle(ojo, bx, by, b2, BRILLO)
    gfxdraw.aacircle(ojo, bx, by, b2, BRILLO)

    # Párpados. NO se pintan de negro: se RECORTA el ojo y se dibuja la línea
    # de pestañas. Un ojo cerrado queda como un trazo, que es como se dibuja de
    # verdad — pintarlo negro daba dos agujeros.
    sup = min(1.0, p.parp_sup + cierre * (1.0 - p.parp_sup))
    inf = min(1.0, p.parp_inf + cierre * (1.0 - p.parp_inf))
    abre = 1.0 - cierre
    arriba, abajo = _borde_parpado(
        rx, ry, sup, inf,
        p.parp_sup_curva * abre - ARCO_CIERRE * cierre,
        p.parp_inf_curva * abre + ARCO_CIERRE * cierre,
    )

    if arriba or abajo:
        silueta = _silueta_ojo(rx, ry)
        recorte = silueta.copy()
        if arriba:
            pygame.draw.polygon(recorte, (255, 255, 255, 0),
                                arriba + [(rx * 2.5, -8), (-rx * 0.5, -8)])
        if abajo:
            pygame.draw.polygon(recorte, (255, 255, 255, 0),
                                abajo + [(rx * 2.5, ry * 2 + 8), (-rx * 0.5, ry * 2 + 8)])
        ojo.blit(recorte, (cx - rx, cy - ry), special_flags=pygame.BLEND_RGBA_MULT)

        gl = max(3, int((10 + 8 * max(sup, inf)) * e))
        trazo = pygame.Surface(silueta.get_size(), pygame.SRCALPHA)
        for linea in (arriba, abajo):
            if not linea:
                continue
            pts = ([(int(x), int(y - gl / 2)) for x, y in linea] +
                   [(int(x), int(y + gl / 2)) for x, y in reversed(linea)])
            gfxdraw.filled_polygon(trazo, pts, TINTA)
            gfxdraw.aapolygon(trazo, pts, TINTA)
        trazo.blit(silueta, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        ojo.blit(trazo, (cx - rx, cy - ry))

    if p.tilt:
        ojo = pygame.transform.rotozoom(ojo, -p.tilt, 1.0)
    pantalla.blit(ojo, ojo.get_rect(center=centro))


# ── Dibujo: cejas ────────────────────────────────────────────
def _dibujar_ceja(sx: int, xo: float, yo: float, p: Pose,
                  cx: float, cy: float) -> None:
    ang = math.radians(p.ceja_ang + (p.ceja_asim * 0.35 if sx < 0 else 0.0))
    gr  = max(5, int(CEJA_GR * e))
    n   = 18
    sup, inf = [], []
    for i in range(n):
        u  = -1.0 + 2.0 * i / (n - 1)         # −1 punta externa, +1 interna
        lx = u * CEJA_W * e / 2
        ly = -p.ceja_arco * e * (1 - u * u) + math.tan(ang) * lx
        x, y = _rotar(xo + sx * lx, yo + ly, cx, cy, p.tilt)
        sup.append((int(x), int(y - gr / 2)))
        inf.append((int(x), int(y + gr / 2)))
    pts = sup + inf[::-1]
    gfxdraw.filled_polygon(pantalla, pts, TINTA)
    gfxdraw.aapolygon(pantalla, pts, TINTA)
    for k in (0, n - 1):                      # puntas redondeadas
        ex, ey = sup[k][0], sup[k][1] + gr // 2
        gfxdraw.filled_circle(pantalla, ex, ey, gr // 2, TINTA)
        gfxdraw.aacircle(pantalla, ex, ey, gr // 2, TINTA)


# ── Dibujo: boca ─────────────────────────────────────────────
def _puntos_boca(cx: float, cy: float, bw: float, abre: float, curva: float,
                 sesgo: float, grosor: float, tilt: float):
    n, sup, inf = 28, [], []
    amp = BOCA_AMP * e
    for i in range(n):
        u  = -1.0 + 2.0 * i / (n - 1)
        x  = cx + u * bw / 2
        yc = cy + curva * amp * (1 - u * u) + sesgo * u * amp * 0.35
        h  = abre * math.sqrt(max(0.0, 1 - u * u))
        sup.append(_rotar(x, yc - h / 2 - grosor / 2, cx, cy, tilt))
        inf.append(_rotar(x, yc + h / 2 + grosor / 2, cx, cy, tilt))
    return [(int(a), int(b)) for a, b in sup + inf[::-1]]


def _dibujar_boca(cx: float, cy: float, p: Pose, abre: float) -> None:
    bw    = 252 * e * p.boca_ancho
    g     = BOCA_GR * e
    borde = max(3, int(6 * e))

    fuera = _puntos_boca(cx, cy, bw, abre, p.boca_curva, p.boca_sesgo,
                         g + borde * 2, p.tilt)
    gfxdraw.filled_polygon(pantalla, fuera, TINTA)
    gfxdraw.aapolygon(pantalla, fuera, TINTA)

    dentro = _puntos_boca(cx, cy, bw - borde * 2.4, max(0.0, abre - borde),
                          p.boca_curva, p.boca_sesgo, g, p.tilt)
    gfxdraw.filled_polygon(pantalla, dentro, BOCA)
    gfxdraw.aapolygon(pantalla, dentro, BOCA)

    if abre > 34 * e:                          # lengua: solo con la boca abierta
        lw = max(3, int(bw * 0.40))
        lh = max(3, int(abre * 0.32))
        lx, ly = _rotar(cx, cy + p.boca_curva * BOCA_AMP * e * 0.55 + abre * 0.30,
                        cx, cy, p.tilt)
        gfxdraw.filled_ellipse(pantalla, int(lx), int(ly), lw, lh, LENGUA)
        gfxdraw.aaellipse(pantalla, int(lx), int(ly), lw, lh, LENGUA)


# ── Dibujo: símbolo flotante ─────────────────────────────────
_simbolo_actual: str | None = SIMBOLOS.get(expresion)
_simbolo_alfa:   float      = 1.0 if _simbolo_actual else 0.0


def _dibujar_simbolo(cx: float, cy: float, nombre: str, alfa: float,
                     ahora: float) -> None:
    a = int(255 * max(0.0, min(1.0, alfa)))
    if a < 8:
        return
    sx = cx + 400 * e
    sy = cy - 300 * e + math.sin(ahora * 2.2) * 16 * e

    if nombre in ("?", "!", "Z"):
        txt = FUENTE.render(nombre, True, SIMBOLO)
        txt.set_alpha(a)
        txt = pygame.transform.rotozoom(txt, math.sin(ahora * 1.6) * 10, 1.0)
        pantalla.blit(txt, txt.get_rect(center=(int(sx), int(sy))))

    elif nombre == "gota":
        for k, (dx, dy, esc) in enumerate(((0, 0, 1.0), (-96, 70, 0.6))):
            cae = ((ahora * 0.6 + k * 0.5) % 1.0) * 130 * e
            gx, gy = int(sx + dx * e), int(sy + dy * e + cae)
            rr = max(3, int(34 * e * esc))
            gfxdraw.filled_polygon(pantalla, [(gx - rr, gy - int(rr * 0.35)),
                                              (gx + rr, gy - int(rr * 0.35)),
                                              (gx, gy - int(rr * 2.6))], (*GOTA, a))
            gfxdraw.aapolygon(pantalla, [(gx - rr, gy - int(rr * 0.35)),
                                         (gx + rr, gy - int(rr * 0.35)),
                                         (gx, gy - int(rr * 2.6))], (*GOTA, a))
            gfxdraw.filled_circle(pantalla, gx, gy, rr, (*GOTA, a))
            gfxdraw.aacircle(pantalla, gx, gy, rr, (*GOTA, a))

    elif nombre == "estrellas":
        for k, (dx, dy, esc) in enumerate(((0, 0, 1.0), (-136, 104, 0.62),
                                           (104, 122, 0.5))):
            pul = 0.82 + 0.18 * math.sin(ahora * 4.0 + k * 1.9)
            r   = 62 * e * esc * pul
            gx, gy = sx + dx * e, sy + dy * e
            pts = []
            for i in range(10):
                rr = r if i % 2 == 0 else r * 0.42
                th = -math.pi / 2 + i * math.pi / 5
                pts.append((int(gx + math.cos(th) * rr), int(gy + math.sin(th) * rr)))
            gfxdraw.filled_polygon(pantalla, pts, (*SIMBOLO, a))
            gfxdraw.aapolygon(pantalla, pts, (*SIMBOLO, a))


# ── Cuadro completo ──────────────────────────────────────────
def _dibujar(ahora: float, p: Pose, cierre: float, mx: float, my: float) -> None:
    # La pose que se dibuja NO es la pose de la tabla: es la pose más lo que le
    # suman la voz y el micro-gesto de este cuadro. Se arma una copia y el resto
    # del dibujo no se entera de nada.
    voz = _voz_lenta if (time.time() - _t_ultimo_volumen) < 0.3 else 0.0
    d_ceja, d_tilt, d_parp = _micro_gesto(ahora, p.gestos)
    p = replace(
        p,
        ceja_alt=p.ceja_alt + d_ceja + voz * p.ceja_vol,
        tilt=p.tilt + d_tilt,
        parp_sup=min(1.0, p.parp_sup + d_parp),
        ojo_esc=p.ojo_esc * (1.0 + voz * p.ojo_vol * 0.14),
    )

    # Respiración + squash & stretch: la cabeza no solo sube y baja, se estira
    # al subir y se aplasta al llegar abajo. Sin esto el rebote se ve rígido.
    bob     = math.sin(ahora * p.bob_vel) * (p.bob_amp + voz * p.bob_vol) * e
    squash  = 1.0 - 0.05 * math.sin(ahora * p.bob_vel * 2.0)
    respira = 1.0 + 0.014 * math.sin(ahora * 0.9)

    cx = W / 2
    cy = H / 2 + bob

    if len(_CACHE_SILUETA) > 96:
        _CACHE_SILUETA.clear()
    if len(_CACHE_HALO) > 48:
        _CACHE_HALO.clear()

    pantalla.blit(FONDO, (0, 0))

    rx    = max(8, int(R_OJO * e * p.ojo_esc * p.ojo_ancho * respira))
    ry    = max(8, int(R_OJO * e * p.ojo_esc * squash * respira))
    sep   = SEP_OJOS * e * respira
    ojo_y = cy + OJO_DY * e * squash

    for sx in (-1, 1):
        ox, oy = _rotar(cx + sx * sep, ojo_y, cx, cy, p.tilt)
        halo = _halo(int(rx * 2.3), IRIS)
        pantalla.blit(halo, halo.get_rect(center=(int(ox), int(oy))),
                      special_flags=pygame.BLEND_RGB_ADD)
        c = cierre if sx < 0 else min(1.0, cierre + p.guino)
        _dibujar_ojo((int(ox), int(oy)), p, rx, ry, mx, my, c)

    for sx in (-1, 1):
        by = ojo_y - ry - (14 + p.ceja_alt) * e - (p.ceja_asim * e if sx < 0 else 0)
        _dibujar_ceja(sx, cx + sx * sep, by, p, cx, cy)

    if p.rubor > 0.02:
        alfa = int(185 * min(1.0, p.rubor))
        rw, rh = int(72 * e), int(42 * e)
        for sx in (-1, 1):
            rxc, ryc = _rotar(cx + sx * (sep + rx * 0.72), ojo_y + ry * 0.92 + 34 * e,
                              cx, cy, p.tilt)
            blush = pygame.Surface((rw * 2 + 2, rh * 2 + 2), pygame.SRCALPHA)
            gfxdraw.filled_ellipse(blush, rw, rh, rw, rh, RUBOR)
            gfxdraw.aaellipse(blush, rw, rh, rw, rh, RUBOR)
            blush.fill((255, 255, 255, alfa), special_flags=pygame.BLEND_RGBA_MULT)
            pantalla.blit(blush, blush.get_rect(center=(int(rxc), int(ryc))))

    abre = p.boca_abre * e
    if p.boca_vol > 0.05 and (time.time() - _t_ultimo_volumen) < 0.3:
        abre += _volumen_suave * 72 * e * p.boca_vol
    bx, by = _rotar(cx, cy + BOCA_DY * e * squash, cx, cy, p.tilt)
    _dibujar_boca(bx, by, p, max(0.0, abre))

    if _simbolo_actual:
        _dibujar_simbolo(cx, cy, _simbolo_actual, _simbolo_alfa, ahora)


# ── Loop principal ───────────────────────────────────────────
def _bucle() -> None:
    global t, expresion, _volumen, _volumen_suave, _voz_lenta, _t_ultimo_volumen
    global _simbolo_actual, _simbolo_alfa

    primer_cuadro = True
    while True:
        try:
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline().strip()
                if line.startswith("expresion:"):
                    expresion = line.split(":", 1)[1]
                elif line.startswith("volumen:"):
                    try:
                        _volumen = float(line.split(":", 1)[1])
                        _t_ultimo_volumen = time.time()
                    except ValueError:
                        pass
        except Exception:
            pass

        # Dos envolventes distintas a propósito: la boca tiene que seguir la
        # sílaba (rápida) y las cejas la frase (lenta). Con una sola, o la boca
        # va tarde o las cejas tiemblan en cada golpe de voz.
        _volumen_suave = _volumen_suave * 0.50 + _volumen * 0.50
        _voz_lenta     = _voz_lenta     * 0.85 + _volumen * 0.15

        _avanzar_resortes(POSES.get(expresion, POSES["idle"]))

        # El símbolo no se interpola: se desvanece, cambia y vuelve a aparecer.
        quiere = SIMBOLOS.get(expresion)
        if quiere == _simbolo_actual:
            _simbolo_alfa = min(1.0, _simbolo_alfa + 0.10) if quiere else 0.0
        else:
            _simbolo_alfa -= 0.16
            if _simbolo_alfa <= 0.0:
                _simbolo_alfa   = 0.0
                _simbolo_actual = quiere

        cierre = _parpadeo(t, _actual.parpadea)
        mx, my = _mirar(t, _actual.vaga)
        _dibujar(t, _actual, cierre, _actual.mirada_x + mx, _actual.mirada_y + my)

        pygame.display.flip()
        pygame.event.pump()

        if primer_cuadro:
            # Avisar que ya hay algo en pantalla. Quien nos lanzó espera esta
            # línea para cerrar su propia ventana sin dejar ver el escritorio.
            primer_cuadro = False
            try:
                sys.stdout.write("LISTO\n")
                sys.stdout.flush()
            except Exception:
                pass

        clock.tick(FPS)
        t += DT


if __name__ == "__main__":
    _bucle()
