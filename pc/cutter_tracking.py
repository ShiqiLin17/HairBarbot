"""Where is the cutter on the head? Combines the IMU with ArUco tag sightings.

The cutter is picked up and placed on the head at one spot after another. Three things tell us where it is
(see docs/cutter-tracking.md):

  1. IMU (always available): which way the cutter points. When it sits FLAT on the head it points along
     the scalp's normal, so its direction picks out the spot (orientation.SurfaceLocator). Weaknesses: it
     only works when the cutter is seated flat, its heading drifts slowly, and the calibration is only as
     good as the user's aim.
  2. Force sensors: say whether the cutter IS seated flat (both pads pressed). Checked by the controller.
  3. ArUco tags on the cutter, seen by a camera that also tracks the head (Python + webcam now, or the
     iPhone app later): where the cutter's scalp face is RELATIVE TO THE HEAD, in mm. Accurate, but only
     while the camera sees a tag and the face, so not at the back of the head.

How they're combined:
  - Tag seen now  -> the spot comes from the tags (where the cutter touches the head).
  - Every tag sighting while the cutter is seated also nudges a small correction rotation C so the
    IMU's direction matches the tags' direction (like a complementary filter). Mostly a turn about the
    vertical, because that's the part of an IMU that drifts (tilt is measured against gravity and doesn't),
    and one sighting is enough to see it. A slower general part also fixes calibration aim error.
  - Tag not seen (back of the head, hand in the way) -> the spot comes from the corrected IMU.
  - If both are available and disagree a lot, something is wrong (a tag misread, a bump, a bad
    calibration): the controller keeps the clipper off until they agree again.

Frames: everything here is in HEAD axes (x forward/nose, y to the client's left, z up, origin = head center,
mm), the same frame as vision/head_profile.py.
"""
import math
import threading
import time

import numpy as np

import config
from orientation import angle_between, axis_angle, rot_from_to


def _partial(R, gain):
    """The same rotation as R, but only `gain` (0..1) of the way."""
    c = max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))
    ang = math.degrees(math.acos(c))
    if ang < 1e-6:
        return np.eye(3)
    axis = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    if np.linalg.norm(axis) < 1e-9:
        return np.eye(3)
    return axis_angle(axis, ang * gain)


def _orthonormalize(R):
    U, _, Vt = np.linalg.svd(R)
    return U @ Vt


class Sighting:
    """One look at the cutter from a camera, already in head axes."""
    __slots__ = ("t", "point", "axis", "spot", "surface_err", "source", "n_tags")

    def __init__(self, t, point, axis, spot, surface_err, source, n_tags=1):
        self.t, self.point, self.axis = t, point, axis
        self.spot, self.surface_err, self.source, self.n_tags = spot, surface_err, source, n_tags

    @property
    def outward(self):
        """Direction from the scalp outward through the cutter (what the IMU measures, see orientation.py)."""
        return -self.axis


class CutterFusion:
    def __init__(self, locator):
        self.locator = locator
        self.C = np.eye(3)                 # correction applied to the IMU direction (head axes)
        self.n_updates = 0                 # tag sightings used to correct the IMU
        self.last = None                   # latest accepted Sighting
        self.last_used_t = 0.0
        self.rejected = 0
        self.disagree = None               # degrees between IMU and tags, last time both were available
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.C = np.eye(3)
            self.n_updates = 0
            self.last = None
            self.disagree = None

    # ---------------------------------------------------------------- tag sightings
    def add_sighting(self, point_head, axis_head, t=None, source="camera", n_tags=1):
        """point_head: center of the cutter's scalp face (mm, head axes).
        axis_head: direction the cutter points INTO the scalp (head axes).
        Returns True if the sighting was accepted."""
        p = np.asarray(point_head, float)
        a = np.asarray(axis_head, float)
        if p.shape != (3,) or a.shape != (3,) or not np.all(np.isfinite(p)) or not np.all(np.isfinite(a)):
            raise ValueError("point and axis must be 3 numbers each")
        a = a / (np.linalg.norm(a) or 1.0)
        t = time.time() if t is None else t
        prev = self.last
        if prev is not None and 0 <= t - prev.t < 0.3 and np.linalg.norm(p - prev.point) < 5.0:
            # the cutter is holding still: average with the last sightings to smooth out the tag noise
            p = 0.7 * prev.point + 0.3 * p
            a = 0.7 * prev.axis + 0.3 * a
            a = a / (np.linalg.norm(a) or 1.0)
        spot, err = self.locator.spot_from_point(p)
        # a real touch is on the scalp and points into it; anything else is a misread or the cutter in the air
        n_surface = self.locator.normal(*spot)
        if err > config.MARKER_MAX_ERR_MM or angle_between(-a, n_surface) > 60.0:
            self.rejected += 1
            return False
        with self.lock:
            self.last = Sighting(t, p, a, spot, err, source, n_tags)
        return True

    def fresh(self, now=None):
        now = time.time() if now is None else now
        s = self.last
        return s if (s is not None and now - s.t <= config.MARKER_FRESH_S) else None

    # ---------------------------------------------------------------- location
    MOVED_DEG = 3.0      # the IMU says the cutter turned this much since the last tag sighting -> that sighting is stale

    def _correct(self, n_corr, target, up):
        """Nudge C so the IMU direction n_corr moves toward the tags' direction `target`."""
        C = self.C
        if up is not None:
            u = np.asarray(up, float) / (np.linalg.norm(up) or 1.0)
            a = n_corr - u * (n_corr @ u)
            b = target - u * (target @ u)
            if np.linalg.norm(a) > 0.25 and np.linalg.norm(b) > 0.25:     # not at the crown
                ang = math.degrees(math.atan2(float(u @ np.cross(a, b)), float(a @ b)))
                R = axis_angle(u, config.MARKER_GAIN * ang)
                C = R @ C
                n_corr = R @ n_corr
            gain = config.MARKER_GAIN / 4.0
        else:
            gain = config.MARKER_GAIN
        C = _partial(rot_from_to(n_corr, target), gain) @ C
        with self.lock:
            self.C = _orthonormalize(C)
            self.n_updates += 1

    def locate(self, n_imu_head, seated, now=None, up_head=None):
        """n_imu_head: outward direction from the IMU (head axes, after calibration), or None.
        seated: both force pads pressed (the cutter sits flat on the head).
        up_head: the room's vertical in head axes (the axis the IMU's heading drifts around), or None.
        -> (spot (yaw, pitch) or None, source "tags" | "imu" | None, disagree_deg or None)"""
        now = time.time() if now is None else now
        s = self.fresh(now)
        n_corr = None if n_imu_head is None else self.C @ np.asarray(n_imu_head, float)
        if s is not None and s.t > self.last_used_t:            # a new sighting
            self.last_used_t = s.t
            self._n_at_sight = n_corr
            if n_corr is not None and seated:
                dis = angle_between(n_corr, s.outward)
                self.disagree = dis
                if not (self.trusted() and dis > config.LOC_DISAGREE_DEG):
                    self._correct(n_corr, s.outward, up_head)        # each sighting corrects the IMU once
                # (a big disagreement after the IMU is trusted is more likely a misread tag: don't learn from it)
                return tuple(float(x) for x in s.spot), "tags", dis
            return tuple(float(x) for x in s.spot), "tags", None
        if s is not None:
            # same sighting as before: still good unless the IMU says the cutter has moved since
            moved = (n_corr is not None and getattr(self, "_n_at_sight", None) is not None
                     and angle_between(n_corr, self._n_at_sight) > self.MOVED_DEG)
            if not moved:
                return tuple(float(x) for x in s.spot), "tags", self.disagree if seated else None
        if n_corr is None:
            return None, None, None
        return tuple(float(x) for x in self.locator.spot(n_corr)), "imu", None

    def trusted(self):
        """The tags have corrected the IMU enough times that a big disagreement means a real problem."""
        return self.n_updates >= 5

    def info(self, now=None):
        now = time.time() if now is None else now
        s = self.last
        c = max(-1.0, min(1.0, (np.trace(self.C) - 1.0) / 2.0))
        return {"seen": bool(s is not None and now - s.t <= config.MARKER_FRESH_S),
                "last_seen_s": None if s is None else round(now - s.t, 1),
                "source": None if s is None else s.source,
                "tags": None if s is None else s.n_tags,
                "surface_err_mm": None if s is None else round(s.surface_err, 1),
                "imu_correction_deg": round(math.degrees(math.acos(c)), 1),
                "corrections": self.n_updates,
                "disagree_deg": None if self.disagree is None else round(self.disagree, 1),
                "rejected": self.rejected}
