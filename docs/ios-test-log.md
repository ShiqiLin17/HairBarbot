# iOS App Test Log

Results of hands-on tests of the BarBot iPhone app, newest last.

## Setup used

| Item | Version |
|---|---|
| Phone | iPhone 17 Pro, iOS 26.6.2 |
| Xcode | 26.6 (17F113) |
| macOS | 26.5.1 |
| App | BarBot, commit `5cd0b22` (depth-check screen) |

## Test 1: TrueDepth distance check (Step 1), 2026-11-17

**Goal:** the center distance shown in the app matches a tape measure within 1 cm at 30, 40 and 50 cm.

**Method:**
- Phone screen faced a cardboard box (flat, matte).
- Distances were marked on the floor with masking tape.
- Measured from the top edge of the phone, where the camera is.
- Three readings at each distance using the Hold button.
- The app reports the median of a 9×9 patch at the center of the depth map, with Apple's depth smoothing on.

**Results:**

| Tape | Reading 1 | Reading 2 | Reading 3 | Average error | Spread |
|---|---|---|---|---|---|
| 30 cm | 30.2 | 30.0 | 30.1 | +0.1 cm | 0.2 cm |
| 40 cm | 40.0 | 40.0 | 40.0 | 0.0 cm | 0.0 cm |
| 50 cm | 49.5 | 49.6 | 49.7 | −0.4 cm | 0.2 cm |

**Result: PASS.** The largest error was 0.5 cm and every reading was within 1 cm.

**Notes:**
- Repeatability is about 2 mm.
- At 50 cm the readings ran slightly short (−0.4 cm). This may be how the marks were made, or the camera losing a little accuracy with distance. It doesn't matter for head scanning, which happens at about 30–40 cm.
- Re-check with a firmer setup (a rigid ruler, or a phone clamped to a stand) if later scans show scale errors.
