# Este archivo existe por un CHOQUE DE NOMBRES, no por diseño.
#
# `speechrecognition` (instalado en site-packages) publica un paquete
# `tests` de nivel raíz. Sin __init__.py, la carpeta tests/ de este repo
# es un "namespace package" y Python la deja de lado en cuanto encuentra
# un paquete REGULAR con el mismo nombre más adelante en sys.path — así
# que `python3 -m tests.test_idioma` corría los tests de esa librería en
# vez de los de MEXA, o directamente fallaba con "No module named".
#
# Con __init__.py, tests/ pasa a ser un paquete regular y gana por estar
# primero en sys.path (el directorio de trabajo). Se arregla acá y no
# desinstalando speechrecognition porque el problema es de ESTE repo
# resolviendo SU nombre, y porque tocar los paquetes de la máquina para
# que ande un test es arreglar la casa del vecino.
