/*
  HairBarbot handheld - bench test. Use this BEFORE the main firmware, while wiring one part at a time.
  Same pins as hairbarbot_handheld.ino. Serial Monitor at 115200, line ending "Newline".

  Commands:
    m <steps>   move the guard motor (+ = longer guard). 800 steps = 1 mm. e.g. "m 1600"
    s           print switches: guard home switch, trigger, E-stop
    c / C       clipper relay off / on   (test with the clipper UNPLUGGED first: listen for the click)
    v / V       vacuum relay off / on
    i           print both IMUs (heading/roll/pitch in degrees + calibration 0..3) 10 times
    t           read the distance sensor 10 times
*/
#include <Wire.h>
#include <AccelStepper.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <VL53L1X.h>

const uint8_t PIN_STEP = 25, PIN_DIR = 26, PIN_EN = 27, PIN_LIMIT = 33, PIN_TRIGGER = 32, PIN_ESTOP = 14;
const uint8_t PIN_CLIPPER = 18, PIN_VACUUM = 19;
AccelStepper motor(AccelStepper::DRIVER, PIN_STEP, PIN_DIR);
TwoWire bus1 = TwoWire(1);
Adafruit_BNO055 imuClip(55, 0x28, &Wire), imuHead(56, 0x28, &bus1);
VL53L1X tof;
bool clipOk, headOk, tofOk;
char buf[32]; uint8_t n = 0;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_EN, OUTPUT); digitalWrite(PIN_EN, LOW);
  pinMode(PIN_CLIPPER, OUTPUT); digitalWrite(PIN_CLIPPER, LOW);
  pinMode(PIN_VACUUM, OUTPUT); digitalWrite(PIN_VACUUM, LOW);
  pinMode(PIN_LIMIT, INPUT_PULLUP); pinMode(PIN_TRIGGER, INPUT_PULLUP); pinMode(PIN_ESTOP, INPUT_PULLUP);
  motor.setMaxSpeed(4000); motor.setAcceleration(20000);
  Wire.begin(21, 22, 400000); bus1.begin(16, 17, 100000);
  clipOk = imuClip.begin(); headOk = imuHead.begin();
  tof.setBus(&Wire); tof.setTimeout(100); tofOk = tof.init();
  if (tofOk) tof.startContinuous(50);
  Serial.printf("Bench test ready. Clipper IMU %s, head IMU %s, ToF %s\n",
                clipOk ? "OK" : "NOT FOUND", headOk ? "OK" : "NOT FOUND", tofOk ? "OK" : "NOT FOUND");
}

void printImu(Adafruit_BNO055& imu, const char* name) {
  sensors_event_t e; imu.getEvent(&e);
  uint8_t sys, g, a, m; imu.getCalibration(&sys, &g, &a, &m);
  Serial.printf("%s  heading %6.1f  roll %6.1f  pitch %6.1f   calib sys%d gyro%d acc%d mag%d\n",
                name, e.orientation.x, e.orientation.y, e.orientation.z, sys, g, a, m);
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
      for (int k = 0; k < 10; k++) {
        if (clipOk) printImu(imuClip, "clipper"); else Serial.println("clipper IMU not found");
        if (headOk) printImu(imuHead, "head   "); else Serial.println("head IMU not found");
        delay(200);
      }
      break;
    case 't':
      if (!tofOk) { Serial.println("ToF not found"); break; }
      for (int k = 0; k < 10; k++) { Serial.printf("%d mm\n", tof.read()); delay(100); }
      break;
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
