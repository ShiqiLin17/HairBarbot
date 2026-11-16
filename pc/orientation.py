"""Where on the head is the device? Worked out from ONE orientation sensor (BNO055) on the device.

Idea: the head is roughly a sphere, and the Flowbee is always held pointing INTO the scalp.
So the direction the device points (reversed) is the direction from the head center to the
spot being cut. If we know that direction in the HEAD's frame, we know the spot:
  yaw   = which way around the head (0 = face, +90 = client's left, 180 = back)
  pitch = how far down from the crown (0 = crown, 90 = ear level)

  n_world = -R_device @ CLIP_AXIS    direction from head center to the spot, in world (room) axes
  n_head  =  M @ n_world             same direction in head axes (M comes from calibration)

No headband: we assume the head stays upright and facing the same way as during calibration.
The BNO055 gives orientation relative to gravity + magnetic north, so tilt (top vs sides) is solid;
"which side" relies on the compass heading, so keep the head still and away from big metal objects.

Head frame: x forward (nose), y to the client's LEFT, z up.

Calibration: the user holds the device at 3-4 known spots (top, back, left, right).
Each gives a pair (v measured, n_head known). M is the rotation that best maps one set
onto the other (Kabsch / Wahba). It captures which way the user is facing in the room.
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


def measured_vector(q_device, q_head=None):
    """Direction from the head center to the spot being cut, in room axes (before calibration).
    q_head is optional (for a future headband sensor); without it the head is assumed still."""
    a = np.array(config.CLIP_AXIS, dtype=float)
    v = -quat_to_matrix(q_device) @ a
    if q_head is not None:
        v = quat_to_matrix(q_head).T @ v
    return v / (np.linalg.norm(v) or 1.0)


def locate(q_device, M, q_head=None):
    """-> (yaw, pitch) of the spot being cut, in degrees."""
    return yaw_pitch(M @ measured_vector(q_device, q_head))


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


def set_forehead_limit(pitch):
    """Use this person's forehead hairline (pitch from the crown, measured by the camera) for the front
    no-cut line instead of the average 55 deg. Clamped to a sensible range."""
    p = float(max(45.0, min(65.0, pitch)))
    ZONE_PITCH[0] = ZONE_PITCH[1] = p
    return p


def reset_zones():
    ZONE_PITCH[:] = [55, 55, 70, 75, 75, 90, 105, 105]


# ---- locating on the REAL head shape
class SurfaceLocator:
    """Finds the spot on the head whose surface faces a given direction.

    The device is pressed flat against the head, so it points along the surface normal at the spot it's on.
    On a round head the normal points straight out from the center, so direction = spot. On a real head
    (longer than it is wide, flatter on the sides) they differ by up to ~10-15 deg, so with a head profile
    (average size, measured, or a 3D scan) we look up the spot whose normal matches."""

    def __init__(self, profile=None, step=2.0):
        self.profile = profile
        if profile is None:
            return
        spots, normals = [], []
        for p in np.arange(0.0, 125.0 + 1e-9, step):
            for y in np.arange(-180.0, 180.0, step if p > 0 else 360.0):
                _, n = profile.surface(float(y), float(p))
                spots.append((float(y), float(p)))
                normals.append(n)
        self.spots = np.array(spots)
        self.normals = np.array(normals)

    def spot(self, n_head):
        """Outward surface direction in head axes -> (yaw, pitch) of the spot."""
        if self.profile is None:
            return yaw_pitch(n_head)
        n = np.asarray(n_head, float)
        dots = self.normals @ (n / (np.linalg.norm(n) or 1.0))
        top = np.argpartition(-dots, 6)[:6]                 # the 6 grid spots facing closest to n
        ang = np.arccos(np.clip(dots[top], -1.0, 1.0))
        w = 1.0 / (ang + 1e-4) ** 2                        # blend them, closest counts most
        best = top[np.argmax(dots[top])]
        y0 = self.spots[best, 0]
        dy = (self.spots[top, 0] - y0 + 180.0) % 360.0 - 180.0
        if self.spots[best, 1] < 4.0:                      # at the crown yaw is meaningless: don't blend it
            dy = dy * 0.0
        yaw = (y0 + float(np.sum(w * dy) / np.sum(w)) + 180.0) % 360.0 - 180.0
        pitch = float(np.sum(w * self.spots[top, 1]) / np.sum(w))
        return yaw, pitch

    def normal(self, yaw, pitch):
        """Direction the device points when held flat at (yaw, pitch) (for calibration targets)."""
        if self.profile is None:
            return direction(yaw, pitch)
        return self.profile.surface(yaw, pitch)[1]
