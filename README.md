# HairBarbot — handheld smart haircutter (ME416 Lab 3)

**Fully handheld.** The user presses HairBarbot against their head and rolls it over the hair. It's a **Flowbee**
vacuum clipper with two small **rollers** on a motorized carriage. The rollers touch the scalp, so moving the
carriage changes how far the blade sits from the scalp — that's the hair length that's left (**3–60 mm**).

In the **app** the user picks a hairstyle, for example **"Fade 2 cm → 5 cm"**. HairBarbot works out which part of
the head it's on and moves the rollers to the length that part needs. If it's somewhere it shouldn't be, or the
rollers aren't at the right length yet, the clipper turns off immediately.

> Design history: we started with a big "halo" robot, then a handheld version with a headband sensor.
> The current design is fully handheld with no headband. Older versions are in the git history.

## How it knows where it is on the head

- **One orientation sensor (BNO055) on the device.** The device is always pressed *into* the head, so the
  direction it points tells you the spot on the head (the head is roughly a sphere): pointing straight down = top,
  sideways = sides, and so on. Tilt comes from gravity (reliable); which side comes from the compass heading.
- **No headband**, so the user should sit upright and keep facing the same way as during calibration.
- **Roller encoder (AS5600).** One roller has a magnet, so HairBarbot knows how far it has rolled. Areas only count
  as cut while the device is actually rolling, and the app shows the distance cut.

```
spot on the head  =  M  ·  ( −R_device · device_axis )
                     ↑ calibration: hold the device at 3–4 known spots (top, back, left, right)
```
That gives **yaw** (around the head: 0 = face, +90 = left, 180 = back) and **pitch** (down from the crown).

## What's in the repo

```
firmware/hairbarbot_handheld/  ESP32 firmware: roller carriage motor, IMU, roller encoder, trigger, relays, E-stop
firmware/bench_test/           test each part on its own while wiring
pc/app.py                      controller + API (python app.py --sim  /  --port COM3)
pc/controller.py               50 Hz loop: location -> length -> clipper allowed? -> coverage map
pc/orientation.py              quaternion math, calibration (Kabsch), no-cut zones (face, ears)
pc/styles.py                   hairstyles: length per region + fade (e.g. "Fade 2 cm -> 5 cm")
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
- **http://localhost:3000** — client app: choose a hairstyle (3D preview), then watch the head fill in as the
  simulated user rolls over it. Shows the area being cut, the roller length vs what that spot needs, distance cut, what's left.
- **http://localhost:3000/operator** — team dashboard: Home guard → Start calibration → Record each spot →
  Finish calibration (or "Skip calibration (sim)"). Then start a haircut from the client app.
- Tests: `cd pc && python tests/test_sim.py` (about 2 minutes; one test runs a full haircut in real time).

## 2. Electronics

| ESP32 pin | Connects to |
|-----------|-------------|
| 25 / 26 / 27 | TMC2209 STEP / DIR / EN (roller carriage motor) |
| 33 | home switch (at the LONG end, 62 mm), other side to GND |
| 32 | trigger switch pole 1 → GND (held = LOW) |
| 14 | E-stop contact B chain → GND (LOW = OK; a broken wire reads as pressed) |
| 18 | clipper relay control, wired **through E-stop contact A and trigger pole 2** |
| 19 | vacuum relay control |
| 21 / 22 | I²C: BNO055 (0x28) + AS5600 roller encoder (0x36), both on the device |
| 2 / 4 | status LED / buzzer |

- TMC2209: VM = 12 V, VIO = 3.3 V from the ESP32, MS1 = MS2 = GND (8 microsteps), common ground. Start with low motor current.
- **Mains:** switch the clipper and vacuum with enclosed low-voltage outlet relays (e.g. IoT Power Relay), plugged into a GFCI strip. Never hand-wire 120 V. Have RASTIC check it before first power-up.
- **IMU mounting:** mount the BNO055 so its Z axis points from the device toward the scalp. Otherwise change `CLIP_AXIS` in `pc/config.py`.
- **Roller encoder:** glue the diametric magnet on the end of one roller axle, AS5600 chip 1–2 mm from it, centered. Set `ROLLER_DIAMETER` in the firmware.

Libraries (Arduino Library Manager): **AccelStepper**, **Adafruit BNO055**, **Adafruit Unified Sensor**.
Board: **ESP32 Dev Module** (install "esp32 by Espressif" in Boards Manager).

## 3. Bring-up order (one thing at a time)
1. Flash `firmware/bench_test`. Motor: `m 800` should move the rollers 1 mm farther out. Fix direction if not.
2. Switches: `s` shows home switch, trigger, E-stop.
3. Sensors: `i` prints the IMU angles (tilt the device and watch), `e` prints the roller distance for 5 s (roll it on the table: 10 cm should read ~100 mm).
4. Relays with the clipper and vacuum **unplugged** first (`C` / `c`, listen for the click).
5. Flash `firmware/hairbarbot_handheld`, then run `python app.py --port <your port>` and `npm start` in `pc/live`.

## 4. Calibrate on each user
User sits upright, facing forward. In the operator dashboard: **Start calibration** → for each spot (top, back,
left, right), press the rollers against the head pointing straight at it, keep still, **Record** → **Finish calibration**.
It reports how well the spots agree (±degrees). Redo it if it says they disagree, or if the user turns their chair.

## 5. Safety layers (keep all of them)
| Layer | Where | What it does |
|-------|-------|--------------|
| E-stop contact A | hardware | cuts clipper power directly |
| Trigger pole 2 | hardware | clipper can't run unless the user holds the trigger, even if the code freezes |
| E-stop contact B | firmware | fault: clipper + vacuum off, rollers go to their longest length |
| Permit lease | firmware | the laptop must re-allow the clipper every 20 ms; if it stops, the clipper is off within 150 ms |
| **Wrong spot** | PC, 50 Hz | clipper off while the rollers aren't within ±1.5 mm of the length this spot needs |
| No-cut zones | PC | clipper off near the face and ears (trim those by hand) |
| Lost sensor | PC | clipper off if the orientation sensor stops working |
| Unexpected clipper | PC | if the board reports the clipper on without permission → full stop |
| Hard stop | mechanical | printed stop: the rollers can never go closer than 3 mm |

Testing: mannequin heads and balloons until RASTIC signs off. First human tests: team members, longest length.

## 6. Things you'll tune
- `pc/styles.py` — add hairstyles from the barber interviews (each = 5 lengths + optional fade).
- `pc/config.py` — `GUARD_TOL`, `ROLLING_MIN_SPEED`, coverage settings, calibration spots.
- `pc/orientation.py` — the no-cut zone table (`ZONE_YAW` / `ZONE_PITCH`).
- Firmware — `ROLLER_DIAMETER`, `STEPS_PER_MM` if your lead screw isn't 2 mm.

AI disclosure: initial code and design generated with Claude (Anthropic) and reviewed and modified by the team.
