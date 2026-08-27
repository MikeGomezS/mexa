"""
¿La señal que llega al micrófono de MEXA cae como 1/distancia?

POR QUÉ EXISTE: queremos saber cuánto se gana SUBIENDO el micrófono, que
hoy está a 46cm del suelo mientras la boca del visitante está a ~160cm.
Desmontar y remontar el micrófono a varias alturas para averiguarlo es
caro y propenso a error.

La salida es que ALTURA y DISTANCIA son la MISMA hipotenusa:

    distancia acústica = √(horizontal² + (altura_boca − altura_micrófono)²)

Al micrófono no le importa por cuál de los dos catetos le llegó el sonido.
Así que si en ESTA sala la señal cae como 1/distancia, alcanza con medir
a distintas distancias —que es gratis, caminás— para predecir qué pasa al
cambiar la altura. Y si NO cae como 1/distancia, eso también se aprende:
querría decir que la reverberación de la sala manda, y que subir el
micrófono rinde MENOS de lo que dice la geometría.

EL PROBLEMA QUE RESUELVE EL DISEÑO POR RONDAS: la fuente de sonido es una
persona, y una persona no es reproducible. Medido el 2026-08-27 con el
mismo usuario, la misma sala y el mismo día: la relación entre su "voz
normal" y su "voz baja" pasó de 1.32x en una corrida a 3.72x en la
siguiente. Ese ruido del instrumento es MAYOR que el efecto que buscamos
(~1.7x). Comparar dos corridas separadas NO PUEDE responder la pregunta.

La defensa es no comparar nunca entre corridas. En cada RONDA caminás a
todas las marcas leyendo la MISMA frase; se comparan solo las marcas
DENTRO de esa ronda. Si en esa ronda hablaste fuerte, hablaste fuerte en
todas las marcas, y la razón entre marcas no se entera. La deriva entre
rondas se cancela sola. Además las rondas alternan el sentido del
recorrido (cerca→lejos, lejos→cerca) para que si te vas quedando sin voz
DENTRO de una ronda, eso tampoco se confunda con la distancia.

USO (MEXA en su lugar, micrófono donde va a estar, marcas en el piso):
  python3 tests/calibrar_distancia_voz.py

Ctrl+C corta en cualquier momento.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Las primitivas de medición viven en el otro calibrador y se importan en
# vez de copiarse: `_medir` remuestrea a 16kHz (la señal que ve el VAD, no
# la del micrófono) y `_spread` detecta una medición contaminada. Tener dos
# copias de eso es tener dos calibradores que miden distinto.
import calibrar_umbral_voz as base
import modulos.vad as vad

_MEDICION_S = 4.0

# Leer SIEMPRE lo mismo. El contenido fonético cambia la energía: una
# frase con muchas vocales abiertas mide más que una con muchas eses.
# Si cambia la frase entre marcas, eso se confunde con la distancia.
_FRASE = ("MEXA es un robot guía que cuenta la historia de las "
          "civilizaciones de México, y hoy estamos midiendo su micrófono.")

_ALTURA_MIC_CM  = 46.0    # medido en hardware (2026-08-27)
_ALTURA_BOCA_CM = 160.0   # adulto de pie; se pregunta por si acaso
_DISTANCIAS_CM  = (66.0, 130.0, 200.0)   # 66 = DISTANCIA_OBJETIVO_CM real
_RONDAS         = 3

# El modelo se da por bueno si la razón medida no se aparta más que esto
# de la predicha. No es un número sagrado: es el error que igual deja la
# decisión de subir el micrófono del mismo lado.
_TOLERANCIA = 0.25


def _preguntar_num(texto: str, por_defecto: float) -> float:
    respuesta = input(f"{texto} [{por_defecto:.0f}]: ").strip()
    if not respuesta:
        return por_defecto
    try:
        return float(respuesta.replace(",", "."))
    except ValueError:
        print(f"  No entendí '{respuesta}', uso {por_defecto:.0f}.")
        return por_defecto


def _hipotenusa(horizontal: float, alt_mic: float, alt_boca: float) -> float:
    """La distancia que el sonido recorre de verdad, de la boca al micrófono."""
    return (horizontal ** 2 + (alt_boca - alt_mic) ** 2) ** 0.5


def _mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    medio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[medio]
    return (ordenados[medio - 1] + ordenados[medio]) / 2


def main() -> int:
    print("=" * 66)
    print("  MEXA — ¿la señal cae como 1/distancia en esta sala?")
    print("=" * 66)

    alt_mic  = _preguntar_num("\nAltura del MICRÓFONO sobre el piso, en cm",
                              _ALTURA_MIC_CM)
    alt_boca = _preguntar_num("Altura de tu BOCA de pie, en cm",
                              _ALTURA_BOCA_CM)
    if alt_boca <= alt_mic:
        print("\nLa boca tiene que estar por encima del micrófono. Abortando.")
        return 2

    distancias = list(_DISTANCIAS_CM)
    print("\nMarcá en el piso, medidas desde el FRENTE de MEXA:")
    for d in distancias:
        hip = _hipotenusa(d, alt_mic, alt_boca)
        print(f"  {d:>5.0f} cm de piso  →  {hip:>6.1f} cm de la boca al micrófono")

    # --- ruido de sala: contexto, y control de que la sala esté quieta ---
    while True:
        input("\nSILENCIO. Enter para medir el ruido de sala...")
        sala = base._medir(_MEDICION_S)
        base._informe("ruido de sala", sala)
        spread = base._spread(sala)
        if spread <= base._SPREAD_MAX:
            break
        print(f"  !! MEDICION CONTAMINADA (p80/p20 = {spread:.1f}x). "
              f"Sonó algo que no era la sala.")
        if input("     ¿Repetir? [S/n] ").strip().lower() in ("n", "no"):
            break

    piso = vad.piso_desde_muestras(sala)
    print(f"\n  → piso de ruido {int(piso)} RMS")

    print(f"\nEn cada ronda vas a caminar a cada marca y leer ESTA frase,")
    print("entera y sin parar, hasta que corte:\n")
    print(f'  "{_FRASE}"\n')
    print("Hablá como le hablarías al robot. NO trates de hablar igual que")
    print("en la ronda anterior: el método ya se encarga de eso.")

    # medidas[ronda][distancia] = p80
    medidas: list[dict[float, int]] = []
    for ronda in range(1, _RONDAS + 1):
        # Alternar el sentido: si te quedás sin voz dentro de la ronda,
        # que no le pegue siempre a la misma marca.
        orden = distancias if ronda % 2 else list(reversed(distancias))
        print(f"\n{'-' * 66}\nRONDA {ronda} de {_RONDAS}  "
              f"({'cerca→lejos' if ronda % 2 else 'lejos→cerca'})")
        fila: dict[float, int] = {}
        for d in orden:
            input(f"  Andá a la marca de {d:.0f} cm y Enter cuando estés listo...")
            muestras = base._medir(_MEDICION_S)
            p80 = base._percentil(sorted(muestras), 0.80)
            fila[d] = p80
            print(f"    {d:>5.0f} cm  →  p80 {p80:>6}")
        medidas.append(fila)

    # --- análisis: razones DENTRO de cada ronda ---
    referencia = distancias[0]
    hip_ref = _hipotenusa(referencia, alt_mic, alt_boca)

    print("\n" + "=" * 66)
    print(f"  RESULTADO — todo relativo a la marca de {referencia:.0f} cm")
    print("=" * 66)
    print(f"\n  {'marca':>7}  {'razón medida':>14}  {'razón 1/d':>11}  "
          f"{'error':>8}")

    desvios = []
    for d in distancias[1:]:
        razones = [fila[d] / fila[referencia] for fila in medidas
                   if fila.get(referencia)]
        if not razones:
            continue
        medida   = _mediana(razones)
        predicha = hip_ref / _hipotenusa(d, alt_mic, alt_boca)
        error    = (medida - predicha) / predicha if predicha else 0.0
        desvios.append(abs(error))
        print(f"  {d:>5.0f}cm  {medida:>14.2f}  {predicha:>11.2f}  "
              f"{error:>+7.0%}")

    print(f"\n  (razones por ronda: " + " | ".join(
        ", ".join(f"{d:.0f}cm {fila[d] / fila[referencia]:.2f}"
                  for d in distancias[1:] if fila.get(referencia))
        for fila in medidas) + ")")

    print("\n" + "-" * 66)
    if not desvios:
        print("  No hay datos suficientes para concluir.")
        return 1

    peor = max(desvios)
    if peor <= _TOLERANCIA:
        print(f"  EL MODELO SE SOSTIENE (peor error {peor:.0%}, tolerancia "
              f"{_TOLERANCIA:.0%}).")
        print("  La señal cae como 1/distancia en esta sala, así que la")
        print("  hipotenusa predice bien. Podemos elegir la altura del")
        print("  micrófono por cálculo, sin remontarlo para probar.")
        objetivo = _preguntar_num(
            "\n  ¿A qué altura pensás subir el micrófono, en cm", 120.0)
        ganancia = (_hipotenusa(referencia, alt_mic, alt_boca) /
                    _hipotenusa(referencia, objetivo, alt_boca))
        print(f"\n  Subirlo de {alt_mic:.0f}cm a {objetivo:.0f}cm, con el "
              f"visitante a {referencia:.0f}cm:")
        print(f"    distancia acústica {_hipotenusa(referencia, alt_mic, alt_boca):.0f}cm"
              f" → {_hipotenusa(referencia, objetivo, alt_boca):.0f}cm")
        print(f"    señal x{ganancia:.2f}  →  tolera {ganancia:.2f}x más "
              f"ruido de sala")
        return 0

    print(f"  EL MODELO NO SE SOSTIENE (peor error {peor:.0%}).")
    print("  La señal NO cae como 1/distancia acá. Lo típico es que la")
    print("  sala reverbere: pasada cierta distancia el sonido reflejado")
    print("  domina sobre el directo y el nivel deja de subir al acercarse.")
    print("  Consecuencia PRÁCTICA: subir el micrófono rinde MENOS que lo")
    print("  que dice la geometría. Hay que medirlo remontándolo, no")
    print("  calcularlo. Empezá por la altura más alta que puedas y medí.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nCancelado.")
        sys.exit(130)
