# BarBot: developer test app (iPhone)

**BarBot is our developer testing app.** Everything in `ios/BarBot/` was built to try
out and measure the pieces HairBarbot needs on an iPhone: 3D head scanning, fitting a
head model, and live head tracking. It shows the engineering on purpose: raw numbers,
colored error dots, debug toggles, test recorders and log files.

**It is not the app users will see.** What we learn here will go into a separate
**user-facing app** that hides this machinery behind a simple flow (scan once, then
cut). The user-facing app will reuse the parts that worked (mostly the code in the
StandardCyborg fork, see below) rather than this app's screens.

## What's in the test app

| Tab | What it's for |
|---|---|
| **Scan** | Scan a head with the front 3D camera (StandardCyborg), save scans as PLY files with gravity, name and label them (front/left/right/back), merge scans, and **Fit Head Model**: fit the FLAME head model to a scan, test it against another scan, and **Save → Use for Tracking**. Saved heads are listed at the bottom. |
| **Track** | Live head tracking with Apple's face tracking (ARKit). **Line Up** the saved head with your face once; then the whole head is drawn on the camera picture. Buttons: **Mask** (Apple's face mask), **Head** (drawn head + opacity), **Depth** (live depth check: measured points colored blue / green / red by distance from the head, per-region errors), **Fix** (depth-corrected pose), **Smooth** (One Euro filter). **Record** runs 10-second tests and logs the results. |
| **Depth Check** | The first test: the distance from the front 3D camera to the center of the picture, checked against a tape measure. |

Files the app writes (all visible in the Files app under **On My iPhone → BarBot**):
`Scans/*.ply`, `Heads/*.json` (saved heads: FLAME shape numbers + line-up),
`Heads/*.obj` (exported meshes), `TrackLogs/track-log.csv` (test runs).

## How head tracking works (current best version)

1. **Scan** the head with a swim cap on, then **fit** the FLAME head model to the scan.
   This gives the full head, including the back the camera can't see during a haircut.
2. **Line up** once: Apple's face mask is snapped onto the fitted head's face.
3. **Every frame (60/s):** Apple's face pose + the line-up places the head.
4. **Every depth picture (15/s), the "Fix":** the measured depth points on the face,
   nose and ears are snapped onto the head model. The small move this takes corrects
   Apple's pose.
5. **Smooth** with a One Euro filter: smooths heavily when still, lightly when moving.

## What we've learned so far

These findings should shape the user-facing app:

- **Apple's face pose alone is not accurate enough for cutting.** Compared with the
  measured depth, Apple's face sat 8–21 mm off and up to ~6° turned, and the error
  changes as the head turns. Correcting it with the depth camera (Fix) brought the
  regions it doesn't use for the correction (forehead, scalp) to within a few mm at
  every angle we tried.
- **Scan with a cap.** With hair, the fitted head followed the hair (forehead ~1 cm
  too far out). With a swim cap the forehead lined up to about 0.3 mm on average and
  the scalp to about 5 mm rms.
- **The depth camera's noise floor is about ±2 mm** at 40–50 cm. Single readings
  flicker at that level; averages over time are much better.
- **Tracking needs the face in view.** Beyond about 60° of head turn Apple's tracking
  stops. The phone has to stay in front of the person.
- **Scan slowly.** Turning too fast makes the scanner lose tracking.
- Remove earbuds and similar for tests; they show up as errors on the ears.

Next: run the recorded tests (steadiness, expressions, known turns), then check the
whole chain against real cutter touch points once the cutter's position relative to
the phone is known.

## Code map

| Where | What |
|---|---|
| `ios/BarBot/BarBot/` | The test app (SwiftUI). `ScanView`, `HeadFitView`, `TrackView`, `DepthCheck`, `LineUp`, `OneEuroFilter`, `TrackRecorder`, … |
| `ios/BarBot/BarBot/HeadModel/` | `FLAMEHead.bin` (committed) and `FLAMEMasks.bin` (generate locally, see `tools/flame/README.md`) |
| `ios/Vendor/StandardCyborgCocoa/` | Our fork of StandardCyborg (git submodule, [brysonmedd/StandardCyborgCocoa](https://github.com/brysonmedd/StandardCyborgCocoa)): scanning, gravity in scans, scan merging (`SCPointCloudMerging`), head model fitting, face line-up, surface check and depth snap (`SCHeadModelFitting`). **The reusable core for the user-facing app.** |
| `tools/flame/` | Converts the FLAME download into the app's model files |
| `docs/ios-test-log.md` | Results of hands-on tests |

## Building

Open `ios/BarBot/BarBot.xcodeproj` in Xcode, pick your iPhone, and press ⌘R. Before
the first build, run `git submodule update --init` and generate `FLAMEMasks.bin`
(see `tools/flame/README.md`). Needs an iPhone with a front 3D (TrueDepth) camera.
With a free Apple developer account, installed builds stop working after 7 days.
