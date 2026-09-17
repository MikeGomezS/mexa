# ============================================================
#  MEXA — Verificación del cableado de expresiones faciales
#
#  `_cara_animada.py` resuelve la expresión con POSES.get(nombre,
#  POSES["idle"]). O sea: un nombre mal escrito NO explota, cae a
#  `idle` EN SILENCIO. Nadie se entera nunca, y la cara simplemente
#  deja de reaccionar en ese punto del diálogo.
#
#  Este test cierra ese agujero y otro peor:
#
#    1. Toda expresión que el código pide EXISTE en POSES.
#    2. Toda expresión que se muestra MIENTRAS MEXA HABLA tiene
#       boca_vol > 0. Si no, la cara habla con la boca congelada:
#       la expresión se ve bien en una foto y rota en movimiento.
#    3. Informa qué poses quedaron sin cablear (no es error: hay
#       expresiones a propósito fuera del flujo).
#
#  HAY DOS FORMAS DE CAMBIAR DE CARA, y las dos se analizan:
#
#    a) como SENTENCIA suelta antes de hablar:
#           cambiar_expresion("feliz")
#           hablar(frase)
#
#    b) como CALLBACK dentro de la llamada que habla:
#           hablar_stream(gen, al_hablar=lambda: cambiar_expresion("hablando"))
#
#       La (b) existe porque consumir `gen` arranca el LLM y el prompt tarda
#       5-25 s en esta Pi: la cara tiene que cambiar cuando hay audio, no
#       cuando se llama. Una expresión puesta desde ahí está en pantalla
#       JUSTO cuando empieza a salir audio, así que cuenta como "habla" por
#       definición.
#
#       Sin analizar la (b) este test se vuelve CIEGO en silencio: pasa en
#       verde e informa la expresión como "sin cablear", que es el peor
#       resultado posible — parece que no hace falta revisarla.
#
#  Lee los archivos con `ast`, sin importarlos: importar
#  `_cara_animada` abre una ventana de pygame, y esto tiene que
#  poder correr por SSH sin proyector.
#
#  Correr con:  python3 tests/test_expresiones.py
# ============================================================

import ast
import os
import sys

RAIZ    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARA    = os.path.join(RAIZ, "modulos", "_cara_animada.py")
FUENTES = [os.path.join(RAIZ, *p) for p in (
    ("modulos", "dialogo.py"),
    ("modulos", "modulo_proyector.py"),
    ("main.py",),
)]

# Funciones que muestran una expresión, y funciones que hacen hablar a MEXA.
CAMBIAN = {"cambiar_expresion", "_iniciar_cara"}
HABLAN  = {"hablar", "hablar_stream"}


def _arbol(ruta: str) -> ast.Module:
    with open(ruta, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=ruta)


def _poses() -> dict[str, float]:
    """Nombre de pose -> su boca_vol, leídos de la tabla POSES."""
    arbol = _arbol(CARA)

    # Default de boca_vol en el dataclass Pose, por si una pose no lo pisa.
    defecto = 0.0
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ClassDef) and nodo.name == "Pose":
            for campo in nodo.body:
                if (isinstance(campo, ast.AnnAssign)
                        and getattr(campo.target, "id", None) == "boca_vol"
                        and campo.value is not None):
                    defecto = ast.literal_eval(campo.value)

    for nodo in ast.walk(arbol):
        # POSES está anotada (`POSES: dict[str, Pose] = {...}`), así que el
        # nodo es AnnAssign y no Assign. Se aceptan las dos formas.
        if isinstance(nodo, ast.AnnAssign):
            destinos = [nodo.target]
        elif isinstance(nodo, ast.Assign):
            destinos = nodo.targets
        else:
            continue
        if not any(getattr(d, "id", None) == "POSES" for d in destinos):
            continue
        if not isinstance(nodo.value, ast.Dict):
            continue
        tabla = {}
        for clave, valor in zip(nodo.value.keys, nodo.value.values):
            nombre = ast.literal_eval(clave)
            vol = defecto
            if isinstance(valor, ast.Call):
                for kw in valor.keywords:
                    if kw.arg == "boca_vol":
                        vol = ast.literal_eval(kw.value)
            tabla[nombre] = vol
        return tabla
    raise SystemExit("No encontré la tabla POSES en _cara_animada.py")


def _textos(nodo: ast.AST) -> list[str]:
    """Strings dentro de un nodo. Cubre el ternario de _despedirse()."""
    return [n.value for n in ast.walk(nodo)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _llama_a(nodo: ast.AST, nombres: set[str]) -> bool:
    for n in ast.walk(nodo):
        if isinstance(n, ast.Call):
            f = n.func
            id_f = getattr(f, "id", None) or getattr(f, "attr", None)
            if id_f in nombres:
                return True
    return False


def _usos(ruta: str) -> list[tuple[str, int, bool]]:
    """(expresión, línea, habla_con_esa_cara) por cada cambio de expresión.

    "Habla con esa cara" = entre este cambio de expresión y el siguiente del
    MISMO bloque hay una llamada a hablar(). Es exactamente la ventana en la
    que esa cara está en pantalla mientras sale audio.
    """
    encontrados = []

    def es_cambio(sentencia: ast.stmt) -> ast.Call | None:
        """La llamada a cambiar_expresion SOLO si es la sentencia en sí.

        Sin esto, un `while` o un `if` que contenga un cambio de expresión
        más adentro cuenta también como cambio, y la misma línea se reporta
        una vez por cada bloque que la envuelve."""
        if not isinstance(sentencia, ast.Expr) or not isinstance(sentencia.value, ast.Call):
            return None
        f = sentencia.value.func
        nombre = getattr(f, "id", None) or getattr(f, "attr", None)
        return sentencia.value if nombre in CAMBIAN else None

    def revisar_bloque(cuerpo: list[ast.stmt]) -> None:
        for i, sentencia in enumerate(cuerpo):
            llamada = es_cambio(sentencia)
            if llamada is None:
                continue
            habla = False
            for siguiente in cuerpo[i + 1:]:
                # Un cambio más adelante cierra la ventana: de ahí en más ya
                # hay otra cara en pantalla. Si una misma sentencia trae las
                # dos cosas, se corta igual (es lo conservador).
                if _llama_a(siguiente, CAMBIAN):
                    break
                if _llama_a(siguiente, HABLAN):
                    habla = True
                    break
            for nombre in _textos(llamada):
                encontrados.append((nombre, sentencia.lineno, habla))

    def _nombre_de(llamada: ast.Call) -> str | None:
        f = llamada.func
        return getattr(f, "id", None) or getattr(f, "attr", None)

    arbol = _arbol(ruta)

    # PASADA 1 — cambios como SENTENCIA (forma a).
    for nodo in ast.walk(arbol):
        for campo in ("body", "orelse", "finalbody"):
            cuerpo = getattr(nodo, campo, None)
            if isinstance(cuerpo, list) and cuerpo and isinstance(cuerpo[0], ast.stmt):
                revisar_bloque(cuerpo)

    # PASADA 2 — cambios pasados COMO ARGUMENTO a la llamada que habla
    # (forma b, el callback `al_hablar`). `revisar_bloque` no los ve nunca:
    # `es_cambio` exige que el cambio sea una sentencia, y acá es un
    # argumento dentro de un lambda.
    #
    # Estos van con habla=True SIN mirar qué hay alrededor, y no es un atajo:
    # una expresión que se pone desde dentro de hablar()/hablar_stream() está
    # en pantalla por construcción mientras sale el audio. No hay ventana que
    # calcular.
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call) or _nombre_de(nodo) not in HABLAN:
            continue
        for arg in list(nodo.args) + [kw.value for kw in nodo.keywords]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Call) and _nombre_de(sub) in CAMBIAN:
                    for nombre in _textos(sub):
                        encontrados.append((nombre, sub.lineno, True))

    return encontrados


def main() -> int:
    poses = _poses()
    print(f"POSES define {len(poses)} expresiones: {', '.join(sorted(poses))}\n")

    fallos = []
    usadas = set()

    for ruta in FUENTES:
        rel = os.path.relpath(ruta, RAIZ)
        for nombre, linea, habla in _usos(ruta):
            usadas.add(nombre)
            etiqueta = "habla" if habla else "muda "
            if nombre not in poses:
                fallos.append(f"{rel}:{linea} pide '{nombre}', que NO existe en POSES "
                              f"-> caería a idle en silencio")
                print(f"  FALTA    {rel}:{linea:<4} {etiqueta}  {nombre}")
            elif habla and poses[nombre] <= 0.0:
                fallos.append(f"{rel}:{linea} habla con '{nombre}', que tiene "
                              f"boca_vol=0 -> boca congelada mientras habla")
                print(f"  SIN BOCA {rel}:{linea:<4} {etiqueta}  {nombre}")
            else:
                print(f"  ok       {rel}:{linea:<4} {etiqueta}  {nombre}")

    sin_cablear = sorted(set(poses) - usadas)
    if sin_cablear:
        print(f"\nSin cablear (no es error): {', '.join(sin_cablear)}")

    if fallos:
        print(f"\n{len(fallos)} PROBLEMA(S):")
        for f in fallos:
            print(f"  - {f}")
        return 1

    print(f"\nTodo bien: {len(usadas)} expresiones cableadas, ninguna muda ni inexistente.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
