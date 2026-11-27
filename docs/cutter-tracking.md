# Where is the cutter on the head?

*Updated Nov 26, 2026. Replaces the "rolling" design. Code: `pc/cutter_tracking.py`, `pc/controller.py`,
`pc/vision/cutter_tags.py`, `pc/camera_head.py`, firmware `firmware/hairbarbot_handheld/`.*

## What changed and why

We used to assume the cutter **rolls** over the head on two rollers. With Carlos's guard design (outer guard on
rails, [guard-drive-options.pdf](guard-drive-options.pdf)) and from what we've seen online, the cutter gets
**picked up and placed** on the head at one spot after another. The guard drive is also slow (D2.2 screw:
~5–7 s for the full 31.75 mm stroke), so the guard changes length mostly between placements.

Locating the cutter with the IMU alone has two weak spots: (1) it only works when the cutter sits flat on the
head, and (2) its heading drifts and the calibration is only as good as the user's aim. The plan is to combine
three sensors:

| Sensor | Answers | Good at | Weak at |
|---|---|---|---|
| **IMU** (BNO085 on the cutter) | which way is the cutter pointing? → which spot (when seated) | works anywhere, incl. the back of the head; 100 Hz | heading drifts slowly; wrong if the cutter isn't flat |
| **2 force sensors** (FSRs in the scalp face, top-left + bottom-right) | is the cutter actually sitting flat on the head? | cheap, instant, simple | says nothing about *where* |
| **ArUco tags** (3 plates: left, right, rear) seen by the camera | where is the cutter relative to the head, in mm? | accurate, no drift | only when the camera sees a tag *and* the face; not at the back |

> A note on "orientation only": the old method never actually relied on rolling. It relied on the cutter
> pointing along the scalp's surface normal, which is true whenever it's **seated flat**. The force pads now
> *confirm* that, so the IMU method still works between tag sightings. What the tags fix is the IMU's drift and
> calibration error, and they give a direct position check.

## How they're combined (every 20 ms)

```
          force pads ──► seated?  (both pads above FSR_ON, for 0.15 s)
                                     │
 camera ─► face pose ┐               ▼
         ─► tag pose ┴► sighting ──► CutterFusion ──► spot (yaw, pitch) + "tags" or "imu"
                       (head axes)      ▲     │
 IMU ─► direction ─► calibration M ─────┘     └─► correction C learned from each sighting
                     (+ head turns from the camera)
```

1. **Seated?** Both pads pressed (with hysteresis: on above `FSR_ON`, off below `FSR_OFF`) for
   `CONTACT_SETTLE_S`. The firmware *also* refuses to run the clipper unless both pads read above `FSR_MIN_FW`.
2. **Tag sighting** (camera picture with the face and ≥1 tag): solvePnP on all visible tag corners gives the
   cutter's pose in the camera; the face tracker gives the head's pose in the same picture; together →
   the scalp-face center and the cutter's axis in **head axes**. Sightings whose point is more than
   `MARKER_MAX_ERR_MM` off the head surface, or that don't point into the head, are thrown away (misreads, or
   the cutter in the air). Consecutive sightings of a still cutter are averaged to cut noise.
3. **Location:**
   - fresh sighting (< `MARKER_FRESH_S`) → the spot comes from the **tags**;
   - but if the IMU says the cutter has turned more than 3° since that sighting, it's stale → use the IMU;
   - no sighting → the **IMU**, corrected by C.
4. **Learning C:** each new sighting while seated nudges C (by `MARKER_GAIN`) so the IMU's direction lines up
   with the tags. Mostly a turn about the vertical, because that's what a gyro-based IMU drifts in and one
   sighting is enough to see it; a slower general part fixes calibration aim error.
5. **Disagreement:** after 5 sightings the IMU is "trusted". If tags and IMU then disagree by more than
   `LOC_DISAGREE_DEG` (20°), the clipper stays off ("unsure") and C is not updated from that sighting (a
   misread tag can't teach the IMU something wrong).

The clipper runs only if: E-stop OK, location known, **seated**, tags and IMU agree, not in a no-cut zone,
guard within `GUARD_TOL` (1 mm) of this spot's length, trigger held (plus the firmware's own checks).
Coverage only counts while seated with the clipper on. When the cutter is lifted, the guard keeps its length.

## Coordinates

**HairBarbot head axes:** x forward (nose), y to the client's **left**, z up; origin = head center (between the
ears, a bit above them); mm. Spots: **yaw** around the head (0 face, +90 left, 180 back), **pitch** down from
the crown (90 = ear level). Same as `vision/head_profile.py`.

**Cutter axes** (for `TAGS` in `pc/config.py`): origin = center of the scalp face; z = into the scalp; x = toward
the back of the Flowbee (hose side); y = z × x. For each tag: its center, which way the printed face points
(`normal`) and which way the top edge of the printed tag points (`up`). **The numbers in `config.py` are
placeholders: measure them from the CAD.**

## iPhone hand-off (for Bryson)

The iPhone app already tracks the head much better than the webcam (depth-corrected FLAME head, a few mm).
If it also finds the tags, it can send each sighting to the controller:

```
POST http://<laptop>:5000/api/cutter
{"point_mm": [x, y, z],   // center of the cutter's scalp face, HairBarbot head axes
 "axis":     [x, y, z],   // direction the cutter points INTO the scalp, HairBarbot head axes
 "age_s":    0.03,        // seconds since the camera frame
 "tags":     2}           // tags seen (optional)
→ {"ok": true, "accepted": true}
```

Things to settle:
- **Frame mapping:** the saved FLAME head / ARKit face frame → HairBarbot head axes (axis directions and where
  the origin is). A quick check: send the cutter's position at the crown, the left ear and the nose tip and
  confirm `/api/state` reports yaw/pitch ≈ (0, 0), (90, 90), (0, ~100).
- **Tag layout:** use the same dictionary (`DICT_4X4_50`), ids (0 left, 1 right, 2 rear) and positions as
  `TAGS` in `pc/config.py`, so there's one source of truth.
- **Latency:** sightings older than `MARKER_FRESH_S` (0.25 s) are ignored.
- Later the same JSON can go over Bluetooth instead of Wi-Fi (`CutterConnection` in the user app).

## What's tested (simulation only, not on hardware yet)

`pc/tests/test_cutter_tracking.py` and `test_sim.py`:
- tag pose from rendered pictures: within ~3 mm / 1.5° with two tags in view, ~8 mm / 5° with one;
- the simulated IMU drifts 40°/min (sped up): with tags the back-of-head spot is within 2.5°, without tags off by more than 5°;
- a lifted or rocked cutter (one pad off) never cuts;
- a misread tag far off the head is rejected; one on the head but in the wrong place stops the clipper and
  doesn't corrupt the IMU correction;
- a whole simulated haircut (163 placements): the clipper never runs on the head with the guard more than
  2.5 mm off what that spot needs, or in a no-cut zone.

## Open questions / to measure

- **Tag positions and size** on Carlos's tag plates → `TAGS`, `TAG_SIZE_MM`. Print with
  `python3 pc/vision/cutter_tags.py --print tags.png`, check the 50 mm bar.
- **FSR thresholds** with the real pads and guard face (bench test `f`).
- **Webcam head pose is the weakest link:** our 5-point webcam pose is rougher than the iPhone's depth-corrected
  pose (Bryson measured Apple's face pose alone 8–21 mm off). Camera intrinsics are guessed from a field of
  view; a proper camera calibration would help. Long term the iPhone should be the camera.
- **Will the tags stay visible?** Hair, hands and the Flowbee hose can cover them; tags are small at 40–60 cm.
  Bigger tags or more plates if needed.
- **Guard speed vs. workflow:** with D2.2 (~5 mm/s) the user waits while the guard adjusts at a new region.
  Fine if the length only changes between regions (Carlos's question 1).
- **Hardware list:** this code follows Carlos's sensor box (XIAO ESP32-S3 + BNO085). Our scrum email to
  Prof. Sebesta mentioned other parts, but the course isn't ordering for us, so we use what we have; adjust the pins and IMU library if the parts on hand differ.
