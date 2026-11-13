/*
  HairBarbot handheld - firmware for an ESP32 DevKit (Arduino core)
  ==================================================================
  Fully handheld: no headband. The user presses the HairBarbot head against their scalp.
  Two small ROLLERS on a carriage touch the scalp. A lead-screw stepper moves that carriage,
  which sets how far the blade is from the scalp = how long the hair is left (3..60 mm).
  One roller has a magnet + AS5600 encoder, so we also know how far the device has rolled.

  This board:
    - drives the guard stepper (TMC2209, STEP/DIR, 8 microsteps) and homes it on a switch
    - reads one BNO055 orientation sensor on the device (which way it points / is tilted)
    - reads the AS5600 roller encoder (distance rolled along the head)
    - reads the trigger button on the handle and the E-stop
    - switches the clipper and vacuum through relays
  The laptop works out WHERE on the head the device is and what length that spot needs.

  Libraries (Arduino Library Manager): AccelStepper (Mike McCauley), Adafruit BNO055,
  Adafruit Unified Sensor. Board: "ESP32 Dev Module". (The AS5600 is read directly over I2C.)

  Serial: 115200 baud, one command per line
    PC -> board
      P            heartbeat (any line counts)
      H            home the guard (blocking, replies HOMED + DONE)
      G <mm>       guard target length, 3..60 mm (ignored until homed)
      C 1 | C 0    clipper permit. "C 1" is a LEASE: re-send at least every 150 ms or the clipper turns off.
                   The clipper also needs the trigger held.
      V 1 | V 0    vacuum on/off
      Z            zero the rolled distance
      S            stop now (fault: clipper + vacuum off, guard goes to its longest length)
      R            reset fault (only if the E-stop is released)
      ?            print one status line now
    board -> PC (50 Hz)
      ST qw qx qy qz rolled guard target state flags
         qw..qz = device orientation quaternion (BNO055 fused, world frame)
         rolled = distance rolled since the last Z, in mm (signed)
         state  : 0 NOT_HOMED, 1 HOMING, 2 READY, 4 FAULT
         flags  : 1 homed, 2 clipper on, 4 vacuum on, 8 E-stop OK, 16 encoder OK,
                  32 IMU OK, 64 trigger held, 128 permit active
      OK | DONE | HOMED | ERR <text> | FAULT <reason>

  SAFETY LAYERS IN THIS FILE (the laptop adds "wrong spot" and face/ear checks on top):
    1. E-stop: hardware cuts clipper power directly (wiring). This board also sees it (pin 14).
    2. Trigger (dead-man): clipper runs only while the trigger is held. Wire its second contact
       in series with the clipper relay too, so this works even if the code freezes.
    3. Permit lease: if the laptop stops renewing "C 1" for 150 ms, the clipper turns off.
    4. Guard can't go below 3 mm: soft limit here + printed hard stop on the carriage.
    5. Fault: clipper and vacuum off, guard runs out to its longest length.
*/

#include <Wire.h>
#include <AccelStepper.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>

// ---------------------------------------------------------------- Pins (ESP32 DevKit)
const uint8_t PIN_STEP = 25, PIN_DIR = 26, PIN_EN = 27;
const uint8_t PIN_LIMIT   = 33;  // guard home switch at the LONG end, NO -> GND, pressed = LOW
const uint8_t PIN_TRIGGER = 32;  // handle button, NO -> GND, held = LOW
const uint8_t PIN_ESTOP   = 14;  // E-stop contact B (NC chain to GND). LOW = OK, HIGH = pressed
const uint8_t PIN_CLIPPER = 18;  // relay control (through E-stop contact A and trigger contact 2)
const uint8_t PIN_VACUUM  = 19;
const uint8_t PIN_LED     = 2;   // on-board LED: on = ready, blinking = fault
const uint8_t PIN_BUZZER  = 4;
const uint8_t SDA0 = 21, SCL0 = 22;   // I2C: BNO055 (0x28) + AS5600 (0x36)

const bool RELAY_ACTIVE_LOW = false;   // set true if your relay turns on with a LOW input

// ---------------------------------------------------------------- Tunables
const float GUARD_MIN = 3.0, GUARD_MAX = 60.0, GUARD_HOME = 62.0;
const float STEPS_PER_MM = 800.0;      // 200-step motor, 8 microsteps, 2 mm lead screw
const float GUARD_VMAX = 15.0;         // mm/s
const float GUARD_ACCEL = 80.0;        // mm/s^2
const float HOME_SPEED = 5.0;          // mm/s
const float ROLLER_DIAMETER = 12.0;    // mm, the roller with the magnet (measure yours)
const int   ROLLER_DIR = 1;            // flip to -1 if rolling "up the head" counts negative
const uint8_t AS5600_ADDR = 0x36;
const unsigned long LEASE_MS = 150, STATUS_MS = 20, HEARTBEAT_MS = 400;

// ---------------------------------------------------------------- Objects / state
AccelStepper guard(AccelStepper::DRIVER, PIN_STEP, PIN_DIR);
Adafruit_BNO055 bno(55, 0x28, &Wire);

enum { ST_NOT_HOMED = 0, ST_HOMING = 1, ST_READY = 2, ST_FAULT = 4 };
uint8_t state = ST_NOT_HOMED;
bool homed = false, clipperOn = false, vacuumOn = false, imuOk = false, encOk = false;
volatile bool estopTripped = false;
unsigned long lastRxMs = 0, lastStatusMs = 0, permitUntil = 0;
float targetMm = GUARD_MAX;
imu::Quaternion q(1, 0, 0, 0);
int lastRaw = -1;
long encCounts = 0;                    // unwrapped encoder counts (4096 per roller turn)
char rxBuf[64];
uint8_t rxLen = 0;

// ---------------------------------------------------------------- Helpers
float guardMm() { return guard.currentPosition() / STEPS_PER_MM; }
float rolledMm() { return ROLLER_DIR * encCounts * (PI * ROLLER_DIAMETER / 4096.0); }
bool estopOk() { return digitalRead(PIN_ESTOP) == LOW; }
bool triggerHeld() { return digitalRead(PIN_TRIGGER) == LOW; }
void relay(uint8_t pin, bool on) { digitalWrite(pin, (on ^ RELAY_ACTIVE_LOW) ? HIGH : LOW); }
void setClipper(bool on) { clipperOn = on; relay(PIN_CLIPPER, on); }
void setVacuum(bool on) { vacuumOn = on; relay(PIN_VACUUM, on); }
float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

void IRAM_ATTR estopISR() {
  digitalWrite(PIN_CLIPPER, RELAY_ACTIVE_LOW ? HIGH : LOW);
  estopTripped = true;
}

void fault(const char* why) {
  setClipper(false);
  setVacuum(false);
  permitUntil = 0;
  if (homed) guard.moveTo(lround(GUARD_MAX * STEPS_PER_MM));   // longest guard = safest
  if (state != ST_FAULT) {
    state = ST_FAULT;
    Serial.print(F("FAULT "));
    Serial.println(why);
    digitalWrite(PIN_BUZZER, HIGH);
  }
}

// ---------------------------------------------------------------- AS5600 roller encoder
int readAs5600Raw() {
  Wire.beginTransmission(AS5600_ADDR);
  Wire.write(0x0C);                                  // RAW ANGLE register (12 bit)
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom(AS5600_ADDR, (uint8_t)2) != 2) return -1;
  int hi = Wire.read(), lo = Wire.read();
  return ((hi & 0x0F) << 8) | lo;
}

void pollEncoder() {
  int raw = readAs5600Raw();
  if (raw < 0) { encOk = false; return; }
  encOk = true;
  if (lastRaw >= 0) {
    int d = raw - lastRaw;
    if (d > 2048) d -= 4096;                         // unwrap across 0
    if (d < -2048) d += 4096;
    encCounts += d;
  }
  lastRaw = raw;
}

// ---------------------------------------------------------------- Homing (toward the LONG end)
bool homeGuard() {
  state = ST_HOMING;
  homed = false;
  setClipper(false);
  guard.setMaxSpeed(HOME_SPEED * STEPS_PER_MM * 2);
  guard.setSpeed(HOME_SPEED * STEPS_PER_MM);
  unsigned long t0 = millis();
  while (digitalRead(PIN_LIMIT) == HIGH) {
    if (!estopOk()) { fault("ESTOP"); return false; }
    if (Serial.available() && Serial.peek() == 'S') { Serial.read(); fault("STOP_CMD"); return false; }
    if (millis() - t0 > 40000UL) { fault("HOME_TIMEOUT"); return false; }
    guard.runSpeed();
  }
  guard.setCurrentPosition(lround(GUARD_HOME * STEPS_PER_MM));
  guard.setMaxSpeed(GUARD_VMAX * STEPS_PER_MM);
  guard.setAcceleration(GUARD_ACCEL * STEPS_PER_MM);
  guard.runToNewPosition(lround(GUARD_MAX * STEPS_PER_MM));   // back off the switch
  targetMm = GUARD_MAX;
  homed = true;
  state = ST_READY;
  Serial.println(F("HOMED"));
  Serial.println(F("DONE"));
  return true;
}

// ---------------------------------------------------------------- Commands
void handleLine(char* line) {
  char* cmd = strtok(line, " ");
  if (!cmd) return;
  char* arg = strtok(NULL, " ");
  switch (cmd[0]) {
    case 'P': break;
    case '?': lastStatusMs = 0; break;
    case 'H':
      if (state == ST_FAULT) { Serial.println(F("ERR reset first")); break; }
      homeGuard();
      break;
    case 'G':
      if (!homed || state == ST_FAULT) break;      // silently ignored: sent 50x per second
      if (arg) { targetMm = clampf(atof(arg), GUARD_MIN, GUARD_MAX); guard.moveTo(lround(targetMm * STEPS_PER_MM)); }
      break;
    case 'C':
      if (arg && arg[0] == '1') {
        if (homed && state == ST_READY) permitUntil = millis() + LEASE_MS;
      } else {
        permitUntil = 0;
        setClipper(false);
      }
      break;
    case 'V':
      setVacuum(arg && arg[0] == '1' && state != ST_FAULT);
      Serial.println(F("OK"));
      break;
    case 'Z': encCounts = 0; Serial.println(F("OK")); break;
    case 'S': fault("STOP_CMD"); break;
    case 'R':
      if (!estopOk()) { Serial.println(F("ERR estop still pressed")); break; }
      estopTripped = false;
      digitalWrite(PIN_BUZZER, LOW);
      state = homed ? ST_READY : ST_NOT_HOMED;
      Serial.println(F("OK"));
      break;
    default: Serial.println(F("ERR unknown"));
  }
}

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    lastRxMs = millis();
    if (c == '\r') continue;
    if (c == '\n') { rxBuf[rxLen] = 0; handleLine(rxBuf); rxLen = 0; }
    else if (rxLen < sizeof(rxBuf) - 1) rxBuf[rxLen++] = c;
    else rxLen = 0;
  }
}

void sendStatus() {
  bool permit = millis() < permitUntil;
  uint16_t flags = (homed ? 1 : 0) | (clipperOn ? 2 : 0) | (vacuumOn ? 4 : 0) | (estopOk() ? 8 : 0) |
                   (encOk ? 16 : 0) | (imuOk ? 32 : 0) | (triggerHeld() ? 64 : 0) | (permit ? 128 : 0);
  char buf[140];
  snprintf(buf, sizeof(buf), "ST %.4f %.4f %.4f %.4f %.1f %.2f %.2f %u %u",
           q.w(), q.x(), q.y(), q.z(), rolledMm(), guardMm(), targetMm, state, flags);
  Serial.println(buf);
}

// ---------------------------------------------------------------- Setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(PIN_CLIPPER, OUTPUT); pinMode(PIN_VACUUM, OUTPUT);
  setClipper(false); setVacuum(false);
  pinMode(PIN_EN, OUTPUT); digitalWrite(PIN_EN, LOW);
  pinMode(PIN_LED, OUTPUT); pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_LIMIT, INPUT_PULLUP);
  pinMode(PIN_TRIGGER, INPUT_PULLUP);
  pinMode(PIN_ESTOP, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ESTOP), estopISR, RISING);
  guard.setMaxSpeed(GUARD_VMAX * STEPS_PER_MM);
  guard.setAcceleration(GUARD_ACCEL * STEPS_PER_MM);
  Wire.begin(SDA0, SCL0, 400000);
  imuOk = bno.begin(OPERATION_MODE_NDOF);
  if (imuOk) bno.setExtCrystalUse(true);
  else Serial.println(F("ERR IMU not found"));
  if (readAs5600Raw() < 0) Serial.println(F("ERR roller encoder not found"));
  Serial.println(F("HairBarbot handheld ready - send H to home the guard"));
}

unsigned long lastSensorMs = 0;
void loop() {
  pollSerial();
  if (millis() - lastSensorMs >= 10) {              // sensors at 100 Hz
    lastSensorMs = millis();
    if (imuOk) q = bno.getQuat();
    pollEncoder();
  }

  // 1. E-stop
  if (state != ST_FAULT && (estopTripped || !estopOk())) fault("ESTOP");

  // 2. the home switch sits 2 mm past the longest guard length, so after homing it should never
  //    be pressed. If it is, the carriage slipped or a wire is loose.
  if (homed && state == ST_READY && digitalRead(PIN_LIMIT) == LOW) fault("LIMIT_SWITCH");

  // 3. clipper = trigger held AND fresh permit from the laptop AND ready
  bool want = state == ST_READY && triggerHeld() && millis() < permitUntil &&
              millis() - lastRxMs < HEARTBEAT_MS && imuOk;
  if (want != clipperOn) setClipper(want);

  // 4. guard motion (also runs in FAULT so the guard can move out to its longest length)
  if (homed) guard.run();

  // 5. LED: solid = ready, blinking = fault, off = not homed
  digitalWrite(PIN_LED, state == ST_FAULT ? ((millis() / 250) % 2) : (state == ST_READY));

  if (millis() - lastStatusMs >= STATUS_MS) { lastStatusMs = millis(); sendStatus(); }
}
