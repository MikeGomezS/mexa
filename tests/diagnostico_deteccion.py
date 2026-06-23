"""
Diagnóstico VISUAL de la detección de caras (YuNet) de MEXA.

Captura N frames y, en cada uno, dibuja TODAS las caras que devuelve YuNet
con un umbral de score BAJO (0.3) — a propósito más bajo que el de producción
(_SCORE_MIN) para VER también las detecciones dudosas y calibrar el umbral.
Cada caja se anota con: score de confianza, tamaño% (alto_caja/alto_frame) y
posición (izq/centro/der). La caja MÁS GRANDE — la que el lazo elegiría — va
en ROJO; el resto en amarillo. Guarda los frames anotados en tests/diag_frames/.

USO (cámara conectada; parate frente a MEXA a la distancia del PIR):
  python3 tests/diagnostico_deteccion.py            # 15 frames, ~1/seg
  python3 tests/diagnostico_deteccion.py 30 0.3     # 30 frames cada 0.3s

Después abrí las imágenes de tests/diag_frames/ y fijate:
  - ¿La caja ROJA cae sobre tu cara, con score alto (>0.9)?
  - ¿Aparece alguna caja sobre el fondo (silla/reflejo) y con qué score?
  - El score de tu cara real vs el de cualquier fantasma decide _SCORE_MIN.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
from modulos.modulo_camara import iniciar_camara, capturar_frame, _YUNET_MODELO

SALIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diag_frames")

# Detector propio con umbral BAJO para ver hasta las detecciones dudosas.
_SCORE_DIAG = 0.3
_det = cv2.FaceDetectorYN.create(_YUNET_MODELO, "", (1280, 720),
                                 score_threshold=_SCORE_DIAG)


def _clasificar(centro_x, ancho):
    if centro_x < ancho * 0.4:
        return "izq"
    if centro_x > ancho * 0.6:
        return "der"
    return "centro"


def main() -> None:
    n_frames = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    intervalo = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0

    os.makedirs(SALIDA, exist_ok=True)
    print(f"[DIAG] Iniciando cámara...")
    iniciar_camara()
    time.sleep(1)  # dejar que el autofocus asiente

    print(f"[DIAG] Capturando {n_frames} frames cada {intervalo:.1f}s "
          f"(umbral diagnóstico score>={_SCORE_DIAG}).")
    print(f"[DIAG] Parate frente a MEXA. Guardo en {SALIDA}/")

    guardados = 0
    for i in range(n_frames):
        frame = capturar_frame()
        if frame is None:
            print(f"[DIAG] frame {i:02d}: SIN frame (cámara/timeout).")
            time.sleep(intervalo)
            continue

        alto, ancho = frame.shape[0], frame.shape[1]
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)  # YuNet espera BGR
        _det.setInputSize((ancho, alto))
        _, caras = _det.detect(bgr)
        caras = [] if caras is None else list(caras)
        n = len(caras)

        # Índice de la caja MÁS GRANDE (la que el lazo elegiría con max área).
        idx_grande = -1
        if n > 0:
            areas = [c[2] * c[3] for c in caras]
            idx_grande = max(range(n), key=lambda k: areas[k])

        resumen = []
        for k, c in enumerate(caras):
            x, y, w, h = int(c[0]), int(c[1]), int(c[2]), int(c[3])
            score = float(c[-1])
            tam = h / alto
            pos = _clasificar(x + w // 2, ancho)
            es_grande = (k == idx_grande)
            color = (0, 0, 255) if es_grande else (0, 220, 220)  # rojo / amarillo
            cv2.rectangle(bgr, (x, y), (x + w, y + h), color, 3)
            cv2.putText(bgr, f"s={score:.2f} {tam:.0%} {pos}", (x, max(0, y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            marca = "*" if es_grande else " "
            resumen.append(f"{marca}s{score:.2f}/{tam:.0%}/{pos}")

        ruta = os.path.join(SALIDA, f"frame_{i:02d}.jpg")
        cv2.imwrite(ruta, bgr)
        guardados += 1
        cajas_txt = ", ".join(resumen) if resumen else "(ninguna)"
        print(f"[DIAG] frame {i:02d}: {n} cara(s) [{cajas_txt}]  -> {ruta}")
        time.sleep(intervalo)

    print(f"[DIAG] Listo. {guardados} imágenes en {SALIDA}/")
    print("[DIAG] La caja ROJA (*) es la que el lazo seguiría. "
          "Mirá el score de tu cara vs el de cualquier fantasma.")


if __name__ == "__main__":
    main()
