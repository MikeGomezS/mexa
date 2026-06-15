#!/usr/bin/env python3
"""
MEXA — Proceso de animación de cara de bienvenida.
Se lanza como subproceso desde modulo_proyector.pantalla_bienvenida().
Uso: python3 _cara_animada.py W H X Y [expresion]

Recibe comandos por stdin para cambiar expresión en tiempo real:
  expresion:hablando\n
  expresion:escuchando\n
  expresion:pensando\n
  expresion:feliz\n
  expresion:idle\n
"""
import math
import os
import select
import signal
import sys
import time

import pygame

W          = int(sys.argv[1]) if len(sys.argv) > 1 else 1920
H          = int(sys.argv[2]) if len(sys.argv) > 2 else 1080
X          = int(sys.argv[3]) if len(sys.argv) > 3 else 0
Y          = int(sys.argv[4]) if len(sys.argv) > 4 else 0
expresion  = sys.argv[5]       if len(sys.argv) > 5 else "idle"

if not os.environ.get("DISPLAY"):
    os.environ["DISPLAY"] = ":0"
os.environ["SDL_VIDEO_WINDOW_POS"] = f"{X},{Y}"

pygame.init()
pantalla = pygame.display.set_mode((W, H), pygame.NOFRAME)
e     = H / 1080.0
clock = pygame.time.Clock()
t     = 0.0

_volumen:           float = 0.0   # último valor recibido
_volumen_suavizado: float = 0.0   # con suavizado exponencial para animación fluida
_t_ultimo_volumen:  float = 0.0   # timestamp del último update


def _salir(signum, frame):
    pygame.quit()
    sys.exit(0)


signal.signal(signal.SIGTERM, _salir)
signal.signal(signal.SIGINT,  _salir)


def _dibujar(t: float, expr: str) -> None:  # noqa: C901
    cx = W // 2

    # ── Parámetros por expresión ────────────────────────────
    if expr == "hablando":
        cy_offset    = int(math.sin(t * 2.0) * 8 * e)
        blink_period = 5.0;  blink_dur = 0.12
        r_ext_mult   = 1.0
        ceja_dy      = 0
        boca_speed   = 5.0;  boca_max = 38
        pupil_dx = pupil_dy = 0
        modo_ojos = "normal";  modo_boca = "normal"

    elif expr == "escuchando":
        cy_offset    = int(math.sin(t * 0.8) * 6 * e)
        blink_period = 6.0;  blink_dur = 0.12
        r_ext_mult   = 1.1                          # ojos un poco más grandes
        ceja_dy      = int(-12 * e)                 # cejas más arriba
        boca_speed   = 0.5;  boca_max = 8           # boca casi quieta
        pupil_dx = pupil_dy = 0
        modo_ojos = "normal";  modo_boca = "normal"

    elif expr == "pensando":
        cy_offset    = int(math.sin(t * 0.9) * 7 * e)
        blink_period = 7.0;  blink_dur = 0.12
        r_ext_mult   = 1.0
        ceja_dy      = 0
        boca_speed   = 0.4;  boca_max = 12
        pupil_dx     = int(18 * e)                  # pupilas arriba-derecha
        pupil_dy     = int(-15 * e)
        modo_ojos = "pensando";  modo_boca = "normal"

    elif expr == "feliz":
        cy_offset    = int(math.sin(t * 2.5) * 15 * e)   # rebote vivo
        blink_period = 99;   blink_dur = 0                 # no parpadea
        r_ext_mult   = 1.0
        ceja_dy      = int(-8 * e)                         # cejas arriba
        boca_speed   = 0;    boca_max = 0
        pupil_dx = pupil_dy = 0
        modo_ojos = "feliz";  modo_boca = "grande"

    else:  # idle (default)
        cy_offset    = int(math.sin(t * 1.2) * 10 * e)
        blink_period = 4.5;  blink_dur = 0.15
        r_ext_mult   = 1.0
        ceja_dy      = 0
        boca_speed   = 1.8;  boca_max = 26
        pupil_dx = pupil_dy = 0
        modo_ojos = "normal";  modo_boca = "normal"

    cy = H // 2 + cy_offset
    pantalla.fill((0, 160, 70))

    r_ext    = int(80 * e * r_ext_mult)
    r_pupila = int(32 * e)
    r_brillo = int(11 * e)
    grosor   = max(4, int(6 * e))
    sep_x    = int(170 * e)
    ojo_y    = cy - int(70 * e)

    parpadeando = (t % blink_period) < blink_dur

    # ── Ojos ────────────────────────────────────────────────
    for sx in (-1, 1):
        xo = cx + sx * sep_x

        if modo_ojos == "feliz":
            # Ojos felices: elipse aplastada (squinting de alegría)
            ojo_w = r_ext * 2
            ojo_h = int(r_ext * 0.65)
            rect_f = pygame.Rect(xo - r_ext, ojo_y - ojo_h // 2, ojo_w, ojo_h)
            pygame.draw.ellipse(pantalla, (255, 255, 255), rect_f)
            pygame.draw.ellipse(pantalla, (25, 25, 25), rect_f, grosor)

        elif parpadeando:
            pygame.draw.ellipse(
                pantalla, (25, 25, 25),
                pygame.Rect(xo - r_ext, ojo_y - int(10 * e), r_ext * 2, int(20 * e)),
            )
        else:
            pygame.draw.circle(pantalla, (255, 255, 255), (xo, ojo_y), r_ext)
            pygame.draw.circle(pantalla, (25, 25, 25), (xo, ojo_y), r_ext, grosor)

            px = xo + pupil_dx
            py = ojo_y + pupil_dy
            pygame.draw.circle(pantalla, (25, 25, 25), (px, py), r_pupila)
            pygame.draw.circle(pantalla, (255, 255, 255),
                               (px + int(8 * e), py - int(8 * e)), r_brillo)

        # ── Cejas ─────────────────────────────────────────
        ceja_y = ojo_y - r_ext - int(18 * e) + ceja_dy
        if modo_ojos == "pensando" and sx == -1:
            ceja_y -= int(20 * e)       # ceja izquierda (vista) levantada
        cw, ch = int(68 * e), int(16 * e)
        pygame.draw.ellipse(
            pantalla, (25, 25, 25),
            pygame.Rect(xo - cw // 2, ceja_y - ch // 2, cw, ch),
        )

    # ── Mejillas (solo "feliz") ──────────────────────────────
    if modo_ojos == "feliz":
        for sx in (-1, 1):
            mx = cx + sx * int(265 * e)
            my = ojo_y + int(85 * e)
            blush = pygame.Surface((int(90 * e), int(55 * e)), pygame.SRCALPHA)
            pygame.draw.ellipse(blush, (255, 130, 130, 90), blush.get_rect())
            pantalla.blit(blush, (mx - int(45 * e), my - int(27 * e)))

    # ── Boca ────────────────────────────────────────────────
    boca_y = cy + int(110 * e)

    if modo_boca == "grande":
        bw = int(160 * e)
        bh = int(48 * e)
        pygame.draw.arc(
            pantalla, (200, 60, 80),
            pygame.Rect(cx - bw // 2, boca_y - bh // 2, bw, bh),
            math.pi, 2 * math.pi,
            max(5, int(8 * e)),
        )
    else:
        bw = int(110 * e)
        # En "hablando" con datos de volumen frescos: boca sincronizada con el audio
        if expr == "hablando" and (time.time() - _t_ultimo_volumen) < 0.3:
            ap = int(_volumen_suavizado * boca_max * e)
        else:
            ap = int(abs(math.sin(t * boca_speed)) * boca_max * e) if boca_speed else 0
        if ap < int(4 * e):
            pygame.draw.arc(
                pantalla, (200, 60, 80),
                pygame.Rect(cx - bw // 2, boca_y - int(14 * e), bw, int(28 * e)),
                math.pi, 2 * math.pi,
                max(4, int(5 * e)),
            )
        else:
            rect_b = pygame.Rect(cx - bw // 2, boca_y - ap // 2, bw, ap)
            pygame.draw.ellipse(pantalla, (200, 60, 80), rect_b)
            pygame.draw.ellipse(pantalla, (25, 25, 25), rect_b, max(3, int(4 * e)))


# ── Loop principal ───────────────────────────────────────────
while True:
    # Leer comandos desde stdin (no bloqueante)
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

    # Suavizado exponencial del volumen (α=0.5 → respuesta ~66ms a 30 FPS)
    _volumen_suavizado = _volumen_suavizado * 0.5 + _volumen * 0.5

    _dibujar(t, expresion)
    pygame.display.flip()
    pygame.event.pump()
    clock.tick(30)
    t += 1.0 / 30.0
