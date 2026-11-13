"""HairBarbot handheld settings. Units: degrees, millimeters, seconds.

Guard limits MUST match the firmware (hairbarbot_handheld.ino).
"""

# ---- Hardware connection
SERIAL_PORT = "/dev/ttyUSB0"   # Windows: "COM3", Mac: "/dev/cu.usbserial-XXXX" or "/dev/cu.SLAB_USBtoUART"
BAUD = 115200

# ---- Guard (comb length = hair length left after cutting)
GUARD_MIN, GUARD_MAX = 3.0, 60.0

# ---- Sensors
# Direction the clipper points INTO the scalp, in the clipper IMU's own axes.
# Mount the clipper BNO055 so its Z axis points from the clipper toward the scalp -> (0, 0, 1).
# If you mount it differently, change this (e.g. (1, 0, 0) if its X axis points at the scalp).
CLIP_AXIS = (0.0, 0.0, 1.0)
# Roller encoder: the device counts as "rolling on the head" above this speed (mm/s).
# Only rolled areas count toward coverage.
ROLLING_MIN_SPEED = 5.0

# ---- Calibration: where the user holds the device for each pose (yaw, pitch on the head).
# There's no headband, so this assumes the head stays upright and facing the same way during the cut.
# yaw 0 = face, +90 = client's LEFT, 180 = back.  pitch 0 = crown, 90 = ear level.
CALIB_POSES = [
    ("Top of the head", 0.0, 0.0),
    ("Back of the head", 180.0, 80.0),
    ("Left side, above the ear", 90.0, 65.0),
    ("Right side, above the ear", -90.0, 65.0),
]
CALIB_MAX_ERROR_DEG = 15.0     # reject a calibration whose poses disagree by more than this

# ---- Cutting
GUARD_TOL = 1.5                # clipper pauses if the guard is this far from the length this spot needs (mm)
ZONE_MARGIN = 0.0              # extra degrees of no-cut margin around face/ears
COVER_RADIUS_DEG = 12.0        # area one pass of the Flowbee head covers (~40 mm wide)
COVER_DWELL_S = 0.25           # time a spot needs under the running clipper to count as cut
COVER_DONE = 0.97              # session ends automatically at this coverage
LOOP_HZ = 50

# ---- Safety (PC side)
STATUS_STALE_S = 0.5           # no status from the board for this long -> stop
UNEXPECTED_CLIP_S = 0.3        # board reports clipper on without our permit for this long -> stop
