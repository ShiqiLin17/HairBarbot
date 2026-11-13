# HairBarbot — handheld smart haircutter (ME416 Lab 3)

The user holds a **Flowbee** vacuum clipper. A small motor on the Flowbee moves the **comb sleeve (guard)**,
which sets how long the hair is left. HairBarbot knows **where on the head** the clipper is and changes the
guard length automatically to match the chosen haircut. If the clipper is somewhere it shouldn't be, or the
guard isn't at the right length yet, the clipper turns off immediately.

So the user doesn't need to know how to cut hair: pick a style in the app, hold the trigger, and move the
clipper over the head until the app's head map is fully covered.

> We started with a big "halo" robot that moved the clipper for you. The team switched to this handheld
> design: much cheaper, far less to build in 5 weeks, and it solves the real problem for people at home
> (knowing *how* to cut, not holding the clipper). The old design is in the git history.

## How it knows where the clipper is

Two orientation sensors (BNO055): one on the Flowbee, one on a headband.
The Flowbee is always held pointing **into** the scalp, so the direction it points tells you the spot on the
head (the head is roughly a sphere). Comparing it with the headband sensor removes head movement.

```
spot on the head  =  M  ·  R_headᵀ  ·  ( −R_clipper · clipper_axis )
                     ↑ calibration (hold the clipper at 3–4 known spots: top, back, left, right)
```
That gives **yaw** (around the head: 0 = face, +90 = left, 180 = back) and **pitch** (down from the crown).
A distance sensor (VL53L1X) next to the comb checks the comb is actually touching the head.

## What's in the repo

```
firmware/hairbarbot_handheld/  ESP32 firmware: guard motor, 2 IMUs, distance sensor, trigger, relays, E-stop
firmware/bench_test/           test each part on its own while wiring
pc/app.py                      controller + API (python app.py --sim  /  --port COM3)
pc/controller.py               50 Hz loop: location -> guard length -> clipper allowed? -> coverage map
pc/orientation.py              quaternion math, calibration (Kabsch), no-cut zones (face, ears)
pc/styles.py                   haircut styles: length per region (top, front, sides, back, nape) + fade
pc/serial_link.py              serial protocol to the ESP32 + a full simulator (fake board + fake user)
pc/tests/test_sim.py           tests, including a full simulated haircut
pc/live/                       Node.js + Socket.io live app: client app + operator dashboard
docs/budget.xlsx               parts list + budget
docs/build-book.html           drawings, parts to make, wiring, plan (open in a browser)
```

## 1. Try it now (no hardware)

```bash
git clone https://github.com/ShiqiLin17/HairBarbot.git
cd HairBarbot/pc
pip install flask numpy pyserial
cd live
npm install
npm run demo          # starts the simulated controller + the live app
```
- **http://localhost:3000** — client app: choose a style (3D preview), then watch the head map fill in as
  the simulated user cuts. Shows the area being cut, the guard length vs what that spot needs, what's left to do.
- **http://localhost:3000/operator** — team dashboard: Home guard → Start calibration → Record each spot →
  Finish calibration (or "Skip calibration (sim)"). Then start a haircut from the client app.
  Shows the clipper decision and why, the guard-vs-spot chart, distance sensor, coverage per area, event log.
- Tests: `cd pc && python tests/test_sim.py` (about 2–3 minutes; one test runs a full haircut in real time).

## 2. Electronics

| ESP32 pin | Connects to |
|-----------|-------------|
| 25 / 26 / 27 | TMC2209 STEP / DIR / EN (guard motor) |
| 33 | guard home switch (at the LONG end), other side to GND |
| 32 | trigger switch pole 1 → GND (held = LOW) |
| 14 | E-stop contact B chain → GND (LOW = OK; a broken wire reads as pressed) |
| 18 | clipper relay control, wired **through E-stop contact A and trigger pole 2** |
| 19 | vacuum relay control |
| 21 / 22 | I²C bus 0: clipper BNO055 (0x28) + VL53L1X (0x29), on the Flowbee |
| 16 / 17 | I²C bus 1: head BNO055 (0x28), on the headband cable |
| 2 / 4 | status LED / buzzer |

- TMC2209: VM = 12 V, VIO = 3.3 V from the ESP32, MS1 = MS2 = GND (8 microsteps), common ground. Start with low motor current.
- **Mains:** switch the clipper and vacuum with enclosed low-voltage outlet relays (e.g. IoT Power Relay), plugged into a GFCI strip. Never hand-wire 120 V. Have RASTIC check it before first power-up.
- **Clipper sensor mounting:** mount the clipper BNO055 so its Z axis points from the clipper toward the scalp. If you mount it another way, change `CLIP_AXIS` in `pc/config.py`.
- Keep the sensor cables under ~1.5 m. The headband bus already runs slower (100 kHz) for the longer cable.

Libraries (Arduino Library Manager): **AccelStepper**, **Adafruit BNO055**, **Adafruit Unified Sensor**, **VL53L1X** (Pololu).
Board: **ESP32 Dev Module** (install "esp32 by Espressif" in Boards Manager).

## 3. Bring-up order (one thing at a time)
1. Flash `firmware/bench_test`. Guard motor: `m 800` should move the sleeve 1 mm longer. Fix direction if not.
2. Switches: `s` shows home switch, trigger, E-stop.
3. Sensors: `i` prints both IMUs (move them and watch the angles), `t` prints the distance.
4. Relays with the clipper and vacuum **unplugged** first (`C` / `c`, listen for the click).
5. Flash `firmware/hairbarbot_handheld`, then run `python app.py --port <your port>` and `npm start` in `pc/live`.

## 4. Calibrate on each user
In the operator dashboard: headband on → **Start calibration** → for each spot (top, back, left, right), hold the
clipper against the head pointing straight at it, keep still, **Record** → **Finish calibration**.
It reports how well the spots agree (±degrees). Redo it if it says the spots disagree.

## 5. Safety layers (keep all of them)
| Layer | Where | What it does |
|-------|-------|--------------|
| E-stop contact A | hardware | cuts clipper power directly |
| Trigger pole 2 | hardware | clipper can't run unless the user holds the trigger, even if the code freezes |
| E-stop contact B | firmware | fault: clipper + vacuum off, guard goes to its longest length |
| Permit lease | firmware | the laptop must re-allow the clipper every 20 ms; if it stops (crash, unplugged), the clipper is off within 150 ms |
| **Wrong spot** | PC, 50 Hz | clipper off while the guard isn't within ±1.5 mm of the length this spot needs |
| No-cut zones | PC | clipper off near the face and ears (trim those by hand) |
| Lost sensors | PC | clipper off if either orientation sensor stops working |
| Unexpected clipper | PC | if the board reports the clipper on without permission → full stop |
| Guard hard stop | mechanical | printed stop: the comb can never go below 3 mm |

Testing: mannequin heads and balloons until RASTIC signs off. First human tests: team members, longest guard.

## 6. Things you'll tune
- `pc/styles.py` — add styles from the barber interviews (each style = 5 lengths + optional fade).
- `pc/config.py` — `TOF_OFFSET` (measure on the real part), `GUARD_TOL`, coverage settings, calibration spots.
- `pc/orientation.py` — the no-cut zone table (`ZONE_YAW` / `ZONE_PITCH`).

AI disclosure: initial code and design generated with Claude (Anthropic) and reviewed and modified by the team.
