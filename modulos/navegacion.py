# ============================================================
#  MEXA — Navegación: acercarse al visitante y volver
#
#  Lazo cerrado cámara+motores que CENTRA y ACERCA a MEXA al
#  visitante (drive-and-sense en dos fases), registrando el
#  camino para luego DESHACERLO con retroceder() (re-exportado
#  desde registro_camino, su pareja conceptual).
#
#  DOS SENTIDOS, DOS TRABAJOS. La CÁMARA dice A QUIÉN mirar y
#  HACIA DÓNDE girar: es el sentido del RUMBO. Los ULTRASÓNICOS
#  frontales dicen CUÁNTO FALTA: son el sentido de la DISTANCIA.
#  La cámara sola no alcanza porque MEXA es bajo y la cara se le
#  sale del cuadro justo cuando más importa saber cuánto falta.
# ============================================================

import time

from .modulo_motores import detener, mover_por_tiempo, mover_adelante
from .modulo_camara  import localizar_cara, reiniciar_objetivo
from .conexion_arduino import (distancia_frontal_cm, freno_por_persona,
                               reiniciar_frente)
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
# CENTRADO ES la señal de "ya casi llego" y dispara el EMPUJE FINAL, que cierra
# el último tramo. Si la cara se pierde LEJOS o descentrada, la persona se fue:
# MEXA no empuja y aborta.
#
# Calibrado en hardware (ruedas chicas): MEXA avanza ~2.5 cm/s (motores a full,
# sin PWM). Estos valores son punto de partida; HAY QUE CALIBRARLOS en el robot
# real (dependen de la lente, la altura de la cámara y la velocidad de los motores).
ACERCAMIENTO_TIMEOUT_S  = 30.0  # tope duro de seguridad para TODA la maniobra
TAMANO_CARA_OBJETIVO    = 0.40  # techo de seguridad: si la cara llegara a verse así
                                # de grande, frena. Casi nunca se alcanza (la cara se
                                # recorta antes ~25%); el freno real es la pérdida por
                                # recorte + el empuje final de la fase 2.
PULSO_GIRO_S            = 0.80  # barrido por paso: más alto = gira menos entrecortado, pero
                                # si se pasa del centro oscila (zona 40/60% lo auto-corrige).
                                # Subido 0.25->0.80 para que el giro se sienta más fluido.
MAX_MISSES_ACERCAMIENTO = 6     # frames sin cara seguidos -> fin de la fase visual
SETTLE_ACERCAMIENTO_S   = 0.35  # respiro anti-blur SÓLO tras un giro: deja asentar
                                # robot+cámara antes de re-sensar. SIN esto, el frame
                                # post-giro sale borroso, YuNet cae bajo _SCORE_MIN y
                                # MEXA pierde la cara (validado en hardware 2026-06-23).
UMBRAL_CARA_CERCA       = 0.20  # último tamaño mínimo para confiar en que el recorte
                                # es por cercanía (no porque la persona se fue)

# ── Distancia por ultrasonido (frontales del Arduino) ─────────
# DÓNDE quiere pararse MEXA: cerca para conversar, lejos para no invadir.
# Este es el número que la cámara NUNCA pudo darnos, porque a esta distancia
# la cara ya se salió del cuadro.
DISTANCIA_OBJETIVO_CM   = 70.0  # CALIBRADO en hardware (2026-08-21) con una persona
                                # a 65cm medidos desde la cara del sensor: el frente
                                # entregó 69.1cm (sesgo de +4cm). MEXA frena, entonces,
                                # a ~66cm reales — que es lo pedido: "alrededor de 65".
                                # NO afinar este número: contra una persona el sensor
                                # oscila entre 56 y 77cm (un cuerpo no es una pared),
                                # así que un decimal de más es falsa precisión.
                                # El sesgo es POSITIVO (el sensor infla), y eso ACERCA
                                # a MEXA de más, no de menos: si algún día hay que
                                # errar, errar hacia ARRIBA.
                                # SIEMPRE por encima de FRENO_PERSONA_CM (25cm) del
                                # firmware: ese es el piso de seguridad, no la meta.
POLL_FRENTE_S           = 0.05  # cada cuánto la Pi consulta el frente durante el
                                # empuje. Acota el error del registro del camino: si
                                # el Arduino frena SOLO, MEXA manda su 'S' como mucho
                                # 50ms después, así el tramo anotado dura lo real.
EMPUJE_TIMEOUT_S        = 8.0   # tope del empuje MEDIDO (~2.5cm/s -> ≈20cm). Cota
                                # física: aunque el sensor mienta, MEXA no puede
                                # recorrer de más lo suficiente para lastimar.
AVANCE_CIEGO_FINAL_S    = 4.0   # empuje A CIEGAS: sólo se usa si los ultrasónicos
                                # frontales NO contestan (no conectados / fallados).
                                # ~2.5 cm/s -> 4s ≈ 10cm. SEGURIDAD: no lo subas tanto
                                # que MEXA choque con el visitante.


def _empuje_final():
    """Cierra el último tramo hasta el visitante, con los ojos que haya.

    MEDIDO si los ultrasónicos frontales contestan: avanza hasta quedar a
    DISTANCIA_OBJETIVO_CM, que es exactamente lo que la cámara no podía
    decirnos (a esa altura la cara ya está fuera del cuadro).

    A CIEGAS si NO contestan: se cae al empuje por tiempo de siempre. El
    sensor tiene que estar ANDANDO para mejorar a MEXA; si no está, MEXA se
    comporta como antes. Un sensor ausente no puede romper lo que funcionaba.

    Devuelve el motivo del freno, para que el log diga la verdad de qué
    sentido tomó la decisión: 'medido' | 'reflejo' | 'ciego' | 'tope'.
    """
    reiniciar_frente()   # espejo de reiniciarFrente() del firmware
    inicio = time.monotonic()
    mover_adelante()
    hubo_lectura = False
    try:
        while True:
            transcurrido = time.monotonic() - inicio

            # El Arduino frenó SOLO: alguien se metió delante. No lo
            # prevenimos, nos enteramos — y mandamos nuestro 'S' para que el
            # registro del camino coincida con lo que el robot realmente hizo.
            frenado = freno_por_persona()
            if frenado is not None:
                print(f"[NAV] Empuje final: el Arduino frenó SOLO a {frenado:.0f}cm "
                      f"(reflejo de seguridad).")
                return "reflejo"

            distancia = distancia_frontal_cm()
            if distancia is not None:
                hubo_lectura = True
                if distancia <= DISTANCIA_OBJETIVO_CM:
                    print(f"[NAV] Empuje final: llegué a {distancia:.0f}cm "
                          f"(objetivo {DISTANCIA_OBJETIVO_CM:.0f}cm).")
                    return "medido"

            # Sin ultrasónicos: se acabó el tiempo del empuje ciego clásico.
            if not hubo_lectura and transcurrido >= AVANCE_CIEGO_FINAL_S:
                print(f"[NAV] Empuje final: sin lectura frontal, "
                      f"empuje CIEGO de {AVANCE_CIEGO_FINAL_S}s completado.")
                return "ciego"

            if transcurrido >= EMPUJE_TIMEOUT_S:
                print(f"[NAV] Empuje final: TOPE de {EMPUJE_TIMEOUT_S}s "
                      f"(el frente nunca bajó de {DISTANCIA_OBJETIVO_CM:.0f}cm).")
                return "tope"

            time.sleep(POLL_FRENTE_S)
    finally:
        detener()


def acercarse_a_usuario():
    """Drive-and-sense en dos fases: MEXA centra al visitante y se le acerca.

    Elige a UN visitante entre los que haya (el más cercano, de frente y
    centrado — ver modulo_camara.localizar_cara) y se queda con él toda la
    maniobra: cambiar de persona a mitad de camino haría zigzaguear a MEXA.

    FASE 1 (visual, avance CONTINUO). Usa el tamaño de la cara como proxy de
    distancia. En cada lectura:
      - frente cerca -> (ultrasónicos <= DISTANCIA_OBJETIVO_CM) llegó: frena.
      - centrado    -> avanza CONTINUO (no frena entre lecturas: sensa en marcha).
      - descentrado -> frena, da un giro corto hacia ese lado, asienta (anti-blur)
                       y re-sensa. Centrar tiene prioridad sobre avanzar.
      - sin cara    -> sigue su marcha; si la pierde MAX_MISSES seguidas, cierra
                       la fase visual y evalúa la fase 2.
      - cara enorme -> (tamano >= TAMANO_CARA_OBJETIVO) techo de seguridad: frena.

    FASE 2 (empuje final). Al cerrar la fase visual por pérdida de cara:
      - si la perdió CERCA (último tamaño >= UMBRAL_CARA_CERCA) y CENTRADA, asume
        que fue por RECORTE (MEXA es bajo, la cara se sale por arriba) y cierra el
        último tramo con _empuje_final(): medido por ultrasonido, o a ciegas si
        los frontales no contestan.
      - si la perdió LEJOS o descentrada, la persona se fue: no empuja, aborta.

    Cortes de seguridad: ACERCAMIENTO_TIMEOUT_S acota TODA la maniobra. El avance
    continuo deja los motores en marcha; sólo se frena para girar, al alcanzar el
    techo de tamaño, al llegar a la distancia objetivo, o al terminar.

    REGISTRA el recorrido: cada comando de motor queda anotado con su
    timestamp y se devuelve como lista de (comando, timestamp), para que
    MEXA pueda RETROCEDER al punto de partida tras atender al visitante."""
    # Objetivo limpio: cada acercamiento elige a SU visitante desde cero,
    # sin arrastrar el enganche del anterior (ver modulo_camara._Seguidor).
    reiniciar_objetivo()
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
            reiniciar_frente()  # cada 'F' nuevo empieza a medir de cero
            mover_adelante()
            avanzando = True

    def frenar():
        nonlocal avanzando
        if avanzando:
            detener()
            avanzando = False

    while time.time() < fin:
        # El frente manda sobre la cara: si el ultrasonido ya dice que MEXA
        # llegó, no hay tamaño de cara que justifique seguir avanzando.
        if avanzando:
            frenado = freno_por_persona()
            if frenado is not None:
                frenar()
                print(f"[NAV] Acercamiento: el Arduino frenó SOLO a {frenado:.0f}cm.")
                break
            distancia = distancia_frontal_cm()
            if distancia is not None and distancia <= DISTANCIA_OBJETIVO_CM:
                frenar()
                print(f"[NAV] Acercamiento: llegué a {distancia:.0f}cm por "
                      f"ultrasonido (objetivo {DISTANCIA_OBJETIVO_CM:.0f}cm).")
                break

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
                          f"Cierro el último tramo.")
                    _empuje_final()
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
