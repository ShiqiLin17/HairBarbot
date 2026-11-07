# HairBarbot — robotic haircutter (ME416 Lab 3)

A vacuum clipper (Flowbee head) on a spherical "halo" robot centered on the client's head:

| Axis  | What it is | Range | Drive |
|-------|------------|-------|-------|
| YAW   | turntable above the head, rotates around the vertical axis through head center | ±170° | NEMA17, 20T → 150T laser-cut GT2 pulley (7.5:1) |
| PITCH | carriage running along a laser-cut arc (R≈230 mm), crown → nape | −12…112° | NEMA17 on the carriage, crawls a GT2 belt fixed to the arc |
| RAD   | radial slide pointing at the head center | 0…110 mm | NEMA17 + T8 lead screw (8 mm lead) |
| GUARD | motorized comb = hair length left after the cut | 3…40 mm | small stepper + 2 mm lead screw, hard stop at 3 mm |

Because the robot is centered on the head, inverse kinematics is just spherical coordinates:
`yaw, pitch` pick the spot, and `rad = D0 − guard − r_scalp(yaw, pitch)` puts the comb on the scalp.

```
docs/build-book.html     drawings, parts to make, wiring, plan (open in a browser)
docs/budget.xlsx          parts list + budget
  firmware/hairbarbot_firmware/   Arduino Mega firmware (motors, sensors, relays, safety interlocks)
  firmware/bench_test/      simple sketch to test each motor / switch / relay while wiring
  pc/app.py                 server + client web app  (python app.py --sim)
  pc/controller.py          state machine, calibration, haircut runner, safety watchdog
  pc/planner.py             haircut -> strokes (against hair growth, crown last)
  pc/styles.py              haircut styles and length-per-region blending
  pc/kinematics.py          spherical IK, head model (ellipsoid), forbidden zones
  pc/head_tracker.py        webcam + MediaPipe head pose: stop if the head moves
  pc/serial_link.py         serial protocol to the Arduino + full simulator
  pc/web/index.html         the client app (style picker, preview, START/PAUSE, big STOP)
  pc/tests/test_sim.py      end-to-end test in simulation
```

## 1. Try it today (no hardware)

```bash
cd pc
pip install flask numpy pyserial
python app.py --sim --speedup 5
```
Open http://localhost:5000 → Operator panel → **Home** → **Skip calibration** → pick a style → **Start haircut**.
Watch the dot move on the head map; try **Simulate head movement** and the **STOP** bar.
Run the tests: `python tests/test_sim.py`.

The app also works on a phone: on the same Wi-Fi open `http://<laptop-ip>:5000`.

## 2. Electronics

### Parts
Arduino Mega 2560 · 4× TMC2209 driver (standalone) · 4× NEMA17 (guard can be NEMA11/8 with lead screw) ·
24 V PSU · 2× Pololu VL53L1X · 4× microswitch · 2× latching mushroom E-stop (2 NC contacts each) ·
2-channel relay output (see AC warning) · buzzer · 2 LEDs + 220 Ω.

### Pin map (Arduino Mega)

| Pin | Connects to |
|-----|-------------|
| 22 / 23 | YAW driver STEP / DIR |
| 24 / 25 | PITCH driver STEP / DIR |
| 26 / 27 | RAD driver STEP / DIR |
| 28 / 29 | GUARD driver STEP / DIR |
| 30 | EN of all 4 drivers (LOW = enabled) |
| 31 / 32 / 33 / 34 | limit switch YAW / PITCH / RAD / GUARD (NO contact, other side to GND) |
| 2 | E-stop contact B (NC chain to GND). LOW = OK. Broken wire reads as pressed. |
| 40 | CLIPPER relay signal — goes **through E-stop contact A** first |
| 41 | VACUUM relay signal |
| 42 / 43 | green OK LED / red FAULT LED |
| 44 | buzzer |
| 20 / 21 | SDA / SCL to both VL53L1X |
| 45 / 46 | XSHUT of ToF 1 / ToF 2 (2.8 V pin: firmware only pulls LOW or floats it) |

### TMC2209 (standalone STEP/DIR)
- VM = 24 V (100 µF cap at each driver), VIO = 5 V from Mega, all GNDs common.
- MS1 = MS2 = GND → **8 microsteps** (the firmware's steps/unit assume this).
- Set motor current with the Vref pot. Start LOW (≈0.6 A): weak motors are a safety feature here.
- Never unplug a motor while the driver is powered.

### E-stop — the most important wiring
Use two latching mushroom E-stops (one the client can reach, one for the operator), each with 2 NC contacts, wired in series:
- **Contact A** chain is in series with the clipper relay signal (pin 40 → E-stop A chain → relay +).
  Pressing either button cuts clipper power in hardware, even if the code is frozen.
- **Contact B** chain goes pin 2 → GND, so the firmware also knows, turns everything off and retracts the arm.

### AC power (clipper + vacuum) — do not hand-wire mains
Use an enclosed low-voltage-controlled outlet relay (e.g. "IoT Power Relay", ~$30) for the clipper and another (or a 2-outlet one) for the vacuum.
The Arduino only drives its 3–48 V control input. Plug both into a GFCI strip. Ask RASTIC to check this before first power-up.
If your relay turns ON when its input is LOW, set `RELAY_ACTIVE_LOW = true` in the firmware.

### Pitch arm must not fall
The motors hold the arm while powered. If power is lost the carriage could slide down the arc onto the head:
add a counterweight or constant-force spring so the carriage is balanced, and test with the drivers disabled (`e` in bench_test).

## 3. Bring-up order (do one thing at a time)
1. Flash `firmware/bench_test`. Wire ONE driver + motor, run `3 1600` (one rev). Repeat per axis. Fix directions:
   +steps must be yaw → client's left, pitch → down toward the nape, rad → toward the head, guard → longer.
2. Wire switches and E-stops, check with `s`.
3. Relays with the clipper/vacuum **unplugged** first (`C`/`c`, listen for the click), then plugged in.
4. ToF sensors (`t`).
5. Flash `firmware/hairbarbot_firmware`. In Serial Monitor send `H` (home), then `M 0 30 20 20 20` etc. Watch `ST ...` lines.
6. Run the PC app for real: `python app.py --port COM3` (Windows) or `--port /dev/ttyACM0`.

Libraries: Arduino Library Manager → **AccelStepper** (Mike McCauley) and **VL53L1X** (Pololu). Board: Arduino Mega 2560.

## 4. Calibrate the machine
**D0** (in `pc/config.py`): distance from the head center (where the yaw axis and the arc center meet) to the clipper blade
when the radial slide is at 0. Measure it with the guard at 3 mm: put a 3D-printed "head center" pointer at the center,
jog RAD until the comb tip touches it, then D0 = rad + 3 + (pointer length). Also check the arc center really is
the head center: the comb tip should stay the same distance from the pointer when you jog PITCH.

**Steps per unit** live at the top of the firmware (`ax[]` table). If you change pulleys or lead screws, recalculate:
`steps/unit = 1600 × gear ratio / (deg or mm per output rev)`. Check: command 90° and measure.

## 5. Calibrate each client's head (in the app, Operator panel)
1. Client sits, chin on the chin rest, camera sees the face.
2. **Start calibration** → for each point press **Go**, jog with +1/+5 until the comb just touches the hair, **Record**.
3. **Finish** fits an ellipsoid head model and stores the head position for the camera check.

## 6. Safety layers (keep ALL of them)
| Layer | Where | What it does |
|-------|-------|--------------|
| E-stop contact A | hardware | cuts clipper power directly |
| E-stop contact B | firmware | fault: clipper off, axes stop, radial retracts |
| Heartbeat | firmware | PC silent for 400 ms while moving/cutting → fault |
| Forbidden zones | firmware + PC | no cutting near face or ears (`max_pitch()` table) |
| Soft limits + limit switches | firmware | out of range → fault |
| ToF too close | firmware | head closer than the comb should allow → fault |
| **Wrong spot** | PC watchdog 50 Hz | guard length ≠ what the haircut needs at the cutter's current spot → stop |
| Too deep | PC watchdog | comb deeper than the head model → stop |
| Head moved / face lost | PC + camera | head moved >8 mm, turned >6°, or face not visible >0.3 s → stop |
| Low motor current, guard hard stop at 3 mm, blade never exposed | mechanical | |

Testing rules: mannequin heads only until RASTIC signs off. First human tests: team members, longest guard, both E-stops staffed.

## 7. Things you will probably tune
- `config.py`: D0, head defaults, `FEED_CUT` (cut speed), `STROKE_YAW_STEP` (overlap), safety thresholds.
- `styles.py`: add styles from your user interviews — each style is just 5 lengths (+ optional fade).
- `kinematics.max_pitch()` **and** `maxPitch()` in the firmware: the allowed zone. Keep them identical.

AI disclosure: initial code and design generated with Claude (Anthropic) and reviewed/modified by the team.
