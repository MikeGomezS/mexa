// ============================================================
//  MEXA — Firmware del Arduino (un solo Arduino para todo)
//  ESTADO: 4 motores DC activos. Servos (brazos) PENDIENTES —
//  se agregarán sin librería Servo (timer manual). Por eso este
//  sketch NO incluye Servo.h.
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
//    Brazos:    H / P  -> aceptados pero SIN efecto por ahora
//
//  DIAGNÓSTICO: banner al arrancar + "OK <cmd>" por comando +
//  LED de la placa (pin 13) encendido = hay orden de motor activa.
//
//  ALIMENTACIÓN: VM del driver -> + de la pila ; GND del driver
//  -> - de la pila Y TAMBIÉN al GND del Arduino (tierra común).
// ============================================================

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

void setup() {
    Serial.begin(9600);

    for (uint8_t i = 0; i < 4; i++) {
        pinMode(MOTOR_PIN[i][0], OUTPUT);
        pinMode(MOTOR_PIN[i][1], OUTPUT);
    }
    detenerTodo();

    pinMode(LED_BUILTIN, OUTPUT);
    led(false);

    Serial.println("MEXA firmware 4 motores listo (servos: pendiente)");
}

void loop() {
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        switch (cmd) {
            // — Conducir —
            case 'F': ladoIzq(+1); ladoDer(+1); led(true);  break;  // adelante
            case 'B': ladoIzq(-1); ladoDer(-1); led(true);  break;  // atrás
            case 'R': ladoIzq(+1); ladoDer(-1); led(true);  break;  // gira a la derecha
            case 'L': ladoIzq(-1); ladoDer(+1); led(true);  break;  // gira a la izquierda
            case 'S': detenerTodo();            led(false); break;  // stop
            // — Identificar un motor —
            case '1': soloMotor(0); led(true); break;
            case '2': soloMotor(1); led(true); break;
            case '3': soloMotor(2); led(true); break;
            case '4': soloMotor(3); led(true); break;
            // — Brazos (reservado, sin efecto por ahora) —
            case 'H': break;
            case 'P': break;
            default:  return;  // '\n', '\r' y otros: no responder
        }
        Serial.print("OK ");
        Serial.println(cmd);
    }
}
