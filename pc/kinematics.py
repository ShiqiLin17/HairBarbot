"""Kinematics for the HairBarbot arc machine.

The machine is a spherical robot centered on the client's head:
  yaw   - turntable rotation about the vertical axis through head center
  pitch - position along the arc (0 = crown, 90 = ear level)
  rad   - radial slide toward the head
So inverse kinematics is just spherical coordinates. The one subtlety is that the comb
tip sits `guard` mm in front of the blade:  comb_tip_radius = D0 - rad - guard.

Head frame: x forward (nose), y to the client's LEFT, z up. Origin = head center.
"""
import math
from dataclasses import dataclass

import numpy as np

import config


def max_pitch(yaw: float) -> float:
    """Highest pitch the cutter may reach at this yaw. Keeps it off the face and ears.
    Same table as maxPitch() in the firmware."""
    a = abs(yaw)
    if a <= 50:
        return 55.0   # forehead hairline
    if a <= 70:
        return 70.0   # temples
    if a <= 115:
        return 75.0   # above the ear
    if a <= 135:
        return 90.0   # behind the ear
    return 105.0      # back of head / nape


def in_cut_zone(yaw: float, pitch: float, margin: float = 0.0) -> bool:
    return pitch <= max_pitch(yaw) - margin and pitch >= 0.0


def direction(yaw: float, pitch: float) -> np.ndarray:
    y, p = math.radians(yaw), math.radians(pitch)
    return np.array([math.sin(p) * math.cos(y), math.sin(p) * math.sin(y), math.cos(p)])


@dataclass
class HeadModel:
    """Ellipsoid scalp model centered on the head center."""
    a: float = config.HEAD_A_FRONT_BACK   # x (front/back)
    b: float = config.HEAD_B_SIDE         # y (sides)
    c: float = config.HEAD_C_TOP          # z (up)

    def radius(self, yaw: float, pitch: float) -> float:
        d = direction(yaw, pitch)
        return 1.0 / math.sqrt((d[0] / self.a) ** 2 + (d[1] / self.b) ** 2 + (d[2] / self.c) ** 2)

    @classmethod
    def fit(cls, points):
        """points: list of (yaw, pitch, r). Least squares on 1/r^2 = dx^2/a^2 + dy^2/b^2 + dz^2/c^2."""
        if len(points) < 3:
            raise ValueError("need at least 3 touch points")
        A = np.array([direction(y, p) ** 2 for y, p, _ in points])
        rhs = np.array([1.0 / r ** 2 for _, _, r in points])
        u, *_ = np.linalg.lstsq(A, rhs, rcond=None)
        if np.any(u <= 0):
            raise ValueError("touch points are inconsistent - redo calibration")
        a, b, c = (1.0 / math.sqrt(v) for v in u)
        for name, v in (("front/back", a), ("side", b), ("top", c)):
            if not 55 <= v <= 150:
                raise ValueError(f"fitted head {name} radius {v:.0f} mm looks wrong - redo calibration")
        return cls(a, b, c)


def rad_for(r_scalp: float, guard: float) -> float:
    """Radial slide position that puts the comb tip on the scalp."""
    return config.D0 - guard - r_scalp


def comb_tip_radius(rad: float, guard: float) -> float:
    return config.D0 - rad - guard


def joints_ok(yaw, pitch, rad, guard) -> bool:
    return (config.YAW_MIN <= yaw <= config.YAW_MAX and config.PITCH_MIN <= pitch <= config.PITCH_MAX
            and config.RAD_MIN <= rad <= config.RAD_MAX and config.GUARD_MIN <= guard <= config.GUARD_MAX)
