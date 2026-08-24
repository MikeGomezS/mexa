"""
Calibración del VOCABULARIO de civilizaciones: qué puede oír MEXA de verdad.

EL PROBLEMA QUE RESUELVE
------------------------
`CIVILIZACIONES` (modulos/contenido.py) matchea por subcadena contra lo que
transcribe Vosk. Pero un reconocedor SOLO puede emitir palabras que estén en
su léxico. Una clave cuya palabra no está en el modelo es CÓDIGO MUERTO: el
`if clave in texto` nunca se cumple, y no hay forma de notarlo leyendo el
código — el video existe, la clave existe, y aun así el visitante recibe
"no reconocí esa civilización" hasta que MEXA se rinde.

Medido al 2026-08-24 (ver modo `auditar`):
  modelo_vosk_en NO tiene: olmec, toltec, mixtec
→ los Olmecas y los Toltecas son inalcanzables por su nombre en inglés.

LOS TRES MODOS
--------------
  auditar → ¿está la palabra en el léxico del modelo? Lee la tabla de símbolos
            embebida en graph/Gr.fst. Instantáneo, no carga modelos ni micrófono.
            Responde "¿esta clave puede funcionar alguna vez?".

  tts     → sintetiza cada frase con Piper (la misma voz que usa MEXA), la
            degrada a condiciones de sala y se la da al MISMO recognizer libre
            que usa `escuchar_pregunta`. Captura la transcripción CRUDA y
            propone el alias. Sin humano, sin micrófono, repetible.
            Responde "¿qué escribe Vosk cuando alguien dice esto?".

  mic     → lo mismo pero con un humano hablándole al micrófono USB, por la
            cadena de producción entera (VAD, resample, stream persistente).
            Es el que manda: el TTS propone, el micrófono dispone.

USO
---
  python3 tests/calibrar_vocabulario.py auditar
  python3 tests/calibrar_vocabulario.py tts
  python3 tests/calibrar_vocabulario.py tts --solo-huecos --repeticiones 5
  python3 tests/calibrar_vocabulario.py mic --idioma es --civilizacion "los Olmecas"

Al final imprime las líneas listas para pegar en `CIVILIZACIONES`, ya validadas
contra colisiones con las claves que ya existen.

OJO CON EL TTS: Piper pronuncia limpio y parejo. Si una frase falla acá, en la
sala falla seguro. Pero que pase acá NO garantiza que pase en la sala — por eso
el modo `mic` existe y por eso los alias se confirman con voz real antes de
darlos por buenos.
"""

import argparse
import audioop
import json
import os
import random
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modulos import contenido


# ── Qué se prueba ────────────────────────────────────────────
# Por civilización: cómo la pediría un visitante, en cada idioma.
# El nombre canónico es el que devuelve `detectar_civilizacion`.
CIVS: list[tuple[str, list[str], list[str]]] = [
    ("los Mayas",
     ["los mayas", "quiero aprender de los mayas"],
     ["the mayas", "i want to learn about the mayas"]),
    ("los Aztecas",
     ["los aztecas", "cuéntame de los aztecas"],
     ["the aztecs", "tell me about the aztecs"]),
    ("Teotihuacán",
     ["teotihuacán", "quiero ver teotihuacán"],
     ["teotihuacan", "i want to see teotihuacan"]),
    ("los Olmecas",
     ["los olmecas", "háblame de los olmecas"],
     ["the olmecs", "tell me about the olmecs"]),
    ("los Toltecas",
     ["los toltecas", "quiero ver los toltecas"],
     ["the toltecs", "i want to see the toltecs"]),
    ("los Zapotecas",
     ["los zapotecas", "cuéntame de los zapotecas"],
     ["the zapotecs", "tell me about the zapotecs"]),
    ("los Mixtecas",
     ["los mixtecas", "háblame de los mixtecas"],
     ["the mixtecs", "tell me about the mixtecs"]),
]

# Combinaciones que hoy sabemos rotas. `--solo-huecos` prueba estas.
HUECOS = {
    ("los Olmecas", "en"), ("los Toltecas", "en"), ("los Mixtecas", "en"),
}

_FST = {
    "es": "modelo_vosk_es/graph/Gr.fst",
    "en": "modelo_vosk_en/graph/Gr.fst",
}

# Umbrales del veredicto. Un alias fonético solo sirve si la transcripción es
# ESTABLE: si hacen falta muchos alias o igual queda destapada buena parte de
# los casos, el problema no se arregla agregando claves.
_MAX_ALIAS = 5
_COBERTURA_MINIMA = 80.0   # % de transcripciones únicas que debe cubrir el conjunto


# ════════════════════════════════════════════════════════════
#  MODO 1 — auditar el léxico
# ════════════════════════════════════════════════════════════
# La tabla de símbolos de OpenFst guarda cada palabra como texto plano
# dentro del .fst, así que se puede buscar sin cargar Vosk.
#
# RIGOR DE LA MEDICIÓN, porque importa no vender más de lo que mide:
#   AUSENCIA  → certeza. Si la secuencia de bytes no está en el archivo,
#               la palabra NO está en el léxico. Punto.
#   PRESENCIA → indicio. "maya" aparece dentro de "mayaguana". Por eso se
#               imprime el contexto vecino: que lo juzgue el humano.

def _leer_fst(idioma: str) -> bytes:
    ruta = _FST[idioma]
    if not os.path.isfile(ruta):
        raise FileNotFoundError(f"No está el modelo: {ruta}")
    with open(ruta, "rb") as f:
        return f.read()


def _contextos(blob: bytes, palabra: str, maximo: int = 6) -> list[str]:
    """Devuelve los tokens imprimibles que CONTIENEN la palabra."""
    pat = re.escape(palabra.encode("utf-8"))
    vistos: list[str] = []
    for m in re.finditer(pat, blob, re.IGNORECASE):
        ini, fin = m.start(), m.end()
        while ini > 0 and 0x20 < blob[ini - 1] < 0x7F or (ini > 0 and blob[ini - 1] > 0xBF):
            ini -= 1
        while fin < len(blob) and (0x20 < blob[fin] < 0x7F or blob[fin] > 0x7F):
            fin += 1
        tok = blob[ini:fin].decode("utf-8", "ignore").strip()
        tok = re.sub(r"[^\w\-']", "", tok, flags=re.UNICODE)
        if tok and tok not in vistos:
            vistos.append(tok)
        if len(vistos) >= maximo:
            break
    return vistos


def _existe(modelo, clave: str) -> bool:
    """¿Puede el modelo emitir esta clave?

    `vosk_model_find_word` consulta la tabla de palabras del modelo y
    devuelve -1 si no está. Es EXACTA, a diferencia de buscar la cadena
    dentro del Gr.fst: ese grep daba falsos positivos porque "olmec"
    aparece dentro de "olmeca" y "aztec" dentro de "azteca".

    Una clave de varias palabras vive solo si viven TODAS sus palabras.
    """
    return all(modelo.vosk_model_find_word(w) != -1 for w in clave.split())


def auditar(mostrar_contexto: bool = False) -> int:
    """Revisa cada clave del catálogo contra el léxico de ambos modelos."""
    from vosk import Model, SetLogLevel
    SetLogLevel(-1)

    print("=" * 72)
    print("AUDITORÍA DE LÉXICO — ¿puede el modelo emitir esta palabra?")
    print("Fuente: vosk_model_find_word (tabla de palabras del modelo).")
    print("=" * 72)

    modelos = {}
    for idioma, ruta in (("es", "modelo_vosk_es"), ("en", "modelo_vosk_en")):
        if os.path.isdir(ruta):
            modelos[idioma] = Model(ruta)
        else:
            print(f"  [{idioma}] falta el modelo en {ruta}")

    alcance: dict[tuple[str, str], list[str]] = {}
    muertas: list[str] = []

    print(f"\n  {'CLAVE':<15} {'es':>4} {'en':>4}   civilización")
    print("  " + "-" * 60)
    for clave, (_e, _n, nombre) in contenido.CIVILIZACIONES.items():
        viva_en_alguno = False
        celdas = []
        for idioma in ("es", "en"):
            m = modelos.get(idioma)
            if m is None:
                celdas.append("?")
                continue
            if _existe(m, clave):
                celdas.append("SÍ")
                alcance.setdefault((nombre, idioma), []).append(clave)
                viva_en_alguno = True
            else:
                celdas.append("·")
        if not viva_en_alguno:
            muertas.append(clave)
        print(f"  {clave:<15} {celdas[0]:>4} {celdas[1]:>4}   {nombre}")

        if mostrar_contexto:
            # Exploratorio: qué palabras PARECIDAS sí tiene el léxico. Sirve
            # para buscar un sinónimo alcanzable cuando la clave no existe.
            for idioma in ("es", "en"):
                try:
                    blob = _leer_fst(idioma)
                except FileNotFoundError:
                    continue
                ctx = _contextos(blob, clave)
                if ctx:
                    print(f"       {idioma}~ {', '.join(ctx)}")

    print("\n" + "-" * 72)
    print("ALCANCE POR CIVILIZACIÓN (vive si vive AL MENOS UNA de sus claves)")
    print("-" * 72)
    rotos: list[tuple[str, str]] = []
    for nombre in contenido.NOMBRES_DISPONIBLES:
        for idioma in ("es", "en"):
            vivas = alcance.get((nombre, idioma), [])
            if vivas:
                print(f"  OK        {nombre:<16}[{idioma}] ← {', '.join(vivas)}")
            else:
                print(f"  INALCANZ. {nombre:<16}[{idioma}] ← ninguna clave está en el léxico")
                rotos.append((nombre, idioma))

    if muertas:
        print("\n" + "-" * 72)
        print("CLAVES MUERTAS EN AMBOS MODELOS (ruido: nunca pueden matchear)")
        print("-" * 72)
        print("  " + ", ".join(muertas))

    print(f"\n{len(rotos)} combinación(es) civilización×idioma sin ninguna clave viva.")
    if rotos:
        print("Ninguna se arregla agregando claves: la palabra no existe en el")
        print("léxico del modelo. Ver el docstring para las salidas de fondo.")
    return 1 if rotos else 0


# ════════════════════════════════════════════════════════════
#  MODO 2 — qué transcribe Vosk (síntesis Piper)
# ════════════════════════════════════════════════════════════

_RUIDOS = [(0.00, 1.00), (0.04, 0.7), (0.06, 0.5), (0.09, 0.4), (0.12, 0.35)]


def _degradar(pcm: bytes, semilla: int, ruido: float, ganancia: float) -> bytes:
    """Simula el micrófono de sala: atenúa y ensucia.

    A diferencia de tests/test_idioma.py — que fija la semilla para ser
    reproducible bit a bit — acá se BARRE el espacio de condiciones a
    propósito: buscamos con qué transcripciones nos topamos, no un
    veredicto binario. Cada repetición usa otra semilla y otro nivel.
    """
    if ganancia != 1.0:
        pcm = audioop.mul(pcm, 2, ganancia)
    if ruido <= 0:
        return pcm
    n = len(pcm) // 2
    rng = random.Random(semilla)
    amp = int(32767 * ruido)
    sucio = [max(-32768, min(32767, m + rng.randint(-amp, amp)))
             for m in struct.unpack(f"<{n}h", pcm)]
    return struct.pack(f"<{n}h", *sucio)


def _reconocer_libre(pcm: bytes, idioma: str) -> str:
    """Decodifica con recognizer SIN gramática — igual que escuchar_pregunta."""
    from vosk import KaldiRecognizer
    from modulos.modulo_audio import _VOSK_RATE, _cargar_modelo
    rec = KaldiRecognizer(_cargar_modelo(idioma), _VOSK_RATE)
    rec.AcceptWaveform(pcm)
    return json.loads(rec.FinalResult()).get("text", "").strip()


def _cargar_sintetizador():
    """Toma `_sintetizar` de tests/test_idioma.py, la fuente única de síntesis.

    Se carga POR RUTA y no con `from tests.test_idioma import ...` porque en
    esta máquina hay un paquete `tests` de terceros en site-packages que
    secuestra el nombre: un paquete regular siempre le gana a un namespace
    package, sin importar el orden de sys.path. Cargar por ruta es inmune.
    """
    import importlib.util
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_idioma.py")
    spec = importlib.util.spec_from_file_location("_mexa_test_idioma", ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._sintetizar


def probar_tts(solo_huecos: bool, repeticiones: int,
               filtro_idioma: str | None, filtro_civ: str | None) -> list[dict]:
    _sintetizar = _cargar_sintetizador()

    casos = []
    for nombre, frases_es, frases_en in CIVS:
        if filtro_civ and filtro_civ.lower() not in nombre.lower():
            continue
        for idioma, frases in (("es", frases_es), ("en", frases_en)):
            if filtro_idioma and idioma != filtro_idioma:
                continue
            if solo_huecos and (nombre, idioma) not in HUECOS:
                continue
            for frase in frases:
                casos.append((nombre, idioma, frase))

    if not casos:
        print("No hay casos que probar con esos filtros.")
        return []

    print("=" * 72)
    print(f"TRANSCRIPCIÓN POR TTS — {len(casos)} frase(s) × {repeticiones} condición(es)")
    print("=" * 72)

    observaciones: list[dict] = []
    for nombre, idioma, frase in casos:
        voz = idioma  # cada idioma con su voz Piper
        try:
            limpio = _sintetizar(frase, voz)
        except Exception as e:
            print(f"  ERROR sintetizando {frase!r} ({voz}): {e}")
            continue

        print(f"\n  [{idioma}] esperado: {nombre}   dicho: {frase!r}")
        for i in range(repeticiones):
            ruido, ganancia = _RUIDOS[min(i, len(_RUIDOS) - 1)]
            pcm = _degradar(limpio, semilla=1000 + i, ruido=ruido, ganancia=ganancia)
            texto = _reconocer_libre(pcm, idioma)
            obtenido = contenido.detectar_civilizacion(texto, idioma)
            nombre_obt = obtenido[1] if obtenido else None

            if not texto:
                estado = "MUDO"
            elif nombre_obt == nombre:
                estado = "OK"
            elif nombre_obt is None:
                estado = "PERDIDO"
            else:
                estado = "CRUZADO"

            cond = "limpio" if ruido == 0 else f"ruido {ruido:.2f}"
            extra = f" → enganchó {nombre_obt}" if estado == "CRUZADO" else ""
            print(f"      {estado:<8} [{cond:<10}] oyó: {texto!r}{extra}")

            observaciones.append({
                "esperado": nombre, "idioma": idioma, "frase": frase,
                "texto": texto, "estado": estado, "obtenido": nombre_obt,
            })
    return observaciones


# ════════════════════════════════════════════════════════════
#  MODO 3 — micrófono real, cadena de producción
# ════════════════════════════════════════════════════════════

def probar_mic(repeticiones: int, filtro_idioma: str | None,
               filtro_civ: str | None) -> list[dict]:
    from modulos.modulo_audio import escuchar_pregunta

    casos = []
    for nombre, frases_es, frases_en in CIVS:
        if filtro_civ and filtro_civ.lower() not in nombre.lower():
            continue
        for idioma, frases in (("es", frases_es), ("en", frases_en)):
            if filtro_idioma and idioma != filtro_idioma:
                continue
            casos.append((nombre, idioma, frases[0]))

    if not casos:
        print("No hay casos que probar con esos filtros.")
        return []

    print("=" * 72)
    print("PRUEBA CON MICRÓFONO — cadena de producción completa")
    print(f"{len(casos)} caso(s) × {repeticiones} repetición(es). Ctrl+C para cortar.")
    print("Hablá a la distancia real del visitante, no pegado al micrófono.")
    print("=" * 72)

    observaciones: list[dict] = []
    try:
        for nombre, idioma, sugerida in casos:
            print(f"\n  [{idioma}] {nombre} — decí algo como: {sugerida!r}")
            for i in range(repeticiones):
                input(f"      ENTER y hablá ({i + 1}/{repeticiones})... ")
                texto = escuchar_pregunta(timeout=8, idioma=idioma)
                obtenido = contenido.detectar_civilizacion(texto, idioma)
                nombre_obt = obtenido[1] if obtenido else None

                if not texto:
                    estado = "MUDO"
                elif nombre_obt == nombre:
                    estado = "OK"
                elif nombre_obt is None:
                    estado = "PERDIDO"
                else:
                    estado = "CRUZADO"

                extra = f" → enganchó {nombre_obt}" if estado == "CRUZADO" else ""
                print(f"      {estado:<8} oyó: {texto!r}{extra}")
                observaciones.append({
                    "esperado": nombre, "idioma": idioma, "frase": sugerida,
                    "texto": texto, "estado": estado, "obtenido": nombre_obt,
                })
    except (KeyboardInterrupt, EOFError):
        print("\n  Interrumpido — se analiza lo que se alcanzó a medir.")
    return observaciones


# ════════════════════════════════════════════════════════════
#  Análisis: de la transcripción cruda al alias
# ════════════════════════════════════════════════════════════

def _simular(texto: str, alias: str, nombre_destino: str) -> str | None:
    """Qué devolvería detectar_civilizacion si `alias` se agregara AL FINAL.

    Replica la regla real: gana la PRIMERA clave que sea subcadena del texto,
    en orden de inserción. Por eso un alias agregado al final puede quedar
    tapado por una clave anterior — esto lo detecta antes de que pase en sala.
    """
    t = texto.lower()
    for clave, (_es, _en, nombre) in contenido.CIVILIZACIONES.items():
        if clave in t:
            return nombre
    return nombre_destino if alias in t else None


def _candidatos(texto: str, frase: str) -> list[str]:
    """N-gramas formados SOLO por palabras que el reconocedor inventó.

    Sin este filtro el análisis propone el acarreo de la pregunta —
    "quiero ver a", "tell me about" — que efectivamente aparece en las
    transcripciones huérfanas, pero como alias es veneno: mandaría
    CUALQUIER pregunta al video de esa civilización.

    La señal está en la diferencia. Lo que se dijo se transcribió bien
    salvo donde estaba la palabra que el modelo no conoce; ahí improvisa.
    Así que solo sirven los n-gramas hechos de palabras que están en lo
    OÍDO y no en lo DICHO.
    """
    dichas = {p for p in re.split(r"\W+", frase.lower()) if p}
    pal = [p for p in re.split(r"\s+", texto.lower()) if p]
    nuevas = [p not in dichas for p in pal]

    salida = []
    for n in (3, 2, 1):
        for i in range(len(pal) - n + 1):
            if not all(nuevas[i:i + n]):
                continue
            g = " ".join(pal[i:i + n])
            if len(g) >= 4:
                salida.append(g)
    return salida


def reportar(observaciones: list[dict]) -> int:
    if not observaciones:
        return 0

    print("\n" + "=" * 72)
    print("RESUMEN")
    print("=" * 72)
    conteo: dict[str, int] = {}
    for o in observaciones:
        conteo[o["estado"]] = conteo.get(o["estado"], 0) + 1
    for estado in ("OK", "PERDIDO", "CRUZADO", "MUDO"):
        if estado in conteo:
            print(f"  {estado:<8} {conteo[estado]}")

    cruzados = [o for o in observaciones if o["estado"] == "CRUZADO"]
    if cruzados:
        print("\n  CRUZADOS — MEXA proyecta el video EQUIVOCADO. Arreglar primero:")
        for o in cruzados:
            print(f"    [{o['idioma']}] {o['frase']!r} → oyó {o['texto']!r} "
                  f"→ dio {o['obtenido']} en vez de {o['esperado']}")

    # Para cada combinación perdida, buscar el n-grama que más se repite y
    # que no quede tapado por una clave anterior.
    perdidos: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for o in observaciones:
        if o["estado"] == "PERDIDO" and o["texto"]:
            perdidos.setdefault((o["esperado"], o["idioma"]), []).append(
                (o["texto"], o["frase"]))

    if not perdidos:
        print("\n  Sin transcripciones huérfanas: no hay alias que proponer.")
        return 1 if cruzados else 0

    print("\n" + "-" * 72)
    print("ALIAS PROPUESTOS (validados contra el catálogo actual)")
    print("-" * 72)

    rutas = {n: (a, b) for (a, b, n) in contenido.CIVILIZACIONES.values()}
    lineas: list[str] = []

    # Todo lo que se oyó, por civilización: sirve para probar cada alias
    # candidato contra las transcripciones de las OTRAS. Un alias que aparece
    # en lo que se oyó al pedir otra civilización es un falso positivo ya
    # medido — no hace falta esperar a la sala para descubrirlo.
    oido_por_civ: dict[str, set[str]] = {}
    for o in observaciones:
        if o["texto"]:
            oido_por_civ.setdefault(o["esperado"], set()).add(o["texto"].lower())

    for (nombre, idioma), pares in sorted(perdidos.items()):
        textos = [t for t, _f in pares]
        frecuencia: dict[str, int] = {}
        for t, f in pares:
            for g in _candidatos(t, f):
                frecuencia[g] = frecuencia.get(g, 0) + 1

        print(f"\n  {nombre} [{idioma}] — {len(textos)} transcripción(es) huérfana(s):")
        for t in sorted(set(textos)):
            print(f"      oyó: {t!r}")

        # Cobertura por conjunto, no por alias suelto: se eligen n-gramas de
        # forma greedy hasta cubrir todas las transcripciones. Si Vosk oye algo
        # distinto en cada condición, un solo alias NUNCA alcanza — y decirlo
        # es más útil que proponer uno que tapa 2 de 6 y da falsa tranquilidad.
        pendientes = list(dict.fromkeys(textos))
        elegidos: list[tuple[str, int]] = []
        descartados: list[tuple[str, str]] = []
        while pendientes and len(elegidos) < _MAX_ALIAS:
            mejor = None
            for g in sorted(frecuencia, key=lambda k: (-frecuencia[k], -len(k))):
                if g in contenido.CIVILIZACIONES or g in [e for e, _ in elegidos]:
                    continue
                # No debe quedar tapado por una clave anterior del catálogo:
                # gana la PRIMERA coincidencia, no la más específica.
                if any(_simular(t, g, nombre) not in (nombre, None)
                       for t in textos if g in t.lower()):
                    continue
                # Ni debe aparecer en lo que se oyó al pedir OTRA civilización.
                colision = next((otra for otra, oidos in oido_por_civ.items()
                                 if otra != nombre and any(g in t for t in oidos)), None)
                if colision:
                    motivo = (g, f"aparece al pedir {colision}")
                    if motivo not in descartados:
                        descartados.append(motivo)
                    continue
                cubre = sum(1 for t in pendientes if g in t.lower())
                if cubre and (mejor is None or cubre > mejor[1]):
                    mejor = (g, cubre)
            if mejor is None:
                break
            g, cubre = mejor
            elegidos.append((g, cubre))
            pendientes = [t for t in pendientes if g not in t.lower()]

        cubiertas = len(set(textos)) - len(pendientes)
        total_unicas = len(set(textos))

        if not elegidos:
            print("      SIN CANDIDATO LIMPIO — hay que revisarlo a mano.")
            continue

        for g, motivo in descartados[:4]:
            print(f"      descartado {g!r}: {motivo}")

        riesgosos = [g for g, _c in elegidos if " " not in g and len(g) <= 6]
        for g, cubre in elegidos:
            aviso = ""
            if g in riesgosos:
                aviso = "   ⚠ palabra suelta y corta: puede salir en charla normal"
            print(f"      → alias: {g!r}  (+{cubre}){aviso}")

        pct = 100 * cubiertas / total_unicas
        print(f"      cobertura del conjunto: {cubiertas}/{total_unicas} ({pct:.0f}%) "
              f"con {len(elegidos)} alias")

        if riesgosos:
            print(f"      VEREDICTO: NO PEGAR TAL CUAL — {', '.join(repr(g) for g in riesgosos)}")
            print("      son palabras comunes del idioma. Como el match es por")
            print("      subcadena, secuestrarían preguntas que no tienen nada que")
            print("      ver. Confirmá con `mic` y quedate solo con los n-gramas")
            print("      de dos o más palabras.")
            continue

        if pct < _COBERTURA_MINIMA or len(elegidos) > 3:
            print("      VEREDICTO: TRANSCRIPCIÓN INESTABLE.")
            print("      Vosk oye algo distinto en cada condición: la palabra no está")
            print("      en su léxico y el decodificador improvisa. Parchear con alias")
            print("      acá es tapar el sol con un dedo — cada visitante nuevo trae")
            print("      una transcripción que no está en la lista. Ver el docstring:")
            print("      hace falta modelo grande, léxico propio, o rediseñar la")
            print("      pregunta para que la respuesta esté en el léxico (números).")
            continue

        esp, eng = rutas.get(nombre, ("?", "?"))
        esp = "_ESP + \"/" + os.path.basename(esp) + "\""
        eng = "_ENG + \"/" + os.path.basename(eng) + "\""
        for g, _c in elegidos:
            lineas.append(
                f'    "{g}":{" " * max(1, 14 - len(g))}({esp},{" " * 3}{eng},{" " * 3}"{nombre}"),')

    if lineas:
        print("\n" + "-" * 72)
        print("PEGAR EN CIVILIZACIONES (modulos/contenido.py), AL FINAL DEL DICT:")
        print("-" * 72)
        print("    # Alias fonéticos: lo que Vosk transcribe de verdad cuando")
        print("    # alguien pide esta civilización. Medidos con")
        print("    # tests/calibrar_vocabulario.py — no son adivinanzas.")
        for l in lineas:
            print(l)
        print("\n  Confirmá con `mic` antes de darlos por buenos si salieron de `tts`.")

    return 1 if cruzados else 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Mide qué palabras de civilizaciones puede oír MEXA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("USO\n---\n")[1] if "USO\n---\n" in __doc__ else "",
    )
    p.add_argument("modo", choices=("auditar", "tts", "mic"))
    p.add_argument("--repeticiones", type=int, default=3,
                   help="condiciones de ruido por frase (tts) o intentos (mic)")
    p.add_argument("--solo-huecos", action="store_true",
                   help="probar solo las combinaciones que ya sabemos rotas")
    p.add_argument("--idioma", choices=("es", "en"), default=None)
    p.add_argument("--civilizacion", default=None,
                   help="filtrar por nombre, ej: --civilizacion Olmecas")
    p.add_argument("--contexto", action="store_true",
                   help="(auditar) mostrar en qué tokens del léxico aparece cada clave")
    args = p.parse_args()

    if args.modo == "auditar":
        return auditar(args.contexto)
    if args.modo == "tts":
        obs = probar_tts(args.solo_huecos, max(1, args.repeticiones),
                         args.idioma, args.civilizacion)
    else:
        obs = probar_mic(max(1, args.repeticiones), args.idioma, args.civilizacion)
    return reportar(obs)


if __name__ == "__main__":
    sys.exit(main())
