/*
  HairBarbot cutter - bench test (XIAO ESP32-S3). Use this BEFORE the main firmware, while wiring one part
  at a time. Same pins as hairbarbot_handheld.ino (screw-drive build). Serial Monitor 115200, "Newline".

  Commands:
    m <pwm> <ms>  run the guard motor, e.g. "m 150 500" (longer) or "m -150 500" (shorter), then brake.
                  Prints encoder counts: use it to find COUNTS_PER_MM (measure the guard with calipers)
                  and PWM_MIN (lowest PWM that still moves it).
    s             print switches: home switch, trigger, E-stop
    f             print both force pads for 5 s (in the air, resting on a head, pressed). Pick FSR_ON / FSR_OFF.
    i             print the IMU quaternion 10 times
    c / C         clipper relay off / on   (test with the clipper UNPLUGGED first: listen for the click)
*/
#include <Wire.h>
#include <Adafruit_BNO08x.h>

const int PIN_FSR_A = A0, PIN_FSR_B = A1, PIN_SDA = D4, PIN_SCL = D5;
const int PIN_TRIGGER = D8, PIN_ESTOP = D9, PIN_CLIPPER = D10;
const int PIN_HOME = D2, PIN_ENC_A = D3, PIN_MOT_1 = D6, PIN_MOT_2 = D7;

Adafruit_BNO08x bno(-1);
sh2_SensorValue_t v;
bool imuOk;
volatile long enc = 0;
volatile int8_t dir = 0;
char buf[32]; uint8_t n = 0;

void IRAM_ATTR encISR() { enc += dir; }

void motor(int pwm) {
  dir = (pwm > 0) - (pwm < 0);
  if (pwm > 0)      { analogWrite(PIN_MOT_1, pwm); analogWrite(PIN_MOT_2, 0); }
  else if (pwm < 0) { analogWrite(PIN_MOT_1, 0);   analogWrite(PIN_MOT_2, -pwm); }
  else              { analogWrite(PIN_MOT_1, 255); analogWrite(PIN_MOT_2, 255); }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_CLIPPER, OUTPUT); digitalWrite(PIN_CLIPPER, LOW);
  pinMode(PIN_MOT_1, OUTPUT); pinMode(PIN_MOT_2, OUTPUT); motor(0);
  pinMode(PIN_HOME, INPUT_PULLUP); pinMode(PIN_TRIGGER, INPUT_PULLUP); pinMode(PIN_ESTOP, INPUT_PULLUP);
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encISR, RISING);
  analogReadResolution(12);
  Wire.begin(PIN_SDA, PIN_SCL, 400000);
  imuOk = bno.begin_I2C(0x4A, &Wire);
  if (imuOk) bno.enableReport(SH2_GAME_ROTATION_VECTOR, 10000);
  Serial.println(imuOk ? "IMU found" : "IMU NOT found: check SDA/SCL, 3V3, and address 0x4A");
  Serial.println("bench test ready: m <pwm> <ms>, s, f, i, c, C");
}

void run(char* line) {
  char* cmd = strtok(line, " ");
  if (!cmd) return;
  if (cmd[0] == 'm') {
    char* a = strtok(NULL, " "); char* b = strtok(NULL, " ");
    int pwm = a ? atoi(a) : 150; int ms = b ? atoi(b) : 300;
    long e0 = enc;
    motor(pwm); delay(ms); motor(0); delay(50);
    Serial.printf("encoder %ld -> %ld (%+ld counts)\n", e0, enc, enc - e0);
  } else if (cmd[0] == 's') {
    Serial.printf("home %s  trigger %s  estop %s\n", digitalRead(PIN_HOME) == LOW ? "PRESSED" : "open",
                  digitalRead(PIN_TRIGGER) == LOW ? "HELD" : "released",
                  digitalRead(PIN_ESTOP) == LOW ? "ok" : "PRESSED/OPEN");
  } else if (cmd[0] == 'f') {
    for (int k = 0; k < 50; k++) {
      Serial.printf("pad A %4d   pad B %4d\n", analogRead(PIN_FSR_A), analogRead(PIN_FSR_B));
      delay(100);
    }
  } else if (cmd[0] == 'i') {
    int got = 0;
    unsigned long t0 = millis();
    while (got < 10 && millis() - t0 < 3000) {
      if (imuOk && bno.getSensorEvent(&v) && v.sensorId == SH2_GAME_ROTATION_VECTOR) {
        Serial.printf("q w %.3f x %.3f y %.3f z %.3f\n", v.un.gameRotationVector.real, v.un.gameRotationVector.i,
                      v.un.gameRotationVector.j, v.un.gameRotationVector.k);
        got++;
        delay(100);
      }
    }
    if (!got) Serial.println("no IMU data");
  } else if (cmd[0] == 'c') {
    digitalWrite(PIN_CLIPPER, LOW); Serial.println("clipper relay OFF");
  } else if (cmd[0] == 'C') {
    digitalWrite(PIN_CLIPPER, HIGH); Serial.println("clipper relay ON");
  } else {
    Serial.println("unknown");
  }
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') { buf[n] = 0; run(buf); n = 0; }
    else if (n < sizeof(buf) - 1) buf[n++] = c;
  }
}
