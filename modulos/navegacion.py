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

from .modulo_motores import (detener, mover_por_tiempo, mover_adelante,
                             iniciar_movimiento,
                             PULSO_GIRO_S)  # re-export: es del tren de tracción
from .modulo_camara  import localizar_cara, reiniciar_objetivo
from .conexion_arduino import (distancia_frontal_cm, freno_por_persona,
                               reiniciar_frente, pared_al_girar, reiniciar_pared)
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

# ── Acercamiento SIN cámara (el ultrasonido como único sentido) ─
# Cuando la cámara no entrega NI UNA cara en toda la fase visual, MEXA se
# quedaba clavada: `asegurar_avance()` vive dentro de la rama de una lectura
# REAL, así que sin cara no salía un solo 'F'. Tenía cuatro ultrasónicos
# ociosos y ningún camino de movimiento que no pasara por los ojos.
#
# ESTE SENTIDO VE MENOS, Y HAY QUE DECIRLO. No reemplaza a la cámara:
#   · ALCANCE ~2m — ECHO_TIMEOUT_FRENTE_US = 12000us (mexa.ino:196). Más
#     lejos el firmware manda 999.0 (telemetria.SIN_ECO_CM), que no es un
#     error: es "no hay nadie dentro del alcance".
#   · NO DA RUMBO — dice cuánto falta, no hacia dónde. MEXA avanza DERECHO;
#     si el visitante está de costado, no lo va a encontrar. Girar a ciegas
#     buscándolo sería pasear un robot por una sala llena de gente.
#   · SÓLO MIDE EN MARCHA — `vigilarFrente()` corre únicamente durante una
#     'F'. Por eso no se puede mirar antes de arrancar: para saber si hay
#     alguien HAY que empezar a caminar.
ALCANCE_FRENTE_CM       = 200.0 # techo físico del frontal. Una lectura de acá para
                                # arriba (999.0 incluido) es "nadie a la vista", no
                                # una distancia. NO lo subas: el sensor no ve más
                                # lejos por cambiarle un número a la Pi.
PACIENCIA_FRENTE_S      = 1.5   # cuánto se aguanta sin una lectura ÚTIL antes de
                                # rendirse. Cubre dos casos distintos con el mismo
                                # número: el sensor que nunca contesta (no está) y
                                # el que contesta 999 sostenido (no hay nadie). El
                                # firmware reporta cada 200ms, así que 1.5s son ~7
                                # ventanas: un eco perdido suelto no aborta nada,
                                # que un cuerpo es blando y oblicuo y se pierde de
                                # a ratos.
CIEGO_TIMEOUT_S         = 20.0  # tope del acercamiento sin cámara. A ~2.5cm/s son
                                # ~50cm: alcanza para cerrar desde ~120cm, NO desde
                                # los 200cm del alcance del sensor. Es a propósito:
                                # un visitante no espera 52s parado, y MEXA acercada
                                # a 120cm ya puede hablarle.


def _acercamiento_a_ciegas(fin):
    """Se acerca al visitante con el ULTRASONIDO como único sentido, cuando la
    cámara no entregó ni una cara en toda la fase visual.

    NO ES EL EMPUJE FINAL, aunque se le parezca. `_empuje_final()` cierra el
    último tramo DESPUÉS de haber visto la cara: tiene testigo de que hay
    alguien ahí, y por eso puede permitirse empujar a ciegas por tiempo si el
    sensor no contesta. Acá no hay testigo de nada. Si el frente no habla, MEXA
    NO empuja: sin cámara y sin ultrasonido no queda un solo sentido que diga
    que hay una persona, y avanzar por las dudas contra un visitante no es un
    fallback, es una apuesta.

    `fin` es el deadline de TODA la maniobra (time.time()): manda sobre el
    presupuesto propio, nunca al revés.

    Devuelve el motivo del freno, para que el log diga qué decidió y con qué:
      'medido'     llegó a DISTANCIA_OBJETIVO_CM (el caso bueno)
      'reflejo'    el firmware frenó solo: alguien se metió delante
      'sin_sensor' el frontal no contestó nunca -> se rinde sin empujar
      'nadie'      contestó 999 sostenido: no hay nadie dentro de los 2m
      'tope'       se acabó el tiempo con el visitante todavía lejos
    """
    reiniciar_frente()          # el firmware mide de cero en cada avance
    inicio = time.monotonic()
    presupuesto = min(CIEGO_TIMEOUT_S, max(0.0, fin - time.time()))
    mover_adelante()            # hay que caminar para que el frontal mida
    hubo_lectura = False        # ¿el sensor contestó ALGUNA vez?
    sello_util = inicio         # cuándo se vio por última vez algo dentro del alcance
    try:
        while True:
            ahora = time.monotonic()

            frenado = freno_por_persona()
            if frenado is not None:
                print(f"[NAV] A ciegas: el Arduino frenó SOLO a {frenado:.0f}cm "
                      f"(reflejo de seguridad).")
                return "reflejo"

            distancia = distancia_frontal_cm()
            if distancia is not None:
                hubo_lectura = True
                if distancia < ALCANCE_FRENTE_CM:
                    sello_util = ahora
                    if distancia <= DISTANCIA_OBJETIVO_CM:
                        print(f"[NAV] A ciegas: llegué a {distancia:.0f}cm sin ver "
                              f"una cara (objetivo {DISTANCIA_OBJETIVO_CM:.0f}cm).")
                        return "medido"

            if not hubo_lectura and ahora - inicio >= PACIENCIA_FRENTE_S:
                print(f"[NAV] A ciegas: el frente no contestó en "
                      f"{PACIENCIA_FRENTE_S:.1f}s. Sin cámara Y sin ultrasonido "
                      f"no empujo: no sé si hay alguien.")
                return "sin_sensor"

            if hubo_lectura and ahora - sello_util >= PACIENCIA_FRENTE_S:
                print(f"[NAV] A ciegas: nada dentro de {ALCANCE_FRENTE_CM:.0f}cm "
                      f"durante {PACIENCIA_FRENTE_S:.1f}s. No hay nadie al frente.")
                return "nadie"

            if ahora - inicio >= presupuesto:
                ultima = f"{distancia:.0f}cm" if distancia is not None else "sin lectura"
                print(f"[NAV] A ciegas: TOPE de {presupuesto:.1f}s ({ultima}). "
                      f"Me quedo acá y le hablo desde donde estoy.")
                return "tope"

            time.sleep(POLL_FRENTE_S)
    finally:
        detener()   # el 'S' propio: el registro del camino tiene que decir la verdad


def _girar_vigilado(posicion):
    """Gira un pulso hacia `posicion`, pero VIGILANDO que el firmware no haya
    cortado el giro por pared lateral.

    POR QUÉ NO ALCANZA UN sleep(PULSO_GIRO_S). El firmware frena SOLO: durante
    un 'R'/'L' mide el lateral de ese lado y si hay pared a menos de
    UMBRAL_PARED_CM cancela el giro (arduino/mexa/mexa.ino:219-232, avisa con
    "WALL:I/D"). Un sleep ciego no se entera: sigue durmiendo el pulso entero y
    recién ahí manda su 'S', así que EL REGISTRO DEL CAMINO ANOTA UN GIRO QUE
    NO PASÓ. Al volver, MEXA gira de más — y el error angular no se suma al
    final, ROTA todos los tramos siguientes.

    Es el mismo trato que ya se le daba al freno frontal durante el avance
    (ver el lazo de acercarse_a_usuario y POLL_FRENTE_S): consultar seguido y
    mandar el 'S' propio, para que el registro cuente lo que el robot hizo.

    Devuelve el lado ('I'/'D') si hubo corte por pared, o None si el pulso se
    completó entero.
    """
    reiniciar_pared()      # espejo del reiniciarFrente() del avance
    inicio = time.monotonic()
    iniciar_movimiento(posicion)
    try:
        while time.monotonic() - inicio < PULSO_GIRO_S:
            lado = pared_al_girar()
            if lado is not None:
                print(f"[NAV] Giro CANCELADO por pared ({lado}) a los "
                      f"{time.monotonic() - inicio:.2f}s de {PULSO_GIRO_S:.2f}s.")
                return lado
            time.sleep(POLL_FRENTE_S)
    finally:
        detener()          # el 'S' que hace que el registro diga la verdad
    return None


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
                elif primera_cara:
                    # NUNCA hubo una cara: no es que se perdió, es que la
                    # cámara no vio nada en toda la fase. Distinguirlo importa,
                    # porque son dos mundos: "se fue" no se arregla caminando,
                    # "no veo" sí — con el otro sentido. El PIR ya dijo que hay
                    # alguien (main.ciclo_principal sólo llama acá después de
                    # _esperar_persona), así que MEXA no sale a inventar gente.
                    print("[NAV] Acercamiento: la cámara no vio NI UNA cara. "
                          "Paso al ultrasonido.")
                    _acercamiento_a_ciegas(fin)
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
            _girar_vigilado(posicion)
            time.sleep(SETTLE_ACERCAMIENTO_S)
    else:
        frenar()
        print("[NAV] Acercamiento: TIMEOUT, freno.")
    detener()
    registro.finalizar()  # deja de escuchar y cierra el último tramo
    return registro.eventos
