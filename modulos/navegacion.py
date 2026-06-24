# ============================================================
#  MEXA — Navegación: acercarse al visitante y volver
#
#  Lazo cerrado cámara+motores que CENTRA y ACERCA a MEXA al
#  visitante (drive-and-sense en dos fases), registrando el
#  camino para luego DESHACERLO con retroceder() (re-exportado
#  desde registro_camino, su pareja conceptual).
# ============================================================

import time

from .modulo_motores import detener, mover_por_tiempo, mover_adelante
from .modulo_camara  import localizar_cara
from .registro_camino import RegistroCamino, retroceder  # re-export: retroceder

# ── Acercamiento con cámara (drive-and-sense en dos fases) ────
# MEXA centra al visitante Y se le acerca usando el TAMAÑO de la cara como proxy
# de distancia (cara grande = cerca). El avance es CONTINUO: los motores NO se
# detienen entre lecturas; MEXA sensa EN MOVIMIENTO y sólo frena para corregir
# rumbo (giro) o al terminar. Esto da una caminata fluida, no entrecortada.
#
# HALLAZGO DE HARDWARE (validado en tests/calibrar_acercamiento.py): MEXA es BAJO
# y la cámara va inclinada, así que al acercarse (~1m) la cara del visitante se
# RECORTA por arriba del cuadro y YuNet deja de verla. Por eso la cara casi nunca
# crece hasta un objetivo grande: se PIERDE antes. Esa pérdida estando CERCA y
# CENTRADO ES la señal de "ya casi llego" y dispara el EMPUJE CIEGO final, que
# cierra el último tramo. Si la cara se pierde LEJOS o descentrada, la persona se
# fue: MEXA no empuja y aborta.
#
# Calibrado en hardware (ruedas chicas): MEXA avanza ~2.5 cm/s (motores a full,
# sin PWM). Estos valores son punto de partida; HAY QUE CALIBRARLOS en el robot
# real (dependen de la lente, la altura de la cámara y la velocidad de los motores).
ACERCAMIENTO_TIMEOUT_S  = 30.0  # tope duro de seguridad para TODA la maniobra
TAMANO_CARA_OBJETIVO    = 0.40  # techo de seguridad: si la cara llegara a verse así
                                # de grande, frena. Casi nunca se alcanza (la cara se
                                # recorta antes ~25%); el freno real es la pérdida por
                                # recorte + el empuje ciego de la fase 2.
PULSO_GIRO_S            = 0.80  # barrido por paso: más alto = gira menos entrecortado, pero
                                # si se pasa del centro oscila (zona 40/60% lo auto-corrige).
                                # Subido 0.25->0.80 para que el giro se sienta más fluido.
MAX_MISSES_ACERCAMIENTO = 6     # frames sin cara seguidos -> fin de la fase visual
SETTLE_ACERCAMIENTO_S   = 0.35  # respiro anti-blur SÓLO tras un giro: deja asentar
                                # robot+cámara antes de re-sensar. SIN esto, el frame
                                # post-giro sale borroso, YuNet cae bajo _SCORE_MIN y
                                # MEXA pierde la cara (validado en hardware 2026-06-23).
# Empuje ciego final (fase 2): tras perder la cara por cercanía, avanza a ciegas
# para cerrar el último tramo hasta el visitante.
UMBRAL_CARA_CERCA       = 0.20  # último tamaño mínimo para confiar en que el recorte
                                # es por cercanía (no porque la persona se fue)
AVANCE_CIEGO_FINAL_S    = 4.0   # segundos de empuje ciego. CALIBRAR: parate frente a
                                # MEXA y SUBÍ este valor hasta que frene a la distancia
                                # que quieras (~2.5 cm/s -> 4s ≈ 10cm). SEGURIDAD: no lo
                                # subas tanto que MEXA choque con el visitante.


def acercarse_a_usuario():
    """Drive-and-sense en dos fases: MEXA centra al visitante y se le acerca.

    FASE 1 (visual, avance CONTINUO). Usa el tamaño de la cara como proxy de
    distancia. En cada lectura:
      - centrado    -> avanza CONTINUO (no frena entre lecturas: sensa en marcha).
      - descentrado -> frena, da un giro corto hacia ese lado, asienta (anti-blur)
                       y re-sensa. Centrar tiene prioridad sobre avanzar.
      - sin cara    -> sigue su marcha; si la pierde MAX_MISSES seguidas, cierra
                       la fase visual y evalúa la fase 2.
      - cara enorme -> (tamano >= TAMANO_CARA_OBJETIVO) techo de seguridad: frena.

    FASE 2 (empuje ciego final). Al cerrar la fase visual por pérdida de cara:
      - si la perdió CERCA (último tamaño >= UMBRAL_CARA_CERCA) y CENTRADA, asume
        que fue por RECORTE (MEXA es bajo, la cara se sale por arriba) y empuja a
        ciegas AVANCE_CIEGO_FINAL_S para cerrar el último tramo.
      - si la perdió LEJOS o descentrada, la persona se fue: no empuja, aborta.

    Cortes de seguridad: ACERCAMIENTO_TIMEOUT_S acota TODA la maniobra. El avance
    continuo deja los motores en marcha; sólo se frena para girar, al alcanzar el
    techo de tamaño, o al terminar.

    REGISTRA el recorrido: cada comando de motor queda anotado con su
    timestamp y se devuelve como lista de (comando, timestamp), para que
    MEXA pueda RETROCEDER al punto de partida tras atender al visitante."""
    registro = RegistroCamino()
    registro.iniciar()  # engancha la capa serial: anota cada F/B/R/L/S
    fin = time.time() + ACERCAMIENTO_TIMEOUT_S
    misses = 0
    primera_cara = True
    ult_tamano = 0.0
    ult_posicion = "centro"
    avanzando = False  # ¿los motores están en marcha continua hacia adelante?

    def asegurar_avance():
        nonlocal avanzando
        if not avanzando:
            mover_adelante()
            avanzando = True

    def frenar():
        nonlocal avanzando
        if avanzando:
            detener()
            avanzando = False

    while time.time() < fin:
        lectura = localizar_cara()  # se sensa EN MOVIMIENTO durante el avance
        if lectura is None:
            misses += 1
            if misses >= MAX_MISSES_ACERCAMIENTO:
                frenar()
                cerca = ult_tamano >= UMBRAL_CARA_CERCA
                centrada = ult_posicion == "centro"
                if cerca and centrada:
                    print(f"[NAV] Acercamiento: cara perdida CERCA "
                          f"(últ={ult_tamano:.0%}, centro) -> recorte. "
                          f"Empuje ciego {AVANCE_CIEGO_FINAL_S}s.")
                    mover_por_tiempo("adelante", AVANCE_CIEGO_FINAL_S)
                else:
                    print(f"[NAV] Acercamiento: cara perdida LEJOS/descentrada "
                          f"(últ={ult_tamano:.0%}, {ult_posicion}) -> no empujo.")
                break
            continue
        misses = 0
        posicion, tamano = lectura
        ult_tamano, ult_posicion = tamano, posicion
        # Tamaño al que MEXA ENGANCHA por primera vez al visitante: dato clave de
        # calibración (¿a qué distancia detecta cuando dispara el PIR?).
        if primera_cara:
            print(f"[NAV] Acercamiento: primera cara en pos={posicion}, "
                  f"tamaño={tamano:.0%}.")
            primera_cara = False
        if tamano >= TAMANO_CARA_OBJETIVO:
            frenar()
            print(f"[NAV] Acercamiento: techo de seguridad (cara={tamano:.0%}), freno.")
            break
        if posicion == "centro":
            asegurar_avance()  # avance CONTINUO: no se frena entre lecturas
        else:
            # Corrección de rumbo: frenar, girar un pulso y asentar (anti-blur)
            # antes de re-sensar, que un frame post-giro sale borroso.
            frenar()
            mover_por_tiempo(posicion, PULSO_GIRO_S)
            time.sleep(SETTLE_ACERCAMIENTO_S)
    else:
        frenar()
        print("[NAV] Acercamiento: TIMEOUT, freno.")
    detener()
    registro.finalizar()  # deja de escuchar y cierra el último tramo
    return registro.eventos
