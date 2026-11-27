# HairBarbot — smart haircutter (BU robotics class, Lab 3)

**The cutter is a Flowbee** (vacuum clipper) with a motorized **outer guard**. The guard slides on printed rails
and sets how long the hair is left: **1/2" to 1-3/4" (12.7–44.45 mm)**. The user **picks the cutter up and
places it** on the head, one spot at a time (it doesn't roll over the head).

In the **app** the user picks a hairstyle, for example **"Fade 2 cm → 4 cm"**. HairBarbot works out which spot
the cutter is on and moves the guard to the length that spot needs. The clipper only runs when the cutter is
sitting flat on the head, in the right place, with the guard at the right length.

> Design history: a big "halo" robot → handheld with a headband → handheld with rollers that rolled over the head →
> **now: pick up and place, with force sensors and ArUco tags** (Nov 2026). Older versions are in the git history.
> The guard drive options (D2.2 screw, C3/C4 scissor) are compared in
> [docs/guard-drive-options.pdf](docs/guard-drive-options.pdf) (Carlos).

> **iPhone apps (in progress):** head scanning and head tracking are being rebuilt for the iPhone in
> [`ios/`](ios/README.md). **HairBarbot** is the **user-facing app**: a guided three-part head scan saved
> under the person's name, then choose a person and style to cut (styles, cutting and the Bluetooth link
> are placeholders for now). **BarBot** is our **developer test app**: it shows all the engineering (raw
> numbers, error maps, test logs) so we can measure what works. See [ios/README.md](ios/README.md).

## How it knows where the cutter is on the head

Full explanation: **[docs/cutter-tracking.md](docs/cutter-tracking.md)**. In short, three things work together:

1. **IMU (BNO085) on the cutter.** When the cutter sits flat on the head it points along the scalp's surface
   normal, so the direction it points picks out the spot (using the head's shape). Works everywhere, including
   the back of the head, but its heading drifts slowly and it's only right when the cutter is seated flat.
2. **Two force sensors (FSRs) in the scalp face** (top-left and bottom-right). Both pressed = the cutter is
   sitting flat on the head. One or none = it's lifted or rocked, so the clipper stays off.
3. **ArUco tags on the cutter** (left, right and rear plates). The camera that tracks the face also sees the tags,
   so it knows where the cutter touches the head in mm. Very accurate while visible; can't see the back of the head.

How they combine: **tags visible → the tags give the spot**, and each sighting corrects the IMU's drift and
calibration error. **Tags hidden → the corrected IMU gives the spot.** If the tags and the IMU disagree by more
than 20°, the clipper stays off until they agree again.

Spots are given as **yaw** (around the head: 0 = face, +90 = the client's left, 180 = back) and **pitch** (down
from the crown). The head shape (average female/male, your circumference, or a swim-cap 3D scan) turns
directions and points into spots.

## What's in the repo

```
firmware/hairbarbot_handheld/  XIAO ESP32-S3 firmware: guard drive (D2.2 screw or C3/C4 servo), BNO085, 2 force
                               pads, trigger, E-stop, clipper relay
firmware/bench_test/           test each part on its own while wiring
pc/app.py                      controller + API (python app.py --sim  /  --port /dev/cu.usbmodem...)
pc/controller.py               50 Hz loop: seated? -> where -> length -> clipper allowed? -> coverage map
pc/cutter_tracking.py          combines the IMU with ArUco tag sightings (and corrects the IMU's drift)
pc/orientation.py              quaternion math, calibration (Kabsch), no-cut zones (face, ears), head-shape lookups
pc/styles.py                   hairstyles: length per region + fade (e.g. "Fade 2 cm -> 4 cm")
pc/serial_link.py              serial protocol to the ESP32 + a full simulator (fake board + fake user placing the cutter)
pc/vision/cutter_tags.py       find the cutter's ArUco tags in a picture; print the tags
pc/vision/head_scalp.py        webcam: find the face, estimate head pose, draw where the scalp is
pc/vision/head_profile.py      head sizes (ANSUR II averages, your measurement, or a 3D scan) + startup menu
pc/vision/face_mesh.py         MediaPipe 478-point face mesh (tracks turned heads)
pc/vision/head_viewer.py       3D wireframe head viewer window
pc/vision/head_scan.py         import a phone 3D scan (taken with a cap on) as a head profile
pc/camera_head.py              camera tracking for the controller: head pose + cutter tags in the same picture
pc/tests/                      tests: simulated haircut, cutter tracking, head tracking, face/scalp, head sizes, scans
pc/live/                       Node.js + Socket.io live app: client app + operator dashboard
ios/                           iPhone apps: HairBarbot (user app) + BarBot (developer test app) + StandardCyborg fork; see ios/README.md
tools/flame/                   converts the FLAME head model for the iPhone app
docs/cutter-tracking.md        how the cutter is located (IMU + force pads + tags), iPhone hand-off, open questions
docs/guard-drive-options.pdf   Carlos's comparison of the guard drives (D2.2 screw, C3 and C4 scissors)
docs/ios-test-log.md           results of hands-on iPhone app tests
docs/budget.xlsx               parts list + budget (from the roller design; needs updating)
docs/build-book.html           older roller-design build book (drawings, plan); see the note at its top
design/                        user-app brand: style guide, color tokens (Swift + CSS), app icon; see design/README.md
AGENTS.md                      pointers for AI agents (UI work -> design/)
```

## 1. Try it now (no hardware)

```bash
git clone https://github.com/ShiqiLin17/HairBarbot.git
cd HairBarbot/pc
pip install flask numpy pyserial opencv-python
cd live
npm install
npm run demo          # starts the simulated controller + the live app
```
- **http://localhost:3000** — client app: choose a hairstyle (3D preview), then watch the head fill in as the
  simulated user places the cutter spot by spot. Shows the area, the guard length vs what that spot needs, whether
  the cutter is on the head, and what's left.
- **http://localhost:3000/operator** — team dashboard: Home guard → Start calibration → Record each spot →
  Finish calibration (or "Skip calibration (sim)"). Then start a haircut from the client app.
  Watch **Located by** switch between *camera tags* (front and sides) and *IMU* (back of the head), and the
  force-pad chart. Try **Lift cutter**, **Hide / show tags** and **Turn head 30°** mid-cut.
- Tests: `cd pc && python -m pytest tests` (about 2 minutes; one test runs a whole simulated haircut).
  The simulated IMU drifts like a real one, so the tests check that the tags correct it.

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

(The iPhone app in `ios/` does this better now: a guided TrueDepth scan with a FLAME head model fitted to it.)

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

## 2. Electronics (XIAO ESP32-S3 in the sensor box on the cutter)

Check these against Kirsten's wiring before powering up. Pins are set at the top of the firmware.

| XIAO pin | Connects to |
|-----------|-------------|
| D0 (A0) / D1 (A1) | force pads A (top-left) / B (bottom-right): FSR from 3V3 to the pin, 10 kΩ from the pin to GND |
| D4 / D5 | I²C SDA / SCL: BNO085 IMU (address 0x4A) |
| D2 | home switch at the SHORT end (1/2"), other side to GND |
| D3 | N20 motor encoder, channel A |
| D6 / D7 | motor driver IN1 / IN2 (DRV8833 or similar) for the N20 screw motor |
| D8 | trigger switch pole 1 → GND (held = LOW) |
| D9 | E-stop contact B chain → GND (LOW = OK; a broken wire reads as pressed) |
| D10 | clipper relay control, wired **through E-stop contact A and trigger pole 2** |

- **Servo build (C3/C4 scissor):** set `GUARD_DRIVE DRIVE_SERVO` in the firmware. The servo goes on D6, D7 can
  then drive a vacuum relay. Measure the servo angle at a few guard lengths and fill in `SERVO_TABLE`.
- **Mains:** switch the clipper with an enclosed low-voltage outlet relay (e.g. IoT Power Relay) on a GFCI strip.
  Never hand-wire 120 V. Have RASTIC check it before first power-up.
- **IMU mounting:** mount the BNO085 so its Z axis points from the cutter toward the scalp. Otherwise change
  `CLIP_AXIS` in `pc/config.py`. The firmware uses its *game rotation vector* (no compass), so the motor's
  magnet can't disturb it; the tags correct its slow heading drift.
- **ArUco tags:** `python3 pc/vision/cutter_tags.py --print tags.png`, print at 100%, check the 50 mm bar, glue
  them on the tag plates. Then measure where each tag sits on the cutter (from the CAD) into `TAGS` in
  `pc/config.py` (the numbers there now are placeholders).

Libraries (Arduino Library Manager): **Adafruit BNO08x** (servo build: **ESP32Servo**).
Board: **XIAO_ESP32S3** ("esp32 by Espressif" in Boards Manager), USB CDC On Boot: Enabled.

## 3. Bring-up order (one thing at a time)
1. Flash `firmware/bench_test`.
2. Switches: `s` shows home switch, trigger, E-stop.
3. Guard motor: `m 150 300` should make the guard longer, `m -150 300` shorter, and print encoder counts.
   Measure the guard with calipers to get counts per mm, then set `GEAR_RATIO` / `ENC_PPR` / `HOME_MM` /
   `PWM_MIN` in the firmware (all marked MEASURE).
4. Force pads: `f` prints both pads for 5 s. Note the numbers in the air, resting on a head and pressed, and set
   `FSR_ON` / `FSR_OFF` in `pc/config.py` between "in the air" and "resting".
5. IMU: `i` prints the quaternion (turn the cutter and watch it change).
6. Relay with the clipper **unplugged** first (`C` / `c`, listen for the click).
7. Tags: `python3 pc/vision/cutter_tags.py --camera 0` should draw the cutter's axes on the tags.
8. Flash `firmware/hairbarbot_handheld`, then run the controller and `npm start` in `pc/live`:
   ```
   python3 app.py --port <your port> --camera 0 --head female        # or male, "57 cm", vision/profiles/<you>.json
   ```
   `--camera 0` turns on head tracking and the tag sightings (webcam on the table, facing the user).

## 4. Calibrate on each user
In the operator dashboard: **Start calibration** → for each spot (top, back, left, right), place the cutter flat
on the head (both pads pressed), keep still, **Record** → **Finish calibration**. It reports how well the spots
agree (±degrees). This gives the IMU a starting point; after that, every time the camera sees the tags it fixes
the IMU's error, so a rough calibration is fine.
- Keep your face toward the camera while recording. After calibration you can turn your head while cutting.

## 5. Safety layers (keep all of them)
| Layer | Where | What it does |
|-------|-------|--------------|
| E-stop contact A | hardware | cuts clipper power directly |
| Trigger pole 2 | hardware | clipper can't run unless the user holds the trigger, even if the code freezes |
| E-stop contact B | firmware | fault: clipper off, guard goes to its longest length |
| Force pads | firmware + PC | clipper off unless BOTH pads are pressed (the cutter is on the head) |
| Permit lease | firmware | the laptop must re-allow the clipper every 20 ms; if it stops, the clipper is off within 150 ms |
| Guard jam | firmware | motor driven but the encoder doesn't move → fault (screw drive) |
| **Wrong spot** | PC, 50 Hz | clipper off while the guard isn't within ±1 mm of the length this spot needs |
| Tags vs IMU | PC | clipper off if the camera's tags and the IMU disagree about where the cutter is by > 20° |
| No-cut zones | PC | clipper off near the face and ears (trim those by hand) |
| Lost sensor | PC | clipper off if the IMU stops working |
| Unexpected clipper | PC | if the board reports the clipper on without permission → full stop |

Testing: mannequin heads and balloons until RASTIC signs off. First human tests: team members, longest length.

## 6. Things you'll tune
- `pc/config.py` — `FSR_ON` / `FSR_OFF`, the tag positions `TAGS` and size `TAG_SIZE_MM`, `GUARD_TOL`,
  `MARKER_GAIN` (how fast tags correct the IMU), `LOC_DISAGREE_DEG`, coverage settings.
- `pc/styles.py` — add hairstyles from the barber interviews (each = 5 lengths + optional fade, 12.7–44.45 mm).
- `pc/orientation.py` — the no-cut zone table (`ZONE_YAW` / `ZONE_PITCH`).
- Firmware — everything marked MEASURE once the motor/servo arrives.

AI disclosure: initial code and design generated with Claude (Anthropic) and reviewed and modified by the team.
