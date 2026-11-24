# HairBarbot — handheld smart haircutter (ME416 Lab 3)

**Fully handheld.** The user presses HairBarbot against their head and rolls it over the hair. It's a **Flowbee**
vacuum clipper with two small **rollers** on a motorized carriage. The rollers touch the scalp, so moving the
carriage changes how far the blade sits from the scalp — that's the hair length that's left (**3–60 mm**).

In the **app** the user picks a hairstyle, for example **"Fade 2 cm → 5 cm"**. HairBarbot works out which part of
the head it's on and moves the rollers to the length that part needs. If it's somewhere it shouldn't be, or the
rollers aren't at the right length yet, the clipper turns off immediately.

> Design history: we started with a big "halo" robot, then a handheld version with a headband sensor.
> The current design is fully handheld with no headband. Older versions are in the git history.

> **iPhone app (in progress):** head scanning and head tracking are being rebuilt for the iPhone in
> [`ios/`](ios/README.md). The app there, **BarBot**, is our **developer test app**: it shows all the
> engineering (raw numbers, error maps, test logs) so we can measure what works. What we learn from it will
> go into a separate, simpler **user-facing app**. See [ios/README.md](ios/README.md).

## How it knows where it is on the head

- **One orientation sensor (BNO055) on the device.** The device is always pressed *into* the head, so the
  direction it points tells you the spot on the head (the head is roughly a sphere): pointing straight down = top,
  sideways = sides, and so on. Tilt comes from gravity (reliable); which side comes from the compass heading.
- **Camera head tracking (optional, recommended).** A webcam on the table watches the face, so the user can
  turn their head while cutting and HairBarbot still knows which side it's on. Without the camera there's no
  headband either, so the user has to keep facing the same way as during calibration.
- **Head shape.** Heads aren't round, so the direction the device points differs from the spot it's on by up to
  ~25°. The controller uses the head shape (average female/male, your circumference, or a cap 3D scan) to find
  the exact spot. With the camera it also measures your forehead and uses it as the front no-cut line.
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
pc/vision/head_scalp.py        webcam: find the face, estimate head pose, draw where the scalp is
pc/vision/head_profile.py      head sizes (ANSUR II averages, your measurement, or a 3D scan) + startup menu
pc/vision/face_mesh.py         MediaPipe 478-point face mesh (tracks turned heads)
pc/vision/head_viewer.py       3D wireframe head viewer window
pc/vision/head_scan.py         import a phone 3D scan (taken with a cap on) as a head profile
pc/camera_head.py              camera head tracking for the controller (follows head turns, measures the forehead)
pc/tests/                      tests: simulated haircut, head tracking, face/scalp estimate, head sizes, scan import
pc/live/                       Node.js + Socket.io live app: client app + operator dashboard
ios/                           iPhone developer test app (BarBot) + StandardCyborg fork; see ios/README.md
tools/flame/                   converts the FLAME head model for the iPhone app
docs/ios-test-log.md           results of hands-on iPhone app tests
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
  Try **Turn head 30° (sim)** mid-cut: the simulated camera keeps the location right.
- Tests: `cd pc && python tests/test_sim.py` (about 2 minutes; one test runs a full haircut in real time).

## 1b. Face, head and scalp (webcam + 3D)

```bash
cd pc
python3 -m pip install opencv-python numpy mediapipe
python3 vision/head_scalp.py --mirror
```
- **Face tracking:** MediaPipe Face Landmarker finds 478 points on the face and keeps tracking with the head
  turned about 60–70° either way. The face mesh is drawn on the video (key `m` toggles it). If MediaPipe isn't
  installed it falls back to OpenCV's YuNet, which needs both eyes visible. The face model (~3.6 MB) downloads
  automatically the first time.
- **Head pose + scalp:** five mesh points (eyes, nose, mouth corners) give the head's yaw / pitch / roll and
  distance. A head model is attached behind the face; the visible scalp above the face/ear no-cut line is drawn,
  colored by the chosen style (`--style fade25`). If the face is lost for a moment, the last pose stays on screen.
- **3D view:** press `v` for a separate window with a rotatable wireframe head and the live face mesh on it
  (drag to turn, scroll to zoom). Or on its own: `python3 vision/head_viewer.py --sex female`.
- Keys: `q` quit, `s` screenshot, `m` mesh, `v` 3D view.

**What the camera can and can't do:** it measures the *face* surface. It can't see bone or the back of the head,
so the skull shape is an **estimate** from the head-size menu, unless you use a 3D scan (below).

**Head size menu** (at startup): `1` female, `2` male, `3` personalized, `4` saved 3D scan (if you have one).
Options 1 and 2 use median head sizes from **ANSUR II**, the 2012 U.S. Army anthropometric survey of 1,986 women
and 4,082 men ([data](https://www.openlab.psu.edu/datasets/ansur2/), Gordon et al., NATICK/TR-15/007):

| | head circumference | head length | head width | ear to top of head |
|---|---|---|---|---|
| Female | 56.0 cm | 19.0 cm | 14.7 cm | 12.7 cm |
| Male | 57.4 cm | 20.0 cm | 15.4 cm | 13.1 cm |

Option 3 asks for head circumference with units (`57 cm`, `22.5 in`, `570 mm`) and scales the average head.
Skip the menu with `--sex female`, `--sex male`, `--head-circ "57 cm"` or `--scan vision/profiles/<name>.json`.

### Most accurate: a 3D head scan with a cap on

Hair sits 1–5 cm above the scalp, so scanning hair gives the wrong shape. A thin **matte wig cap or swim cap**
flattens it to a few mm and scans far better than shiny or wet hair.

1. Put on the cap. Sit still, face relaxed, looking straight ahead.
2. Scan with a phone app (Polycam, Scaniverse, …): walk slowly around the head about 30 cm away, covering the
   top and back. Export as **OBJ, PLY or STL**.
3. `python3 vision/head_scan.py my_scan.obj --name shiqi` → a 3D window opens. Check the orange hairline is at
   the forehead and the face is at the front (`f` flips front/back, `[` `]` turn 5°), then `s` to save.
4. The profile is saved to `pc/vision/profiles/shiqi.json` and shows up as option 4 in the menu.
5. Take the cap off before cutting. The scan can be reused for later haircuts.

The import subtracts 3 mm for the cap and flattened hair (`--cap`) and assumes the scan is upright with Y up,
as phone AR scans are (`--up z` otherwise).

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
5. Flash `firmware/hairbarbot_handheld`, then run the controller and `npm start` in `pc/live`:
   ```
   python3 app.py --port <your port> --camera 0 --head female        # or male, "57 cm", vision/profiles/<you>.json
   ```
   `--camera 0` turns on camera head tracking (webcam on the table, facing the user). `--head` picks the head shape
   (default: average adult). The operator page shows the camera view with the face mesh.

## 4. Calibrate on each user
In the operator dashboard: **Start calibration** → for each spot (top, back, left, right), hold the device flat on
the head, keep still, **Record** → **Finish calibration**. It reports how well the spots agree (±degrees).
- With the camera: keep your face toward the camera while recording. The head may move a bit between spots, and
  after calibration you can turn your head freely while cutting.
- Without the camera: sit upright facing forward and stay that way; redo calibration if you turn your chair.

The app suggests starting at the back of the neck and rolling upward (against hair growth), but HairBarbot knows
where it is, so any order works.

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
| Face out of view | PC (with camera) | clipper pauses if the camera can't see the face for 1 s |
| Unexpected clipper | PC | if the board reports the clipper on without permission → full stop |
| Hard stop | mechanical | printed stop: the rollers can never go closer than 3 mm |

Testing: mannequin heads and balloons until RASTIC signs off. First human tests: team members, longest length.

## 6. Things you'll tune
- `pc/styles.py` — add hairstyles from the barber interviews (each = 5 lengths + optional fade).
- `pc/config.py` — `GUARD_TOL`, `ROLLING_MIN_SPEED`, coverage settings, calibration spots.
- `pc/orientation.py` — the no-cut zone table (`ZONE_YAW` / `ZONE_PITCH`).
- Firmware — `ROLLER_DIAMETER`, `STEPS_PER_MM` if your lead screw isn't 2 mm.

AI disclosure: initial code and design generated with Claude (Anthropic) and reviewed and modified by the team.
