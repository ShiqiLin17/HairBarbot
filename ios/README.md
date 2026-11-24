# iPhone apps: BarBot (developer test app) and HairBarbot (user app)

One Xcode project, `ios/BarBot/BarBot.xcodeproj`, builds two apps:

- **HairBarbot** (`ios/BarBot/HairBarbot/`): the **user-facing app**. See
  [HairBarbot: the user app](#hairbarbot-the-user-app) below.
- **BarBot** (`ios/BarBot/BarBot/`): the **developer test app**, described first.

Code both apps use is in `ios/BarBot/Shared/`.

## BarBot: developer test app

**BarBot is our developer testing app.** Everything in `ios/BarBot/` was built to try
out and measure the pieces HairBarbot needs on an iPhone: 3D head scanning, fitting a
head model, and live head tracking. It shows the engineering on purpose: raw numbers,
colored error dots, debug toggles, test recorders and log files.

**It is not the app users will see.** What we learn here goes into the separate
**user-facing app, HairBarbot**, which hides this machinery behind a simple flow (scan
once, then cut). HairBarbot reuses the parts that worked (the StandardCyborg fork and
`Shared/`) rather than this app's screens.

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

## HairBarbot: the user app

A guided app with no engineering numbers on screen. Its look follows
[`design/`](../design/README.md): colors only from `Color.brand` (the generated
`design/ios/BrandColors.swift`, which the target uses in place), red only for safety.

| Screen | What the user sees |
|---|---|
| **Home** | Cutter card (**Connect**: placeholder, Bluetooth comes later), **Start Haircut**, **Scan a New Head**, and **People** (saved heads; tap for a 3D view, **Rescan**, **Delete**). |
| **Scan** | Get ready (swim cap, no glasses/earbuds, light, phone on a stand) → how scanning works (go slowly; play each sound: tick = good, low beep = slow down, chime = done) → **Scan 1: turn right** until the sounds stop → check it → **Scan 2: turn left** → check the merge of 1 + 2 → **Scan 3: hold the phone and raise it over the head** → check the merge of all three → the head model is fitted → **save under the person's name**. Each check screen has **Redo** for the latest scan only. A spoken 5-second countdown, spoken prompts, and a chime when a scan ends, since the person can't see the screen while turning. |
| **Haircut** | Choose the person → choose a style (**placeholder**) → ready screen (**placeholder** for the cutting screen: line-up, live tracking, STOP button). |

Saved data: the fitted head as `Heads/<name>.json` (same format as BarBot's saved heads)
and the merged scan as `Scans/<name>-merged.ply`. Scans in progress are kept in
`CurrentScan/` until Save. All visible in the Files app under **On My iPhone → HairBarbot**
(on for now, for testing).

## Code map

| Where | What |
|---|---|
| `ios/BarBot/HairBarbot/` | The user app (SwiftUI). `HomeView`, `ScanFlow` (the scan steps) + `ScanFlowView`, `GuidedScanView`, `HaircutFlowView`, `CutterConnection` (placeholder), `BrandStyles` |
| `ios/BarBot/BarBot/` | The test app (SwiftUI). `ScanView`, `HeadFitView`, `MergeView`, `TrackView`, `DepthCheck`, `OneEuroFilter`, `TrackRecorder`, … |
| `ios/BarBot/Shared/` | Used by both apps: `ScanStore`, `HeadStore` (saved heads), `ScanSounds`, `Merger`, `HeadFitting` (model loading, fitting, head mesh view), `LineUp` |
| `ios/BarBot/Shared/HeadModel/` | `FLAMEHead.bin` (committed) and `FLAMEMasks.bin` (generate locally, see `tools/flame/README.md`) |
| `ios/Vendor/StandardCyborgCocoa/` | Our fork of StandardCyborg (git submodule, [brysonmedd/StandardCyborgCocoa](https://github.com/brysonmedd/StandardCyborgCocoa)): scanning, gravity in scans, scan merging (`SCPointCloudMerging`), head model fitting, face line-up, surface check and depth snap (`SCHeadModelFitting`). **The reusable core for the user-facing app.** |
| `tools/flame/` | Converts the FLAME download into the app's model files |
| `docs/ios-test-log.md` | Results of hands-on tests |

## Building

Open `ios/BarBot/BarBot.xcodeproj` in Xcode, pick the **HairBarbot** or **BarBot**
scheme and your iPhone, and press ⌘R. Before
the first build, run `git submodule update --init` and generate `FLAMEMasks.bin`
(see `tools/flame/README.md`). Needs an iPhone with a front 3D (TrueDepth) camera.
With a free Apple developer account, installed builds stop working after 7 days.
