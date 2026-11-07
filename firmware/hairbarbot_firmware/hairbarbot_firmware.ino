/*
  HairBarbot robotic haircutter - firmware for Arduino Mega 2560
  =========================================================
  Drives 4 stepper axes (TMC2209 drivers in standalone STEP/DIR mode, 8 microsteps),
  reads 2x VL53L1X time-of-flight sensors, the E-stop, 4 homing switches, and
  switches the clipper + vacuum through relays.

  Axes (all positions in "machine units"):
    YAW    degrees  rotation of the turntable around the vertical axis through head center
                    0 = facing the client's face, +90 = client's LEFT side, +/-180 = back of head
    PITCH  degrees  carriage position along the arc. 0 = crown (top), 90 = ear level, 105 = nape
    RAD    mm       radial slide. 0 = fully retracted (away from head), larger = closer to head
    GUARD  mm       guard (comb) length = hair length left after cutting. 3..40 mm

  Libraries (install with Arduino Library Manager):
    - AccelStepper by Mike McCauley
    - VL53L1X by Pololu

  Serial protocol: 115200 baud, one command per line ('\n' terminated)
    PC -> board
      P                         heartbeat (send every 100 ms; any line counts)
      H                         home all axes (blocking, replies HOMED + DONE)
      M yaw pitch rad guard f   coordinated move, f = feed % of max speed (1..100). Replies OK, later DONE
      C 1 | C 0                 clipper on/off (refused with ERR if not safe)
      V 1 | V 0                 vacuum on/off
      S                         stop now (fault stop: clipper off, radial retracts)
      R                         reset fault (only if E-stop released)
      ?                         print one status line
    board -> PC
      ST yaw pitch rad guard tof1 tof2 state flags     (10 Hz)
         state: 0 BOOT(not homed) 1 HOMING 2 IDLE 3 MOVING 4 FAULT
         flags: 1 homed, 2 clipper on, 4 vacuum on, 8 E-stop OK, 16 ToF OK
      OK | DONE | HOMED | ERR <text> | FAULT <reason>

  SAFETY LAYERS IN THIS FILE (the PC software adds more on top):
    1. E-stop: hardware cuts clipper power directly (see wiring). This board ALSO sees it on
       pin 2 (interrupt) and turns the clipper relay off + retracts the radial axis.
    2. Heartbeat: if the PC goes silent for 400 ms while moving or cutting -> fault.
    3. Forbidden zones (face, ears): clipper cannot be on there, checked every loop.
    4. Soft limits on every axis + limit switches outside homing -> fault.
    5. ToF "too close" check: if the head is closer to the sensors than the comb tip
       should allow, something is pressing into the head -> fault.
    6. Fault always: clipper OFF, other axes stop, radial axis retracts away from head.
*/

#include <Wire.h>
#include <AccelStepper.h>
#include <VL53L1X.h>

// ---------------------------------------------------------------- Pins
const uint8_t PIN_ESTOP       = 2;   // E-stop 2nd NC contact -> GND. LOW = OK, HIGH = pressed / wire broken
const uint8_t PIN_EN          = 30;  // EN of all 4 drivers, LOW = enabled
const uint8_t PIN_CLIPPER     = 40;  // relay module IN (HIGH = clipper ON)
const uint8_t PIN_VACUUM      = 41;  // relay module IN (HIGH = vacuum ON)
const uint8_t PIN_LED_OK      = 42;
const uint8_t PIN_LED_FAULT   = 43;
const uint8_t PIN_BUZZER      = 44;
const uint8_t PIN_TOF1_XSHUT  = 45;
const uint8_t PIN_TOF2_XSHUT  = 46;
// Limit switches: normally-open microswitch to GND, INPUT_PULLUP. Pressed = LOW.
const uint8_t PIN_LIM_YAW = 31, PIN_LIM_PITCH = 32, PIN_LIM_RAD = 33, PIN_LIM_GUARD = 34;

// If your relay module is "active LOW" (many cheap ones are), set this to true.
const bool RELAY_ACTIVE_LOW = false;

// ---------------------------------------------------------------- Tunables
const unsigned long HEARTBEAT_MS   = 400;
const unsigned long STATUS_MS      = 100;
const float  ZONE_MARGIN_DEG       = 5.0;   // firmware zone is a bit wider than the planner's
const float  RETRACT_SPEED_MM_S    = 8.0;
const bool   TOF_REQUIRED          = true;  // clipper refused if ToF sensors did not start
const int    TOF_MIN_MM            = 12;    // closer than this = pressing into head -> fault
                                            // (sensors sit ~25 mm behind the comb tip; tune on the bench)

// ---------------------------------------------------------------- Steppers
AccelStepper mYaw  (AccelStepper::DRIVER, 22, 23);
AccelStepper mPitch(AccelStepper::DRIVER, 24, 25);
AccelStepper mRad  (AccelStepper::DRIVER, 26, 27);
AccelStepper mGuard(AccelStepper::DRIVER, 28, 29);

struct Axis {
  const char*   name;
  AccelStepper* m;
  float spu;        // steps per unit (deg or mm)
  float minU, maxU; // soft limits
  float homeU;      // position value at the home switch
  int8_t homeDir;   // direction to move to find the switch (-1 / +1)
  float vmax;       // max speed, units/s
  float homeSpeed;  // homing speed, units/s
  uint8_t limitPin;
  float parkU;      // where to go after homing
};

enum { YAW = 0, PITCH, RAD, GUARD, NAX };

// steps/unit with 1600 steps/rev (200-step motor, 8 microsteps):
//   YAW:   20T pulley -> 150T laser-cut pulley (7.5:1)  : 1600*7.5/360   = 33.333 steps/deg
//   PITCH: 20T GT2 pinion crawling a belt on R=250 mm arc: 40 steps/mm * 4.3633 mm/deg = 174.53 steps/deg
//   RAD:   T8 lead screw, 8 mm lead                       : 1600/8 = 200 steps/mm
//   GUARD: lead screw, 2 mm lead                          : 1600/2 = 800 steps/mm
Axis ax[NAX] = {
  // name    motor    spu      min    max    home   dir  vmax  homeV pin            park
  {"yaw",   &mYaw,    33.333, -170,  170,  -175,   -1,  30,   10,  PIN_LIM_YAW,    0},
  {"pitch", &mPitch,  174.53, -12,   112,  -15,    -1,  15,   5,   PIN_LIM_PITCH,  0},
  {"rad",   &mRad,    200.0,   0,    110,  -3,     -1,  10,   4,   PIN_LIM_RAD,    0},
  {"guard", &mGuard,  800.0,   3,    40,    42,    +1,  4,    2,   PIN_LIM_GUARD,  40},
};

// ---------------------------------------------------------------- State
enum { ST_BOOT = 0, ST_HOMING, ST_IDLE, ST_MOVING, ST_FAULT };
uint8_t state = ST_BOOT;
bool homed = false, clipperOn = false, vacuumOn = false;
volatile bool estopTripped = false;
unsigned long lastRxMs = 0, lastStatusMs = 0;

VL53L1X tof1, tof2;
bool tofOk = false;
int tofMm[2] = {0, 0};

char rxBuf[64];
uint8_t rxLen = 0;

// ---------------------------------------------------------------- Helpers
float pos(uint8_t i) { return ax[i].m->currentPosition() / ax[i].spu; }
bool estopOk() { return digitalRead(PIN_ESTOP) == LOW; }

void relay(uint8_t pin, bool on) { digitalWrite(pin, (on ^ RELAY_ACTIVE_LOW) ? HIGH : LOW); }

void setClipper(bool on) { clipperOn = on; relay(PIN_CLIPPER, on); }
void setVacuum(bool on)  { vacuumOn = on;  relay(PIN_VACUUM, on); }

// Highest pitch the cutter may reach at a given yaw (same table as pc/kinematics.py max_pitch)
float maxPitch(float yaw) {
  float a = fabs(yaw);
  if (a <= 50)  return 55;   // forehead hairline
  if (a <= 70)  return 70;   // temples
  if (a <= 115) return 75;   // above the ear
  if (a <= 135) return 90;   // behind the ear
  return 105;                // back of head / nape
}

void estopISR() {
  // Runs instantly when the E-stop opens. Hardware already cut the clipper; do it here too.
  digitalWrite(PIN_CLIPPER, RELAY_ACTIVE_LOW ? HIGH : LOW);
  estopTripped = true;
}

void beep(int ms) { digitalWrite(PIN_BUZZER, HIGH); delay(ms); digitalWrite(PIN_BUZZER, LOW); }

// ---------------------------------------------------------------- Fault handling
void fault(const char* why) {
  setClipper(false);
  setVacuum(false);
  for (uint8_t i = 0; i < NAX; i++) {
    if (i == RAD) continue;
    ax[i].m->moveTo(ax[i].m->currentPosition());
    ax[i].m->setSpeed(0);
  }
  if (homed) {   // retract radial axis away from the head
    long cur = mRad.currentPosition();
    mRad.moveTo(0);
    mRad.setSpeed(cur > 0 ? -RETRACT_SPEED_MM_S * ax[RAD].spu : 0);
  }
  if (state != ST_FAULT) {
    state = ST_FAULT;
    Serial.print(F("FAULT "));
    Serial.println(why);
    digitalWrite(PIN_LED_FAULT, HIGH);
    digitalWrite(PIN_LED_OK, LOW);
    digitalWrite(PIN_BUZZER, HIGH);
  }
}

bool clipperAllowed(const char** why) {
  if (!homed)                           { *why = "not homed"; return false; }
  if (state == ST_FAULT || state == ST_HOMING) { *why = "fault/homing"; return false; }
  if (!estopOk())                       { *why = "estop"; return false; }
  if (TOF_REQUIRED && !tofOk)           { *why = "tof not ok"; return false; }
  if (pos(PITCH) > maxPitch(pos(YAW)) + ZONE_MARGIN_DEG) { *why = "forbidden zone"; return false; }
  if (pos(GUARD) < ax[GUARD].minU - 0.2) { *why = "guard too short"; return false; }
  return true;
}

// ---------------------------------------------------------------- ToF
// XSHUT on the Pololu boards is a 2.8 V pin: never drive it HIGH from the 5 V Mega.
// Hold it LOW to keep a sensor off, switch the pin to INPUT (floating) to let it turn on.
void tofShutdown(uint8_t pin) { pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
void tofRelease(uint8_t pin)  { pinMode(pin, INPUT); }

void initTof() {
  tofShutdown(PIN_TOF1_XSHUT);
  tofShutdown(PIN_TOF2_XSHUT);
  delay(10);
  bool ok = true;
  // sensor 1 -> new address 0x30
  tofRelease(PIN_TOF1_XSHUT); delay(10);
  tof1.setTimeout(100);
  if (tof1.init()) { tof1.setAddress(0x30); } else ok = false;
  // sensor 2 -> default 0x29
  tofRelease(PIN_TOF2_XSHUT); delay(10);
  tof2.setTimeout(100);
  if (!tof2.init()) ok = false;
  if (ok) {
    tof1.setDistanceMode(VL53L1X::Short); tof1.setMeasurementTimingBudget(33000); tof1.startContinuous(40);
    tof2.setDistanceMode(VL53L1X::Short); tof2.setMeasurementTimingBudget(33000); tof2.startContinuous(40);
  }
  tofOk = ok;
  if (!ok) Serial.println(F("ERR tof init failed"));
}

void pollTof() {
  if (!tofOk) return;
  if (tof1.dataReady()) tofMm[0] = tof1.read(false);
  if (tof2.dataReady()) tofMm[1] = tof2.read(false);
  if (clipperOn) {
    for (uint8_t k = 0; k < 2; k++)
      if (tofMm[k] > 0 && tofMm[k] < TOF_MIN_MM) { fault("TOO_CLOSE"); return; }
  }
}

// ---------------------------------------------------------------- Motion
void stopAll() { for (uint8_t i = 0; i < NAX; i++) { ax[i].m->moveTo(ax[i].m->currentPosition()); ax[i].m->setSpeed(0); } }

bool startMove(const float u[NAX], float feed) {
  if (feed < 1) feed = 1;
  if (feed > 100) feed = 100;
  long tgt[NAX];
  float dur = 0;
  for (uint8_t i = 0; i < NAX; i++) {
    if (u[i] < ax[i].minU - 0.01 || u[i] > ax[i].maxU + 0.01) {
      Serial.print(F("ERR limit ")); Serial.println(ax[i].name);
      return false;
    }
    tgt[i] = lround(u[i] * ax[i].spu);
    long d = labs(tgt[i] - ax[i].m->currentPosition());
    float t = d / (ax[i].vmax * ax[i].spu * feed / 100.0);
    if (t > dur) dur = t;
  }
  if (dur < 0.001) { Serial.println(F("OK")); Serial.println(F("DONE")); return true; }
  for (uint8_t i = 0; i < NAX; i++) {
    long d = tgt[i] - ax[i].m->currentPosition();
    ax[i].m->moveTo(tgt[i]);
    ax[i].m->setSpeed(d / dur);   // all axes finish together (coordinated, constant speed)
  }
  state = ST_MOVING;
  Serial.println(F("OK"));
  return true;
}

// Handles serial while blocked in homing: only S (stop) does anything.
bool serviceSerialBlocking() {
  while (Serial.available()) {
    char c = Serial.read();
    lastRxMs = millis();
    if (c == 'S') return false;
  }
  return true;
}

bool homeAxis(uint8_t i) {
  Axis& a = ax[i];
  AccelStepper& m = *a.m;
  m.setMaxSpeed(a.homeSpeed * a.spu * 2);
  m.setSpeed(a.homeDir * a.homeSpeed * a.spu);
  unsigned long t0 = millis();
  while (digitalRead(a.limitPin) == HIGH) {
    if (!estopOk() || estopTripped) return false;
    if (!serviceSerialBlocking()) return false;
    if (millis() - t0 > 60000UL) { Serial.print(F("ERR home timeout ")); Serial.println(a.name); return false; }
    m.runSpeed();
  }
  m.setCurrentPosition(lround(a.homeU * a.spu));
  // back off the switch to the soft limit
  m.setAcceleration(a.homeSpeed * a.spu * 4);
  float off = (a.homeDir < 0) ? a.minU : a.maxU;
  m.runToNewPosition(lround(off * a.spu));
  return true;
}

bool homeAll() {
  state = ST_HOMING;
  homed = false;
  setClipper(false);
  digitalWrite(PIN_EN, LOW);
  // radial first (pull away from the head), then guard, pitch, yaw
  const uint8_t order[NAX] = {RAD, GUARD, PITCH, YAW};
  for (uint8_t k = 0; k < NAX; k++) {
    if (!homeAxis(order[k])) { homed = false; fault("HOME_FAILED"); return false; }
  }
  for (uint8_t k = 0; k < NAX; k++) {   // go to park
    Axis& a = ax[order[k]];
    a.m->setMaxSpeed(a.vmax * a.spu * 0.5);
    a.m->setAcceleration(a.vmax * a.spu);
    a.m->runToNewPosition(lround(a.parkU * a.spu));
  }
  for (uint8_t i = 0; i < NAX; i++) ax[i].m->setMaxSpeed(ax[i].vmax * ax[i].spu);  // restore full speed limit
  homed = true;
  state = ST_IDLE;
  Serial.println(F("HOMED"));
  Serial.println(F("DONE"));
  return true;
}

// ---------------------------------------------------------------- Serial commands
void handleLine(char* line) {
  char* cmd = strtok(line, " ");
  if (!cmd) return;
  switch (cmd[0]) {
    case 'P': break;
    case '?': lastStatusMs = 0; break;
    case 'H':
      if (state == ST_FAULT) { Serial.println(F("ERR reset first")); break; }
      homeAll();
      break;
    case 'M': {
      if (!homed) { Serial.println(F("ERR not homed")); break; }
      if (state == ST_FAULT) { Serial.println(F("ERR fault")); break; }
      if (state == ST_MOVING) { Serial.println(F("ERR busy")); break; }
      float u[NAX];
      for (uint8_t i = 0; i < NAX; i++) { char* t = strtok(NULL, " "); if (!t) { Serial.println(F("ERR args")); return; } u[i] = atof(t); }
      char* f = strtok(NULL, " ");
      startMove(u, f ? atof(f) : 30);
      break;
    }
    case 'C': {
      char* t = strtok(NULL, " ");
      bool on = t && t[0] == '1';
      if (on) {
        const char* why = "";
        if (!clipperAllowed(&why)) { Serial.print(F("ERR clipper ")); Serial.println(why); break; }
      }
      setClipper(on);
      Serial.println(F("OK"));
      break;
    }
    case 'V': {
      char* t = strtok(NULL, " ");
      bool on = t && t[0] == '1';
      if (on && state == ST_FAULT) { Serial.println(F("ERR fault")); break; }
      setVacuum(on);
      Serial.println(F("OK"));
      break;
    }
    case 'S': fault("STOP_CMD"); break;
    case 'R':
      if (!estopOk()) { Serial.println(F("ERR estop still pressed")); break; }
      estopTripped = false;
      stopAll();
      state = homed ? ST_IDLE : ST_BOOT;
      digitalWrite(PIN_LED_FAULT, LOW);
      digitalWrite(PIN_BUZZER, LOW);
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
    else rxLen = 0;   // overflow: drop line
  }
}

void sendStatus() {
  uint8_t flags = (homed ? 1 : 0) | (clipperOn ? 2 : 0) | (vacuumOn ? 4 : 0) | (estopOk() ? 8 : 0) | (tofOk ? 16 : 0);
  Serial.print(F("ST "));
  Serial.print(pos(YAW), 2);   Serial.print(' ');
  Serial.print(pos(PITCH), 2); Serial.print(' ');
  Serial.print(pos(RAD), 2);   Serial.print(' ');
  Serial.print(pos(GUARD), 2); Serial.print(' ');
  Serial.print(tofMm[0]);      Serial.print(' ');
  Serial.print(tofMm[1]);      Serial.print(' ');
  Serial.print(state);         Serial.print(' ');
  Serial.println(flags);
}

// ---------------------------------------------------------------- Setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(PIN_CLIPPER, OUTPUT); pinMode(PIN_VACUUM, OUTPUT);
  setClipper(false); setVacuum(false);
  pinMode(PIN_EN, OUTPUT); digitalWrite(PIN_EN, LOW);   // enabled: holding torque keeps the arm still
  pinMode(PIN_LED_OK, OUTPUT); pinMode(PIN_LED_FAULT, OUTPUT); pinMode(PIN_BUZZER, OUTPUT);
  pinMode(PIN_ESTOP, INPUT_PULLUP);
  pinMode(PIN_LIM_YAW, INPUT_PULLUP); pinMode(PIN_LIM_PITCH, INPUT_PULLUP);
  pinMode(PIN_LIM_RAD, INPUT_PULLUP); pinMode(PIN_LIM_GUARD, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ESTOP), estopISR, RISING);
  for (uint8_t i = 0; i < NAX; i++) ax[i].m->setMaxSpeed(ax[i].vmax * ax[i].spu);
  Wire.begin();
  Wire.setClock(400000);
  initTof();
  beep(80);
  Serial.println(F("HairBarbot ready - send H to home"));
}

void loop() {
  pollSerial();

  // 1. E-stop
  if (state != ST_FAULT && (estopTripped || !estopOk())) fault("ESTOP");

  // 2. heartbeat
  if (state != ST_FAULT && (clipperOn || state == ST_MOVING) && millis() - lastRxMs > HEARTBEAT_MS) fault("HEARTBEAT");

  // 3. forbidden zone / interlocks while cutting
  if (clipperOn) {
    const char* why = "";
    if (!clipperAllowed(&why)) fault(why);
  }

  // 4. limit switches outside homing
  if (homed && state != ST_HOMING && state != ST_FAULT) {
    for (uint8_t i = 0; i < NAX; i++)
      if (digitalRead(ax[i].limitPin) == LOW) { fault("LIMIT_SWITCH"); break; }
  }

  // 5. motion
  if (state == ST_MOVING) {
    bool busy = false;
    for (uint8_t i = 0; i < NAX; i++) { ax[i].m->runSpeedToPosition(); if (ax[i].m->distanceToGo() != 0) busy = true; }
    if (!busy) { state = ST_IDLE; Serial.println(F("DONE")); }
  } else if (state == ST_FAULT) {
    mRad.runSpeedToPosition();   // keep retracting
  }

  pollTof();

  digitalWrite(PIN_LED_OK, (homed && state != ST_FAULT) ? HIGH : LOW);
  if (millis() - lastStatusMs >= STATUS_MS) { lastStatusMs = millis(); sendStatus(); }
}
