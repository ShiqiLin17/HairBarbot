"""HairBarbot settings. Units: degrees, millimeters, seconds.

Joint limits and the forbidden-zone table MUST match the firmware (hairbarbot_firmware.ino).
"""

# ---- Hardware connections
SERIAL_PORT = "/dev/ttyACM0"   # Windows: "COM3", Mac: "/dev/cu.usbmodemXXXX"
BAUD = 115200
CAMERA_INDEX = 0               # webcam that looks at the client's face

# ---- Joint limits (same as firmware)
YAW_MIN, YAW_MAX = -170.0, 170.0
PITCH_MIN, PITCH_MAX = -12.0, 112.0
RAD_MIN, RAD_MAX = 0.0, 110.0
GUARD_MIN, GUARD_MAX = 3.0, 40.0

# ---- Geometry
# Distance from the head center (where yaw axis and arc center meet) to the CLIPPER BLADE
# when the radial slide is at 0. Comb tip = blade - guard length.
# Measure this on the real machine and update it (see README "Calibrate D0").
D0 = 175.0

# Default head model: ellipsoid semi-axes (mm) measured to the scalp surface through the hair.
HEAD_A_FRONT_BACK = 100.0
HEAD_B_SIDE = 78.0
HEAD_C_TOP = 112.0

# ---- Cutting path
STROKE_YAW_STEP = 15.0      # degrees between strokes (comb ~40 mm wide -> ~22 deg at r=100, so overlap)
STROKE_PITCH_STEP = 5.0     # degrees between waypoints along a stroke
ZONE_MARGIN = 3.0           # planner stays this many degrees inside the allowed zone
MAX_GUARD_STEP = 1.0        # guard may change at most this much between waypoints (mm)
APPROACH_GAP = 20.0         # how far (mm) the comb sits off the head before plunging in
FEED_TRAVEL = 40            # % of max speed for moves with the clipper off
FEED_PLUNGE = 15
FEED_CUT = 20

# ---- Safety thresholds (PC side)
GUARD_TOL = 1.5             # guard error allowed vs the haircut plan at the current spot (mm)
DEPTH_TOL = 6.0             # comb may sit at most this far inside the head model (mm)
HEAD_MOVE_MM = 8.0          # head moved more than this since calibration -> stop
HEAD_ROT_DEG = 6.0          # head turned more than this -> stop
FACE_LOST_S = 0.3           # no face seen for this long -> stop
WATCHDOG_HZ = 50
