/*
  HairBarbot cutter - firmware for the Seeed XIAO ESP32-S3 (Arduino core)
  ========================================================================
  The cutter is a Flowbee with an outer guard that slides on rails (Carlos's design, see
  docs/guard-drive-options.pdf). The user PICKS IT UP AND PLACES IT on the head, spot by spot.
  A small drive moves the outer guard from 1/2" to 1-3/4" (12.7..44.45 mm) = the hair length left.

  This board, in the sensor box on the cutter:
    - drives the guard: D2.2 screw drive (N20 gear motor + encoder + M4 lead screw + home switch), default,
      or the C3/C4 scissor with a hobby servo (set GUARD_DRIVE below)
    - reads the BNO085 IMU (which way the cutter points)
    - reads the two force sensors (FSRs) in the scalp face (is the cutter sitting flat on the head?)
    - reads the trigger and the E-stop, and switches the clipper relay
  The laptop works out WHERE on the head the cutter is (IMU + the camera's view of the ArUco tags)
  and what guard length that spot needs. See docs/cutter-tracking.md.

  Board: "XIAO_ESP32S3" (esp32 by Espressif, core 3.x). Tools > USB CDC On Boot: Enabled.
  Libraries (Library Manager): "Adafruit BNO08x" (+ its dependencies). Servo build only: "ESP32Servo".

  Serial (USB): 115200 baud, one command per line
    PC -> board
      P            heartbeat (any line counts)
      H            home the guard (screw drive: runs to the home switch; replies HOMED + DONE)
      G <mm>       guard target length, 12.7..44.45 mm (ignored until homed)
      C 1 | C 0    clipper permit. "C 1" is a LEASE: re-send at least every 150 ms or the clipper turns off.
                   The clipper also needs the trigger held AND both force pads pressed.
      V 1 | V 0    vacuum relay on/off (only if PIN_VACUUM is wired, see pins)
      S            stop now (fault: clipper off, guard goes to its longest length)
      R            reset fault (only if the E-stop is released)
      ?            print one status line now
    board -> PC (50 Hz)
      ST qw qx qy qz fsrA fsrB guard target state flags
         qw..qz    = cutter orientation quaternion (BNO085 game rotation vector: no compass, so the motor's
                     magnet can't disturb it; its slow heading drift is corrected by the camera's tag sightings)
         fsrA fsrB = force pads, raw ADC 0..4095 (higher = pressed harder)
         state     : 0 NOT_HOMED, 1 HOMING, 2 READY, 4 FAULT
         flags     : 1 homed, 2 clipper on, 4 vacuum on, 8 E-stop OK, 16 guard drive OK,
                     32 IMU OK, 64 trigger held, 128 permit active
      OK | DONE | HOMED | ERR <text> | FAULT <reason>

  SAFETY LAYERS IN THIS FILE (the laptop adds "wrong spot", face/ear and tags-vs-IMU checks on top):
    1. E-stop: hardware cuts clipper power directly (wiring). This board also sees it.
    2. Trigger (dead-man): clipper runs only while the trigger is held. Wire its second contact
       in series with the clipper relay too, so this works even if the code freezes.
    3. Permit lease: if the laptop stops renewing "C 1" for 150 ms, the clipper turns off.
    4. Force pads: clipper runs only while BOTH pads are pressed (cutter on the head), checked here too.
    5. Guard limits: soft limits here + the printed rail ends.
    6. Jam check (screw drive): motor driven but the encoder doesn't move -> fault.
    7. Fault: clipper off, guard runs out to its longest length.

  !! Numbers marked MEASURE are estimates until the parts arrive (see Carlos's PDF). !!
*/

#include <Wire.h>
#include <Adafruit_BNO08x.h>

// ---------------------------------------------------------------- Which guard drive?
#define DRIVE_SCREW 1      // D2.2: N20 motor with encoder + M4 lead screw + home switch (recommended)
#define DRIVE_SERVO 2      // C3 or C4: servo turning the scissor linkage
#define GUARD_DRIVE DRIVE_SCREW

#if GUARD_DRIVE == DRIVE_SERVO
#include <ESP32Servo.h>
#endif

// ---------------------------------------------------------------- Pins (XIAO ESP32-S3 has D0..D10)
// Check against Kirsten's wiring diagram before powering up.
const int PIN_FSR_A   = A0;   // D0: force pad top-left. FSR from 3V3 to pin, 10k from pin to GND
const int PIN_FSR_B   = A1;   // D1: force pad bottom-right, same divider
const int PIN_SDA     = D4;   // BNO085 SDA (address 0x4A)
const int PIN_SCL     = D5;   // BNO085 SCL
const int PIN_TRIGGER = D8;   // handle button, NO -> GND, held = LOW
const int PIN_ESTOP   = D9;   // E-stop contact B (NC chain to GND). LOW = OK, HIGH = pressed
const int PIN_CLIPPER = D10;  // clipper relay control (through E-stop contact A and trigger contact 2)
#if GUARD_DRIVE == DRIVE_SCREW
const int PIN_HOME    = D2;   // home switch at the SHORT end (1/2"), NO -> GND, pressed = LOW
const int PIN_ENC_A   = D3;   // N20 encoder channel A
const int PIN_ENC_B   = -1;   // channel B if you have a spare pad, else -1 (direction comes from the motor command)
const int PIN_MOT_1   = D6;   // motor driver IN1 (DRV8833 / TB6612 / similar)
const int PIN_MOT_2   = D7;   // motor driver IN2
const int PIN_VACUUM  = -1;   // no pin left: run the vacuum from its own switch
#else
const int PIN_SERVO   = D6;   // servo signal
const int PIN_VACUUM  = D7;   // vacuum relay (-1 if not wired)
#endif

const bool RELAY_ACTIVE_LOW = false;   // set true if your relay turns on with a LOW input

// ---------------------------------------------------------------- Tunables
const float GUARD_MIN = 12.7, GUARD_MAX = 44.45;     // 1/2" .. 1-3/4"
const int   FSR_MIN_FW = 300;                         // both pads must read above this for the clipper (laptop uses its own, higher, threshold)
const unsigned long LEASE_MS = 150, STATUS_MS = 20, HEARTBEAT_MS = 400;

#if GUARD_DRIVE == DRIVE_SCREW
const float LEAD_MM = 0.7;            // M4 thread: 0.7 mm per screw turn
const float GEAR_RATIO = 100.0;       // MEASURE: N20 gearbox ratio (motor turns per screw turn)
const float ENC_PPR = 7.0;            // MEASURE: encoder pulses per MOTOR turn on channel A (rising edges)
const float COUNTS_PER_MM = ENC_PPR * GEAR_RATIO / LEAD_MM;
const float HOME_MM = 12.2;           // MEASURE: guard length where the home switch clicks (just under 1/2")
const int   PWM_MAX = 255, PWM_MIN = 90;   // MEASURE: lowest PWM that still turns the screw
const float KP = 120.0;               // PWM per mm of error
const float DEADBAND_MM = 0.05;
const bool  MOTOR_REVERSED = false;   // flip if "longer" drives the guard shorter
const unsigned long STALL_MS = 400;   // driven this long with no encoder pulses -> jammed
#else
// Servo: guard length -> servo angle, measured at a few points (the scissor isn't linear). MEASURE all.
// C3 turns ~28 deg over the whole stroke. C4's 2:1 bevel doubles that and reverses the direction.
const float SERVO_TABLE[][2] = { {12.7, 60.0}, {28.6, 74.0}, {44.45, 88.0} };   // {mm, degrees}
const int   SERVO_POINTS = sizeof(SERVO_TABLE) / sizeof(SERVO_TABLE[0]);
const float SERVO_DEG_PER_S = 120.0;  // slew limit so the guard doesn't slam
#endif

// ---------------------------------------------------------------- Objects / state
Adafruit_BNO08x bno(-1);
sh2_SensorValue_t sensorValue;

enum { ST_NOT_HOMED = 0, ST_HOMING = 1, ST_READY = 2, ST_FAULT = 4 };
uint8_t state = ST_NOT_HOMED;
bool homed = false, clipperOn = false, vacuumOn = false, imuFound = false, driveOk = true;
volatile bool estopTripped = false;
unsigned long lastRxMs = 0, lastStatusMs = 0, permitUntil = 0, lastImuMs = 0;
float targetMm = GUARD_MAX;
float qw = 1, qx = 0, qy = 0, qz = 0;
int fsrA = 0, fsrB = 0;
char rxBuf[64];
uint8_t rxLen = 0;

#if GUARD_DRIVE == DRIVE_SCREW
volatile long encCount = 0;
volatile int8_t motorDir = 0;          // last commanded direction (+1 = longer), used with a single encoder channel
long lastEncCount = 0;
unsigned long lastEncMoveMs = 0;
#else
Servo servo;
float servoDeg = 0;
unsigned long lastServoMs = 0;
#endif

// ---------------------------------------------------------------- Helpers
bool estopOk() { return digitalRead(PIN_ESTOP) == LOW; }
bool triggerHeld() { return digitalRead(PIN_TRIGGER) == LOW; }
bool imuOk() { return imuFound && millis() - lastImuMs < 200; }
bool padsPressed() { return fsrA > FSR_MIN_FW && fsrB > FSR_MIN_FW; }
void relay(int pin, bool on) { if (pin >= 0) digitalWrite(pin, (on ^ RELAY_ACTIVE_LOW) ? HIGH : LOW); }
void setClipper(bool on) { clipperOn = on; relay(PIN_CLIPPER, on); }
void setVacuum(bool on) { vacuumOn = on && PIN_VACUUM >= 0; relay(PIN_VACUUM, vacuumOn); }
float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

void IRAM_ATTR estopISR() {
  digitalWrite(PIN_CLIPPER, RELAY_ACTIVE_LOW ? HIGH : LOW);
  estopTripped = true;
}

void fault(const char* why) {
  setClipper(false);
  setVacuum(false);
  permitUntil = 0;
  if (homed) targetMm = GUARD_MAX;      // longest guard = safest
  if (state != ST_FAULT) {
    state = ST_FAULT;
    Serial.print(F("FAULT "));
    Serial.println(why);
  }
}

// ---------------------------------------------------------------- Guard drive: D2.2 screw
#if GUARD_DRIVE == DRIVE_SCREW
void IRAM_ATTR encISR() {
  if (PIN_ENC_B >= 0) encCount += digitalRead(PIN_ENC_B) ? -1 : 1;
  else encCount += motorDir;
}

float guardMm() {
  noInterrupts(); long c = encCount; interrupts();
  return HOME_MM + c / COUNTS_PER_MM;
}

void motor(int pwm) {                   // + = guard longer, - = shorter, 0 = brake
  if (MOTOR_REVERSED) pwm = -pwm;
  pwm = constrain(pwm, -PWM_MAX, PWM_MAX);
  motorDir = (pwm > 0) - (pwm < 0);
  if (MOTOR_REVERSED) motorDir = -motorDir;
  if (pwm > 0)      { analogWrite(PIN_MOT_1, pwm); analogWrite(PIN_MOT_2, 0); }
  else if (pwm < 0) { analogWrite(PIN_MOT_1, 0);   analogWrite(PIN_MOT_2, -pwm); }
  else              { analogWrite(PIN_MOT_1, 255); analogWrite(PIN_MOT_2, 255); }   // brake: holds better
}

void driveGuard() {
  if (!homed) return;
  float err = targetMm - guardMm();
  if (fabs(err) < DEADBAND_MM) { motor(0); lastEncMoveMs = millis(); return; }
  int pwm = (int)(KP * err);
  if (abs(pwm) < PWM_MIN) pwm = err > 0 ? PWM_MIN : -PWM_MIN;
  motor(pwm);
  noInterrupts(); long c = encCount; interrupts();
  if (c != lastEncCount) { lastEncCount = c; lastEncMoveMs = millis(); }
  else if (millis() - lastEncMoveMs > STALL_MS) {       // pushing but not moving: jammed rails
    motor(0);
    driveOk = false;
    if (state != ST_FAULT) fault("GUARD_JAM");
    targetMm = guardMm();                                // stop trying (don't fight the jam)
  }
}

bool homeGuard() {
  state = ST_HOMING;
  homed = false;
  setClipper(false);
  unsigned long t0 = millis();
  // the screw is slow (~5 mm/s): a full stroke takes ~6 s
  while (digitalRead(PIN_HOME) == HIGH) {
    if (!estopOk()) { motor(0); fault("ESTOP"); return false; }
    if (Serial.available() && Serial.peek() == 'S') { Serial.read(); motor(0); fault("STOP_CMD"); return false; }
    if (millis() - t0 > 15000UL) { motor(0); fault("HOME_TIMEOUT"); return false; }
    motor(-PWM_MAX);                                     // toward the short end
    delay(1);
  }
  motor(0);
  noInterrupts(); encCount = 0; interrupts();            // here the guard is HOME_MM long
  lastEncCount = 0;
  lastEncMoveMs = millis();
  homed = true;
  driveOk = true;
  targetMm = GUARD_MAX;
  state = ST_READY;
  Serial.println(F("HOMED"));
  Serial.println(F("DONE"));
  return true;
}

void setupDrive() {
  pinMode(PIN_MOT_1, OUTPUT); pinMode(PIN_MOT_2, OUTPUT);
  motor(0);
  pinMode(PIN_HOME, INPUT_PULLUP);
  pinMode(PIN_ENC_A, INPUT_PULLUP);
  if (PIN_ENC_B >= 0) pinMode(PIN_ENC_B, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), encISR, RISING);
}

void checkHomeSwitch() {
  // the switch sits just under the shortest length, so after homing the guard never reaches it.
  // If it's pressed, the count slipped or a wire is loose.
  if (homed && state == ST_READY && digitalRead(PIN_HOME) == LOW && targetMm > GUARD_MIN + 1.0) fault("HOME_SWITCH");
}

// ---------------------------------------------------------------- Guard drive: C3/C4 servo
#else
float angleFor(float mm) {
  if (mm <= SERVO_TABLE[0][0]) return SERVO_TABLE[0][1];
  for (int i = 1; i < SERVO_POINTS; i++)
    if (mm <= SERVO_TABLE[i][0]) {
      float f = (mm - SERVO_TABLE[i - 1][0]) / (SERVO_TABLE[i][0] - SERVO_TABLE[i - 1][0]);
      return SERVO_TABLE[i - 1][1] + f * (SERVO_TABLE[i][1] - SERVO_TABLE[i - 1][1]);
    }
  return SERVO_TABLE[SERVO_POINTS - 1][1];
}

float mmFor(float deg) {               // inverse of angleFor (the table is monotonic)
  bool up = SERVO_TABLE[SERVO_POINTS - 1][1] > SERVO_TABLE[0][1];
  for (int i = 1; i < SERVO_POINTS; i++) {
    float a0 = SERVO_TABLE[i - 1][1], a1 = SERVO_TABLE[i][1];
    if ((up && deg <= a1) || (!up && deg >= a1)) {
      float f = (deg - a0) / (a1 - a0);
      return SERVO_TABLE[i - 1][0] + f * (SERVO_TABLE[i][0] - SERVO_TABLE[i - 1][0]);
    }
  }
  return SERVO_TABLE[SERVO_POINTS - 1][0];
}

// No encoder: this is where we TOLD the servo to be, not a measurement.
float guardMm() { return mmFor(servoDeg); }

void driveGuard() {
  if (!homed) return;
  unsigned long now = millis();
  float dt = (now - lastServoMs) / 1000.0;
  lastServoMs = now;
  float want = angleFor(targetMm);
  float step = SERVO_DEG_PER_S * dt;
  servoDeg += clampf(want - servoDeg, -step, step);
  servo.write(servoDeg);
}

bool homeGuard() {                     // a servo has no home switch: just go to the longest length
  servoDeg = angleFor(GUARD_MAX);
  servo.write(servoDeg);
  delay(500);
  lastServoMs = millis();
  targetMm = GUARD_MAX;
  homed = true;
  state = ST_READY;
  Serial.println(F("HOMED"));
  Serial.println(F("DONE"));
  return true;
}

void setupDrive() {
  servo.attach(PIN_SERVO, 500, 2500);
  servoDeg = angleFor(GUARD_MAX);
}

void checkHomeSwitch() {}
#endif

// ---------------------------------------------------------------- Sensors
void setupImu() {
  imuFound = bno.begin_I2C(0x4A, &Wire);
  if (!imuFound) { Serial.println(F("ERR IMU not found (BNO085 at 0x4A?)")); return; }
  bno.enableReport(SH2_GAME_ROTATION_VECTOR, 10000);     // 100 Hz
}

void pollImu() {
  if (!imuFound) return;
  if (bno.wasReset()) bno.enableReport(SH2_GAME_ROTATION_VECTOR, 10000);
  while (bno.getSensorEvent(&sensorValue)) {
    if (sensorValue.sensorId == SH2_GAME_ROTATION_VECTOR) {
      qw = sensorValue.un.gameRotationVector.real;
      qx = sensorValue.un.gameRotationVector.i;
      qy = sensorValue.un.gameRotationVector.j;
      qz = sensorValue.un.gameRotationVector.k;
      lastImuMs = millis();
    }
  }
}

void pollFsr() {
  // a little smoothing: the pads are noisy
  fsrA = (3 * fsrA + analogRead(PIN_FSR_A)) / 4;
  fsrB = (3 * fsrB + analogRead(PIN_FSR_B)) / 4;
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
      if (arg) targetMm = clampf(atof(arg), GUARD_MIN, GUARD_MAX);
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
    case 'S': fault("STOP_CMD"); break;
    case 'R':
      if (!estopOk()) { Serial.println(F("ERR estop still pressed")); break; }
      estopTripped = false;
      driveOk = true;
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
                   (driveOk ? 16 : 0) | (imuOk() ? 32 : 0) | (triggerHeld() ? 64 : 0) | (permit ? 128 : 0);
  char buf[140];
  snprintf(buf, sizeof(buf), "ST %.4f %.4f %.4f %.4f %d %d %.2f %.2f %u %u",
           qw, qx, qy, qz, fsrA, fsrB, guardMm(), targetMm, state, flags);
  Serial.println(buf);
}

// ---------------------------------------------------------------- Setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(PIN_CLIPPER, OUTPUT);
  if (PIN_VACUUM >= 0) pinMode(PIN_VACUUM, OUTPUT);
  setClipper(false); setVacuum(false);
  pinMode(PIN_TRIGGER, INPUT_PULLUP);
  pinMode(PIN_ESTOP, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_ESTOP), estopISR, RISING);
  analogReadResolution(12);
  setupDrive();
  Wire.begin(PIN_SDA, PIN_SCL, 400000);
  setupImu();
  Serial.println(F("HairBarbot cutter ready - send H to home the guard"));
}

unsigned long lastSensorMs = 0;
void loop() {
  pollSerial();
  pollImu();
  if (millis() - lastSensorMs >= 5) {               // force pads at 200 Hz
    lastSensorMs = millis();
    pollFsr();
  }

  // 1. E-stop
  if (state != ST_FAULT && (estopTripped || !estopOk())) fault("ESTOP");
  checkHomeSwitch();

  // 2. clipper = trigger held AND both pads pressed AND fresh permit from the laptop AND ready
  bool want = state == ST_READY && triggerHeld() && padsPressed() && millis() < permitUntil &&
              millis() - lastRxMs < HEARTBEAT_MS && imuOk();
  if (want != clipperOn) setClipper(want);

  // 3. guard motion (also runs in FAULT so the guard can move out to its longest length)
  driveGuard();

  if (millis() - lastStatusMs >= STATUS_MS) { lastStatusMs = millis(); sendStatus(); }
}
