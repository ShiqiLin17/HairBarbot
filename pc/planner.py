"""Turns a haircut (lengths per region) into strokes for the machine.

Each stroke is at a fixed yaw and goes UPWARD from the lowest allowed point to the crown,
i.e. against the direction hair grows, the way a barber uses clippers.
"""
from dataclasses import dataclass, asdict

import numpy as np

import config
from kinematics import HeadModel, max_pitch, rad_for, joints_ok
from styles import guard_length


@dataclass
class Waypoint:
    yaw: float
    pitch: float
    rad: float
    guard: float

    def as_dict(self):
        return asdict(self)


class PlanError(Exception):
    pass


def _stroke_pitches(yaw):
    top = max_pitch(yaw) - config.ZONE_MARGIN
    ps = list(np.arange(top, 0.0, -config.STROKE_PITCH_STEP))
    ps.append(0.0)
    return ps


def make_waypoint(yaw, pitch, head, lengths, fade_to):
    g = guard_length(yaw, pitch, lengths, fade_to)
    r = head.radius(yaw, pitch)
    s = rad_for(r, g)
    if not joints_ok(yaw, pitch, s, g):
        raise PlanError(
            f"Can't reach yaw {yaw:.0f}, pitch {pitch:.0f}: radial {s:.1f} mm is outside "
            f"{config.RAD_MIN:.0f}-{config.RAD_MAX:.0f}. Check D0 / head position / calibration.")
    return Waypoint(round(yaw, 2), round(pitch, 2), round(s, 2), round(g, 2))


def plan_haircut(lengths: dict, fade_to=None, head: HeadModel = None):
    head = head or HeadModel()
    strokes = []
    yaws = np.arange(-165.0, 165.0 + 1e-6, config.STROKE_YAW_STEP)
    for yaw in yaws:
        pts = []
        prev = None
        for p in _stroke_pitches(yaw):
            wp = make_waypoint(float(yaw), float(p), head, lengths, fade_to)
            if prev is not None and abs(wp.guard - prev.guard) > config.MAX_GUARD_STEP:
                # add in-between points so the guard never jumps
                n = int(np.ceil(abs(wp.guard - prev.guard) / config.MAX_GUARD_STEP))
                for k in range(1, n):
                    pk = prev.pitch + (wp.pitch - prev.pitch) * k / n
                    pts.append(make_waypoint(float(yaw), pk, head, lengths, fade_to))
            pts.append(wp)
            prev = wp
        strokes.append(pts)
    return strokes


def estimate_minutes(strokes):
    """Rough time: cutting at FEED_CUT% of 15 deg/s pitch speed + ~6 s overhead per stroke."""
    cut_speed = 15.0 * config.FEED_CUT / 100.0
    t = 0.0
    for s in strokes:
        t += abs(s[0].pitch - s[-1].pitch) / cut_speed + 6.0
    return round(t / 60.0, 1)
