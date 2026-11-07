/*
  HairBarbot bench test - use this BEFORE the main firmware, while you wire things up one at a time.
  Same pins as hairbarbot_firmware.ino. Open Serial Monitor at 115200, line ending "Newline".

  Commands:
    1..4 <steps>   spin motor 1=yaw 2=pitch 3=rad 4=guard by <steps> (negative = reverse), e.g. "3 1600"
    s              print all switches (limit switches + E-stop)
    c / C          clipper relay off / on        (test with the clipper UNPLUGGED first: listen for the click)
    v / V          vacuum relay off / on
    t              read both ToF sensors 10 times
    e / E          drivers disabled / enabled
  Tip: check each motor's direction. +steps must move: yaw -> client's left, pitch -> down toward the
  nape, rad -> toward the head, guard -> longer. If one is backwards, swap one coil pair on that motor.
*/
#include <Wire.h>
#include <AccelStepper.h>
#include <VL53L1X.h>

AccelStepper m[4] = {
  AccelStepper(AccelStepper::DRIVER, 22, 23), AccelStepper(AccelStepper::DRIVER, 24, 25),
  AccelStepper(AccelStepper::DRIVER, 26, 27), AccelStepper(AccelStepper::DRIVER, 28, 29)};
const char* names[4] = {"yaw", "pitch", "rad", "guard"};
const uint8_t LIM[4] = {31, 32, 33, 34};
const uint8_t PIN_ESTOP = 2, PIN_EN = 30, PIN_CLIPPER = 40, PIN_VACUUM = 41, XS1 = 45, XS2 = 46;
VL53L1X tof1, tof2;
bool tofOk = false;
char buf[32]; uint8_t n = 0;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_EN, OUTPUT); digitalWrite(PIN_EN, LOW);
  pinMode(PIN_CLIPPER, OUTPUT); digitalWrite(PIN_CLIPPER, LOW);
  pinMode(PIN_VACUUM, OUTPUT); digitalWrite(PIN_VACUUM, LOW);
  pinMode(PIN_ESTOP, INPUT_PULLUP);
  for (int i = 0; i < 4; i++) { pinMode(LIM[i], INPUT_PULLUP); m[i].setMaxSpeed(1500); m[i].setAcceleration(3000); }
  Wire.begin();
  // XSHUT is 2.8 V: hold LOW to keep off, set to INPUT to release (never drive HIGH)
  pinMode(XS1, OUTPUT); pinMode(XS2, OUTPUT); digitalWrite(XS1, LOW); digitalWrite(XS2, LOW); delay(10);
  pinMode(XS1, INPUT); delay(10); tof1.setTimeout(100);
  bool a = tof1.init(); if (a) tof1.setAddress(0x30);
  pinMode(XS2, INPUT); delay(10); tof2.setTimeout(100);
  bool b = tof2.init();
  tofOk = a && b;
  if (tofOk) { tof1.startContinuous(50); tof2.startContinuous(50); }
  Serial.print(F("Bench test ready. ToF: ")); Serial.println(tofOk ? F("OK") : F("NOT FOUND"));
}

void run(char* line) {
  char c = line[0];
  if (c >= '1' && c <= '4') {
    int i = c - '1';
    long steps = atol(line + 1);
    Serial.print(F("moving ")); Serial.print(names[i]); Serial.print(' '); Serial.println(steps);
    m[i].move(steps);
    while (m[i].distanceToGo() != 0) {
      if (digitalRead(PIN_ESTOP) == HIGH) { m[i].stop(); Serial.println(F("E-STOP!")); break; }
      m[i].run();
    }
    m[i].setCurrentPosition(0);
  } else if (c == 's') {
    for (int i = 0; i < 4; i++) { Serial.print(names[i]); Serial.print(digitalRead(LIM[i]) == LOW ? F(":PRESSED ") : F(":open ")); }
    Serial.print(F(" E-stop:")); Serial.println(digitalRead(PIN_ESTOP) == LOW ? F("released(OK)") : F("PRESSED/OPEN"));
  } else if (c == 'c' || c == 'C') { digitalWrite(PIN_CLIPPER, c == 'C'); Serial.println(c == 'C' ? F("clipper ON") : F("clipper off")); }
  else if (c == 'v' || c == 'V') { digitalWrite(PIN_VACUUM, c == 'V'); Serial.println(c == 'V' ? F("vacuum ON") : F("vacuum off")); }
  else if (c == 'e' || c == 'E') { digitalWrite(PIN_EN, c == 'E' ? LOW : HIGH); Serial.println(c == 'E' ? F("drivers enabled") : F("drivers disabled")); }
  else if (c == 't') {
    if (!tofOk) { Serial.println(F("ToF not found - check wiring/XSHUT")); return; }
    for (int k = 0; k < 10; k++) { Serial.print(tof1.read()); Serial.print(F(" mm   ")); Serial.print(tof2.read()); Serial.println(F(" mm")); }
  } else Serial.println(F("?"));
}

void loop() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') { buf[n] = 0; if (n) run(buf); n = 0; }
    else if (n < sizeof(buf) - 1) buf[n++] = ch;
  }
}
