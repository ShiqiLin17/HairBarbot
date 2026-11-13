/*
  HairBarbot handheld - bench test. Use this BEFORE the main firmware, while wiring one part at a time.
  Same pins as hairbarbot_handheld.ino. Serial Monitor at 115200, line ending "Newline".

  Commands:
    m <steps>   move the guard motor (+ = longer guard). 800 steps = 1 mm. e.g. "m 1600"
    s           print switches: guard home switch, trigger, E-stop
    c / C       clipper relay off / on   (test with the clipper UNPLUGGED first: listen for the click)
    v / V       vacuum relay off / on
    i           print the IMU (heading/roll/pitch in degrees + calibration 0..3) 10 times
    e           print the roller encoder for 5 s: roll the roller by hand and watch the mm change
*/
#include <Wire.h>
#include <AccelStepper.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>

const uint8_t PIN_STEP = 25, PIN_DIR = 26, PIN_EN = 27, PIN_LIMIT = 33, PIN_TRIGGER = 32, PIN_ESTOP = 14;
const uint8_t PIN_CLIPPER = 18, PIN_VACUUM = 19;
const float ROLLER_DIAMETER = 12.0;
AccelStepper motor(AccelStepper::DRIVER, PIN_STEP, PIN_DIR);
Adafruit_BNO055 bno(55, 0x28, &Wire);
bool imuOk;
char buf[32]; uint8_t n = 0;

int readAs5600Raw() {
  Wire.beginTransmission(0x36);
  Wire.write(0x0C);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom((uint8_t)0x36, (uint8_t)2) != 2) return -1;
  int hi = Wire.read(), lo = Wire.read();
  return ((hi & 0x0F) << 8) | lo;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_EN, OUTPUT); digitalWrite(PIN_EN, LOW);
  pinMode(PIN_CLIPPER, OUTPUT); digitalWrite(PIN_CLIPPER, LOW);
  pinMode(PIN_VACUUM, OUTPUT); digitalWrite(PIN_VACUUM, LOW);
  pinMode(PIN_LIMIT, INPUT_PULLUP); pinMode(PIN_TRIGGER, INPUT_PULLUP); pinMode(PIN_ESTOP, INPUT_PULLUP);
  motor.setMaxSpeed(4000); motor.setAcceleration(20000);
  Wire.begin(21, 22, 400000);
  imuOk = bno.begin();
  Serial.printf("Bench test ready. IMU %s, roller encoder %s\n",
                imuOk ? "OK" : "NOT FOUND", readAs5600Raw() >= 0 ? "OK" : "NOT FOUND");
}

void run(char* line) {
  switch (line[0]) {
    case 'm': {
      long steps = atol(line + 1);
      Serial.printf("moving %ld steps\n", steps);
      motor.move(steps);
      while (motor.distanceToGo()) {
        if (digitalRead(PIN_ESTOP) == HIGH) { Serial.println("E-STOP!"); break; }
        motor.run();
      }
      motor.setCurrentPosition(0);
      break;
    }
    case 's':
      Serial.printf("home switch %s   trigger %s   E-stop %s\n",
                    digitalRead(PIN_LIMIT) == LOW ? "PRESSED" : "open",
                    digitalRead(PIN_TRIGGER) == LOW ? "HELD" : "released",
                    digitalRead(PIN_ESTOP) == LOW ? "released (OK)" : "PRESSED / OPEN");
      break;
    case 'c': case 'C': digitalWrite(PIN_CLIPPER, line[0] == 'C'); Serial.println(line[0] == 'C' ? "clipper ON" : "clipper off"); break;
    case 'v': case 'V': digitalWrite(PIN_VACUUM, line[0] == 'V'); Serial.println(line[0] == 'V' ? "vacuum ON" : "vacuum off"); break;
    case 'i':
      if (!imuOk) { Serial.println("IMU not found"); break; }
      for (int k = 0; k < 10; k++) {
        sensors_event_t e; bno.getEvent(&e);
        uint8_t sys, g, a, mg; bno.getCalibration(&sys, &g, &a, &mg);
        Serial.printf("heading %6.1f  roll %6.1f  pitch %6.1f   calib sys%d gyro%d acc%d mag%d\n",
                      e.orientation.x, e.orientation.y, e.orientation.z, sys, g, a, mg);
        delay(200);
      }
      break;
    case 'e': {
      long counts = 0; int last = readAs5600Raw();
      if (last < 0) { Serial.println("encoder not found"); break; }
      unsigned long t0 = millis(), tp = 0;
      while (millis() - t0 < 5000) {
        int raw = readAs5600Raw();
        if (raw >= 0) { int d = raw - last; if (d > 2048) d -= 4096; if (d < -2048) d += 4096; counts += d; last = raw; }
        if (millis() - tp > 200) { tp = millis(); Serial.printf("rolled %.1f mm\n", counts * PI * ROLLER_DIAMETER / 4096.0); }
        delay(5);
      }
      break;
    }
    default: Serial.println("?");
  }
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') { buf[n] = 0; if (n) run(buf); n = 0; }
    else if (n < sizeof(buf) - 1) buf[n++] = c;
  }
}
