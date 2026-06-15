// MEXA — Control de Brazos
// Timer1 Normal Mode + ISR: genera pulsos de servo en cualquier pin digital.
// Protocolo serial: 'H' = animar, 'P' = parar

#include <avr/io.h>
#include <avr/interrupt.h>

const uint8_t PIN_IZQ    = 2;
const uint8_t PIN_DER    = 3;
const int     POS_REPOSO = 90;
const int     POS_ARRIBA = 120;
const int     POS_ABAJO  = 60;
const int     INTERVALO_MS = 600;

// Timer1: prescaler 8 → 0.5 µs/tick a 16 MHz
// Grados → ticks:  map(grados, 0, 180, 1088, 4800)
//   0°  = 544 µs  → 1088 ticks
//   90° = 1500 µs → 2944 ticks (aprox)
//   180°= 2400 µs → 4800 ticks
const uint16_t PERIODO_TICKS = 40000; // 20 ms

volatile uint16_t pulse_izq = 2944;
volatile uint16_t pulse_der = 2944;
volatile uint8_t  isr_state = 0;

ISR(TIMER1_COMPA_vect) {
    uint16_t ahora = TCNT1;
    switch (isr_state) {
        case 0:
            digitalWrite(PIN_IZQ, HIGH);
            OCR1A     = ahora + pulse_izq;
            isr_state = 1;
            break;
        case 1:
            digitalWrite(PIN_IZQ, LOW);
            digitalWrite(PIN_DER, HIGH);
            OCR1A     = ahora + pulse_der;
            isr_state = 2;
            break;
        case 2: {
            digitalWrite(PIN_DER, LOW);
            uint16_t usado = pulse_izq + pulse_der;
            OCR1A     = ahora + (PERIODO_TICKS > usado ? PERIODO_TICKS - usado : 200);
            isr_state = 0;
            break;
        }
    }
}

inline uint16_t gradosATicks(int grados) {
    return (uint16_t)map(grados, 0, 180, 1088, 4800);
}

void moverServos(int grados) {
    uint16_t t = gradosATicks(grados);
    cli(); pulse_izq = t; pulse_der = t; sei();
}

bool animando      = false;
bool brazosArriba  = false;
unsigned long ultimoMov = 0;

void setup() {
    Serial.begin(9600);
    pinMode(PIN_IZQ, OUTPUT);
    pinMode(PIN_DER, OUTPUT);

    // Timer1: modo Normal, prescaler 8, interrupciones por OCR1A
    TCCR1A = 0;
    TCCR1B = (1 << CS11);
    TIMSK1 = (1 << OCIE1A);
    TCNT1  = 0;
    OCR1A  = PERIODO_TICKS;
    sei();

    moverServos(POS_REPOSO);
}

void loop() {
    if (Serial.available() > 0) {
        char cmd = Serial.read();
        while (Serial.available()) Serial.read();
        if (cmd == 'H') {
            animando = true;
        } else if (cmd == 'P') {
            animando = false;
            moverServos(POS_REPOSO);
        }
    }

    if (animando && millis() - ultimoMov >= INTERVALO_MS) {
        ultimoMov    = millis();
        brazosArriba = !brazosArriba;
        moverServos(brazosArriba ? POS_ARRIBA : POS_ABAJO);
    }
}
