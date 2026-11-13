"""Where on the head is the clipper? Worked out from two orientation sensors (BNO055).

Idea: the head is roughly a sphere, and the Flowbee is always held pointing INTO the scalp.
So the direction the clipper points (reversed) is the direction from the head center to the
spot being cut. If we know that direction in the HEAD's frame, we know the spot:
  yaw   = which way around the head (0 = face, +90 = client's left, 180 = back)
  pitch = how far down from the crown (0 = crown, 90 = ear level)

  n_world = -R_clip @ CLIP_AXIS      direction from head center to the spot, in world axes
  v       =  R_head.T @ n_world      same direction in the headband sensor's axes
  n_head  =  M @ v                   same direction in head axes (M comes from calibration)

Head frame: x forward (nose), y to the client's LEFT, z up.

Calibration: the user holds the clipper at 3-4 known spots (top, back, left, right).
Each gives a pair (v measured, n_head known). M is the rotation that best maps one set
onto the other (Kabsch / Wahba). That also absorbs however the headband sensor is mounted.
"""
import math

import numpy as np

import config


def quat_to_matrix(q):
    """(w, x, y, z) -> 3x3 rotation matrix (sensor axes -> world axes)."""
    w, x, y, z = q
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def matrix_to_quat(R):
    t = np.trace(R)
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        return ((0.25 * s), (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s)
    i = int(np.argmax([R[0, 0], R[1, 1], R[2, 2]]))
    if i == 0:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        return ((R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s)
    if i == 1:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        return ((R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s)
    s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
    return ((R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s)


def direction(yaw, pitch):
    """(yaw, pitch) on the head -> unit vector in head axes."""
    y, p = math.radians(yaw), math.radians(pitch)
    return np.array([math.sin(p) * math.cos(y), math.sin(p) * math.sin(y), math.cos(p)])


def yaw_pitch(n):
    n = np.asarray(n, dtype=float)
    n = n / (np.linalg.norm(n) or 1.0)
    return math.degrees(math.atan2(n[1], n[0])), math.degrees(math.acos(max(-1.0, min(1.0, n[2]))))


def measured_vector(q_clip, q_head):
    """Direction to the spot being cut, in the headband sensor's axes (before calibration)."""
    a = np.array(config.CLIP_AXIS, dtype=float)
    n_world = -quat_to_matrix(q_clip) @ a
    v = quat_to_matrix(q_head).T @ n_world
    return v / (np.linalg.norm(v) or 1.0)


def locate(q_clip, q_head, M):
    """-> (yaw, pitch) of the spot being cut, in degrees."""
    return yaw_pitch(M @ measured_vector(q_clip, q_head))


def calibrate(pairs):
    """pairs: list of (v_measured, n_head_known). Returns (M, worst_error_deg).
    Kabsch: rotation M minimizing sum |M v - n|^2."""
    if len(pairs) < 3:
        raise ValueError("Record at least 3 calibration spots.")
    V = np.array([p[0] for p in pairs])
    N = np.array([p[1] for p in pairs])
    H = V.T @ N
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    M = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    errs = [math.degrees(math.acos(max(-1.0, min(1.0, float((M @ v) @ n))))) for v, n in pairs]
    return M, max(errs)


# ---- no-cut zones: keep the clipper off near the face and ears.
# Lowest the clipper may go (pitch, degrees from the crown) at each angle around the head.
# Linear between points (no sudden steps), so a few degrees of sensor error near a boundary
# can't suddenly allow cutting much lower.
ZONE_YAW = [0, 50, 62, 80, 115, 128, 145, 180]       # |yaw|: 0 = face, 90 = ear, 180 = back
ZONE_PITCH = [55, 55, 70, 75, 75, 90, 105, 105]      # forehead, temples, above ear, behind ear, nape


def max_pitch(yaw: float) -> float:
    return float(np.interp(abs(yaw), ZONE_YAW, ZONE_PITCH))


def in_cut_zone(yaw: float, pitch: float) -> bool:
    return pitch <= max_pitch(yaw) - config.ZONE_MARGIN
