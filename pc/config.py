"""HairBarbot cutter settings. Units: degrees, millimeters, seconds.

Guard limits MUST match the firmware (hairbarbot_handheld.ino).

Design (Nov 2026): the cutter is PICKED UP AND PLACED on the head at one spot after another (it does not
roll). Where it is comes from three things (see docs/cutter-tracking.md):
  1. IMU (BNO085) orientation: which way the cutter points = which spot it's on, when it sits flat
  2. two force sensors (FSRs) in the scalp face: is it actually pressed flat on the head?
  3. ArUco tags on the cutter, seen by the camera: where the cutter is relative to the head
"""

# ---- Hardware connection
SERIAL_PORT = "/dev/ttyUSB0"   # Windows: "COM3", Mac: "/dev/cu.usbmodemXXXX" (XIAO ESP32-S3 over USB)
BAUD = 115200

# ---- Guard (outer guard on the Flowbee = hair length left after cutting)
# Carlos's guard drive moves the outer guard from 1/2" to 1-3/4" (31.75 mm of stroke).
GUARD_MIN, GUARD_MAX = 12.7, 44.45

# ---- IMU on the cutter
# Direction the cutter points INTO the scalp, in the IMU's own axes.
# Mount the IMU so its Z axis points from the cutter toward the scalp -> (0, 0, 1).
# If you mount it differently, change this (e.g. (1, 0, 0) if its X axis points at the scalp).
CLIP_AXIS = (0.0, 0.0, 1.0)

# ---- Force sensors (2 FSRs in the scalp face, top-left and bottom-right). Raw ESP32 ADC counts, 0..4095.
# "On the head" = BOTH pads pressed. Two thresholds (hysteresis) so it doesn't flicker at the edge.
# Tune with the bench test: read the numbers with the cutter in the air, resting on a head, and pressed.
FSR_ON = 600                   # a pad counts as pressed above this
FSR_OFF = 400                  # ...and released below this
CONTACT_SETTLE_S = 0.15        # both pads must be pressed this long before the clipper may run

# ---- ArUco tags on the cutter (three tag plates: left, right, rear). Dictionary 4x4, 50 ids.
# Each tag: its id -> where its center sits on the cutter, which way its printed face points ("normal") and
# which way the TOP edge of the printed tag points ("up"), all in CUTTER axes:
#   origin = center of the scalp face (where the guard touches the head)
#   z = INTO the scalp (same as CLIP_AXIS), x = toward the back of the Flowbee (hose side), y = z cross x
# The numbers below are PLACEHOLDERS: measure them from Carlos's CAD once the tag plates are final.
TAG_DICT = "DICT_4X4_50"
TAG_SIZE_MM = 20.0             # black square edge length, as printed (measure the print!)
TAGS = {
    0: {"name": "left",  "center": (-10.0, -35.0, -30.0), "normal": (0.0, -1.0, 0.0), "up": (0.0, 0.0, -1.0)},
    1: {"name": "right", "center": (-10.0,  35.0, -30.0), "normal": (0.0,  1.0, 0.0), "up": (0.0, 0.0, -1.0)},
    2: {"name": "rear",  "center": ( 45.0,   0.0, -30.0), "normal": (1.0,  0.0, 0.0), "up": (0.0, 0.0, -1.0)},
}

# ---- Combining the IMU with the tags
MARKER_FRESH_S = 0.25          # a tag sighting counts as "now" for this long
MARKER_GAIN = 0.15             # how fast the IMU is pulled toward the tags each sighting (0..1)
MARKER_MAX_ERR_MM = 25.0       # ignore a tag sighting whose contact point is this far off the head surface
LOC_DISAGREE_DEG = 20.0        # tags and IMU disagree this much -> clipper pauses (something is wrong)
IMU_ONLY_WARN_S = 30.0         # IMU without a tag sighting for this long -> show a "show the cutter" hint

# ---- Calibration: where the user holds the device for each pose (yaw, pitch on the head).
# Only needed for the IMU before the camera has seen a tag; tag sightings then keep it corrected.
# yaw 0 = face, +90 = client's LEFT, 180 = back.  pitch 0 = crown, 90 = ear level.
CALIB_POSES = [
    ("Top of the head", 0.0, 0.0),
    ("Back of the head", 180.0, 80.0),
    ("Left side, above the ear", 90.0, 65.0),
    ("Right side, above the ear", -90.0, 65.0),
]
CALIB_MAX_ERROR_DEG = 15.0     # reject a calibration whose poses disagree by more than this

# ---- Cutting
GUARD_TOL = 1.0                # clipper stays off if the guard is this far from the length this spot needs (mm)
ZONE_MARGIN = 0.0              # extra degrees of no-cut margin around face/ears
COVER_RADIUS_DEG = 12.0        # area one placement of the Flowbee head covers (~40 mm wide)
COVER_DWELL_S = 0.4            # time a spot needs under the running clipper to count as cut
COVER_DONE = 0.97              # session ends automatically at this coverage
LOOP_HZ = 50

# ---- Safety (PC side)
STATUS_STALE_S = 0.5           # no status from the board for this long -> stop
UNEXPECTED_CLIP_S = 0.3        # board reports clipper on without our permit for this long -> stop
