// ============================================================
//  MEXA — Firmware del Arduino (un solo Arduino para todo)
//  ESTADO: 4 motores DC + 2 servos de brazos activos.
//  Los brazos usan la librería Servo con gesto NO bloqueante
//  (barrido por millis(), para no frenar la lectura serial).
//
//  PINOUT MOTORES (4 motores, puente(s) H tipo MX1508):
//    Motor 0  ->  D2, D3
//    Motor 1  ->  D4, D5
//    Motor 2  ->  D6, D7
//    Motor 3  ->  D8, D9
//
//  AGRUPACIÓN (provisional — ajustar tras identificar):
//    LADO IZQUIERDO  = Motor 0 + Motor 1
//    LADO DERECHO    = Motor 2 + Motor 3
//
//  PROTOCOLO SERIAL (9600 baud, comandos de 1 letra):
//    Conducir:  F=adelante  B=atrás  R=derecha  L=izquierda  S=stop
//    Identificar (mueve UN solo motor hacia "adelante"):
//               1=Motor0  2=Motor1  3=Motor2  4=Motor3
//    Brazos:    H=gesticular (hablando)  P=volver a reposo
//               Servos: brazo derecho -> D10 ; brazo izquierdo -> D11
//
//  PRESENCIA (2x PIR HC-SR501, leídos por el Arduino):
//    PIR derecho  -> D24 ; PIR izquierdo -> D22
//    Se reporta a la Pi por serial: "PRES:1"/"PRES:0" (lógica OR de
//    ambos PIR), al cambiar de estado + heartbeat cada 1s.
//
//  ULTRASÓNICOS (2x HC-SR04, evitan chocar paredes AL MANIOBRAR):
//    Derecho   TRIG -> D29 ; ECHO -> D28
//    Izquierdo TRIG -> D31 ; ECHO -> D30
//    El Mega tolera 5V en sus entradas → ECHO va directo (sin divisor).
//    La evasión es 100% firmware: durante un giro (R/L) frena si el
//    lateral correspondiente está más cerca que UMBRAL_PARED_CM.
//
//  PROTOCOLO DE SALIDA (Arduino -> Pi, líneas terminadas en '\n'):
//    "OK <cmd>"  eco de comando | "PRES:0/1" presencia | "WALL:I/D" evasión
//
//  DIAGNÓSTICO: banner al arrancar + "OK <cmd>" por comando +
//  LED de la placa (pin 13) encendido = hay orden de motor activa.
//
//  ALIMENTACIÓN: VM del driver -> + de la pila ; GND del driver
//  -> - de la pila Y TAMBIÉN al GND del Arduino (tierra común).
// ============================================================

#include <Servo.h>

// ── Motores ──────────────────────────────────────────────────
// Cada motor: {pinA, pinB}. dir +1 → A=HIGH,B=LOW ; -1 → A=LOW,B=HIGH ; 0 → ambos LOW
const uint8_t MOTOR_PIN[4][2] = {
    {2, 3},   // Motor 0  (tecla 1) — lado IZQUIERDO
    {4, 5},   // Motor 1  (tecla 2) — lado IZQUIERDO
    {6, 7},   // Motor 2  (tecla 3) — lado DERECHO
    {8, 9},   // Motor 3  (tecla 4) — lado DERECHO
};

// Sentido por motor. Los del lado DERECHO están montados en espejo y
// giran al revés → se invierten por software (sin tocar cables).
// Si alguno sigue al revés, cambiá su true/false acá.
const bool INVERTIR[4] = { false, false, true, true };

void motor(uint8_t i, int dir) {
    if (INVERTIR[i]) dir = -dir;
    digitalWrite(MOTOR_PIN[i][0], dir > 0 ? HIGH : LOW);
    digitalWrite(MOTOR_PIN[i][1], dir < 0 ? HIGH : LOW);
}

// Agrupación de lados: izquierda = motores 0,1 ; derecha = motores 2,3
void ladoIzq(int dir) { motor(0, dir); motor(1, dir); }
void ladoDer(int dir) { motor(2, dir); motor(3, dir); }

void detenerTodo() {
    for (uint8_t i = 0; i < 4; i++) motor(i, 0);
}

// Mueve UN solo motor hacia adelante, frena los demás (identificación)
void soloMotor(uint8_t i) {
    detenerTodo();
    motor(i, +1);
}

void led(bool encendido) {
    digitalWrite(LED_BUILTIN, encendido ? HIGH : LOW);
}

// ── Brazos (servos) ──────────────────────────────────────────
// Gesto no bloqueante: al recibir 'H' los brazos oscilan entre
// BRAZO_MIN y BRAZO_MAX; con 'P' vuelven a BRAZO_REPOSO.
// Ajustá los ángulos según el montaje mecánico real.
const uint8_t SERVO_DER_PIN = 10;
const uint8_t SERVO_IZQ_PIN = 11;

const int BRAZO_REPOSO = 90;   // ángulo en reposo
const int BRAZO_MIN    = 60;   // extremos del barrido al hablar
const int BRAZO_MAX    = 120;
const int BRAZO_PASO   = 2;    // grados por actualización
const unsigned long BRAZO_INTERVALO_MS = 15;  // velocidad del gesto

Servo brazoIzq, brazoDer;
bool animandoBrazos = false;
int  brazoAng = BRAZO_REPOSO;
int  brazoDir = +1;
unsigned long brazoUltimo = 0;

void brazosReposo() {
    brazoAng = BRAZO_REPOSO;
    brazoIzq.write(BRAZO_REPOSO);
    brazoDer.write(180 - BRAZO_REPOSO);  // espejo: brazo derecho montado invertido
}

void actualizarBrazos() {
    if (!animandoBrazos) return;
    unsigned long ahora = millis();
    if (ahora - brazoUltimo < BRAZO_INTERVALO_MS) return;
    brazoUltimo = ahora;

    brazoAng += brazoDir * BRAZO_PASO;
    if (brazoAng >= BRAZO_MAX) { brazoAng = BRAZO_MAX; brazoDir = -1; }
    if (brazoAng <= BRAZO_MIN) { brazoAng = BRAZO_MIN; brazoDir = +1; }

    brazoIzq.write(brazoAng);
    brazoDer.write(180 - brazoAng);      // espejo para gesto simétrico
}

// ── Presencia (2x PIR) ───────────────────────────────────────
// Los PIR los lee el Arduino (antes los leía la Pi). La presencia
// es la OR de ambos: con que UNO detecte movimiento, hay persona.
const uint8_t PIR_DER_PIN = 24;
const uint8_t PIR_IZQ_PIN = 22;

bool presenciaPrev = false;
unsigned long presenciaUltimoLatido = 0;
const unsigned long PRESENCIA_LATIDO_MS = 1000;  // heartbeat a la Pi

void reportarPresencia(bool hay) {
    Serial.print("PRES:");
    Serial.println(hay ? 1 : 0);
}

// Lee los PIR y avisa a la Pi al cambiar de estado + heartbeat 1s.
void actualizarPresencia() {
    bool hay = (digitalRead(PIR_DER_PIN) == HIGH) ||
               (digitalRead(PIR_IZQ_PIN) == HIGH);
    unsigned long ahora = millis();
    if (hay != presenciaPrev || ahora - presenciaUltimoLatido >= PRESENCIA_LATIDO_MS) {
        presenciaPrev = hay;
        presenciaUltimoLatido = ahora;
        reportarPresencia(hay);
    }
}

// ── Ultrasónicos (2x HC-SR04, evasión lateral al maniobrar) ──
const uint8_t TRIG_DER = 29, ECHO_DER = 28;
const uint8_t TRIG_IZQ = 31, ECHO_IZQ = 30;

const float UMBRAL_PARED_CM = 15.0;   // ⚙ ajustar: pared "demasiado cerca"
const unsigned long MEDIR_INTERVALO_MS = 60;  // cada cuánto medir durante un giro
// Timeout del ECHO: ~5ms ≈ 85cm de alcance → acota el bloqueo de pulseIn.
const unsigned long ECHO_TIMEOUT_US = 5000;

unsigned long medirUltimo = 0;

// Distancia en cm con HC-SR04. Bloquea como MUCHO ECHO_TIMEOUT_US.
// Devuelve 999 si no hay eco (fuera de rango / nada cerca).
float medirCm(uint8_t trig, uint8_t echo) {
    digitalWrite(trig, LOW);
    delayMicroseconds(2);
    digitalWrite(trig, HIGH);
    delayMicroseconds(10);
    digitalWrite(trig, LOW);
    unsigned long us = pulseIn(echo, HIGH, ECHO_TIMEOUT_US);
    if (us == 0) return 999.0;       // sin eco dentro del timeout
    return us / 58.0;                // µs → cm (HC-SR04)
}

// Evasión: SOLO se llama mientras hay un giro activo (R/L).
// Si el lateral del lado hacia el que gira está muy cerca, frena.
//   R = gira a la derecha  → vigila el lateral DERECHO
//   L = gira a la izquierda → vigila el lateral IZQUIERDO
// Devuelve true si frenó por pared.
bool evitarPared(char giro) {
    unsigned long ahora = millis();
    if (ahora - medirUltimo < MEDIR_INTERVALO_MS) return false;
    medirUltimo = ahora;

    if (giro == 'R' && medirCm(TRIG_DER, ECHO_DER) < UMBRAL_PARED_CM) {
        detenerTodo();
        Serial.println("WALL:D");
        return true;
    }
    if (giro == 'L' && medirCm(TRIG_IZQ, ECHO_IZQ) < UMBRAL_PARED_CM) {
        detenerTodo();
        Serial.println("WALL:I");
        return true;
    }
    return false;
}

void setup() {
    Serial.begin(9600);

    for (uint8_t i = 0; i < 4; i++) {
        pinMode(MOTOR_PIN[i][0], OUTPUT);
        pinMode(MOTOR_PIN[i][1], OUTPUT);
    }
    detenerTodo();

    pinMode(LED_BUILTIN, OUTPUT);
    led(false);

    brazoIzq.attach(SERVO_IZQ_PIN);
    brazoDer.attach(SERVO_DER_PIN);
    brazosReposo();

    // Presencia (PIR) y ultrasónicos
    pinMode(PIR_DER_PIN, INPUT);
    pinMode(PIR_IZQ_PIN, INPUT);
    pinMode(TRIG_DER, OUTPUT); pinMode(ECHO_DER, INPUT);
    pinMode(TRIG_IZQ, OUTPUT); pinMode(ECHO_IZQ, INPUT);
    digitalWrite(TRIG_DER, LOW);
    digitalWrite(TRIG_IZQ, LOW);

    Serial.println("MEXA firmware listo: 4 motores + 2 brazos + 2 PIR + 2 ultrasonicos");
}

char comandoActivo = 'S';  // último comando de motor (para la evasión)

void loop() {
    actualizarBrazos();     // animación no bloqueante de los brazos
    actualizarPresencia();  // PIR -> "PRES:x" a la Pi

    // Evasión de paredes SOLO mientras hay un giro activo (R/L).
    if (comandoActivo == 'R' || comandoActivo == 'L') {
        if (evitarPared(comandoActivo)) {
            comandoActivo = 'S';  // frenó por pared: cancela el giro
            led(false);
        }
    }

    if (Serial.available() > 0) {
        char cmd = Serial.read();
        switch (cmd) {
            // — Conducir —
            case 'F': ladoIzq(+1); ladoDer(+1); led(true);  comandoActivo='F'; break;  // adelante
            case 'B': ladoIzq(-1); ladoDer(-1); led(true);  comandoActivo='B'; break;  // atrás
            case 'R': ladoIzq(+1); ladoDer(-1); led(true);  comandoActivo='R'; break;  // gira a la derecha
            case 'L': ladoIzq(-1); ladoDer(+1); led(true);  comandoActivo='L'; break;  // gira a la izquierda
            case 'S': detenerTodo();            led(false); comandoActivo='S'; break;  // stop
            // — Identificar un motor —
            case '1': soloMotor(0); led(true); break;
            case '2': soloMotor(1); led(true); break;
            case '3': soloMotor(2); led(true); break;
            case '4': soloMotor(3); led(true); break;
            // — Brazos —
            case 'H': animandoBrazos = true;                   break;  // gesticular al hablar
            case 'P': animandoBrazos = false; brazosReposo();  break;  // volver a reposo
            default:  return;  // '\n', '\r' y otros: no responder
        }
        Serial.print("OK ");
        Serial.println(cmd);
    }
}
