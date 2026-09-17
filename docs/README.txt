# docs/ — Informes y registros

## validaciones.txt
Qué se probó EN EL ROBOT y cuándo. Se edita a mano.

Existe porque los mensajes de commit no se actualizan: una línea "PENDIENTE
de validar en hardware" sigue diciendo lo mismo tres meses después de que
alguien lo validó. La historia de git es inmutable a propósito; el estado de
las validaciones no. Cuando un pendiente se valida, se anota ahí — NO se
reescribe el commit.

## informe_conexiones_arduino
Cableado completo del Arduino, protocolo serial y reflejos de freno.

  informe_conexiones_arduino.html   FUENTE — se edita esto
  informe_conexiones_arduino.pdf    salida — no se edita a mano

El PDF se regenera desde el HTML con Chromium en modo headless (en la Pi no
hay pandoc, weasyprint ni LaTeX; chromium ya viene instalado):

  chromium --headless --disable-gpu --no-sandbox --no-pdf-header-footer \
    --print-to-pdf="$PWD/docs/informe_conexiones_arduino.pdf" \
    "file://$PWD/docs/informe_conexiones_arduino.html"

Chromium escribe en stderr un `Error: unrecognized flag ...` que NO impide la
generación: el PDF sale igual. Mirar la línea "bytes written to file".

Para revisar el resultado sin abrirlo a mano:

  pdftoppm -png -r 62 docs/informe_conexiones_arduino.pdf /tmp/pg

REGLA: la fuente de verdad de los pines es arduino/mexa/mexa.ino, NUNCA este
informe. Si el firmware cambia un pin, se corrige el HTML y se regenera el PDF
EN EL MISMO COMMIT. Un informe de cableado desactualizado es peor que no tener
informe: se lee creyendo que es verdad.
