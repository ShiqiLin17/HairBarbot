"""Haircut styles: a hair length (= guard length, mm) for every spot on the head.

The head is split into 5 regions; lengths blend smoothly between them so there are no steps:
  top    - crown and top of head (pitch < 35 deg)
  front  - front hairline / fringe (|yaw| < 50)
  sides  - above the ears (|yaw| 70..115)
  back   - back of head (|yaw| > 135)
  nape   - low back of the neck (|yaw| > 115 and pitch > 85)
Optional fade: sides/back get shorter toward the bottom, down to `fade_to` mm.
"""
import numpy as np

import config
from orientation import max_pitch

REGIONS = ["top", "front", "sides", "back", "nape"]

STYLES = {
    "even20": {
        "name": "Even 2 cm",
        "desc": "2 cm all over. A simple, tidy trim.",
        "lengths": {"top": 20, "front": 20, "sides": 20, "back": 20, "nape": 20},
        "fade_to": None,
    },
    "buzz": {
        "name": "Buzz cut",
        "desc": "Same length everywhere. Simplest and fastest.",
        "lengths": {"top": 9, "front": 9, "sides": 9, "back": 9, "nape": 9},
        "fade_to": None,
    },
    "classic": {
        "name": "Classic short",
        "desc": "Longer on top, short and tidy on the sides and back.",
        "lengths": {"top": 25, "front": 25, "sides": 12, "back": 12, "nape": 9},
        "fade_to": None,
    },
    "fade": {
        "name": "Fade",
        "desc": "Longer on top, sides and back fade down to very short at the bottom.",
        "lengths": {"top": 25, "front": 25, "sides": 16, "back": 16, "nape": 6},
        "fade_to": 4,
    },
    "trim": {
        "name": "Long trim",
        "desc": "Takes a little off a longer haircut and evens it out.",
        "lengths": {"top": 40, "front": 35, "sides": 30, "back": 30, "nape": 22},
        "fade_to": None,
    },
}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def guard_length(yaw: float, pitch: float, lengths: dict, fade_to=None) -> float:
    ay = abs(yaw)
    lower = float(np.interp(ay, [0, 50, 70, 115, 135, 180],
                            [lengths["front"], lengths["front"], lengths["sides"],
                             lengths["sides"], lengths["back"], lengths["back"]]))
    if fade_to is not None:
        # smooth version of the no-cut boundary, so the fade has no steps as you move around the head
        mp = float(np.interp(ay, [0, 50, 70, 115, 135, 180], [55, 55, 72, 75, 90, 105]))
        # fade over a wide band (from 40 deg down to the edge) so the guard never has to jump
        t = _clamp((pitch - 40) / (mp - 40), 0.0, 1.0)
        lower = lower + (fade_to - lower) * t
    if ay > 115:
        w = _clamp((ay - 115) / 20.0, 0.0, 1.0) * _clamp((pitch - 85) / 10.0, 0.0, 1.0)
        lower = lower * (1 - w) + lengths["nape"] * w
    wt = _clamp((pitch - 35) / 20.0, 0.0, 1.0)   # 0 -> pure top, 1 -> pure lower region
    g = lengths["top"] * (1 - wt) + lower * wt
    return _clamp(g, config.GUARD_MIN, config.GUARD_MAX)


def validate_lengths(lengths: dict) -> dict:
    out = {}
    for r in REGIONS:
        if r not in lengths:
            raise ValueError(f"missing length for {r}")
        v = float(lengths[r])
        if not config.GUARD_MIN <= v <= config.GUARD_MAX:
            raise ValueError(f"{r} length must be {config.GUARD_MIN:.0f}-{config.GUARD_MAX:.0f} mm")
        out[r] = v
    return out


def preview_grid(lengths, fade_to=None, yaw_step=10, pitch_step=5):
    """Lengths on a yaw x pitch grid for the app's head map. None = not cut (face/ears)."""
    rows = []
    for p in range(0, 111, pitch_step):
        row = []
        for y in range(-180, 181, yaw_step):
            row.append(round(guard_length(y, p, lengths, fade_to), 1) if p <= max_pitch(y) else None)
        rows.append(row)
    return {"yaw_step": yaw_step, "pitch_step": pitch_step, "rows": rows}


def region_name(yaw: float, pitch: float) -> str:
    """Friendly name of the area at (yaw, pitch), for the live app."""
    ay = abs(yaw)
    if pitch < 35:
        return "top"
    if ay > 115 and pitch > 85:
        return "nape"
    if ay <= 50:
        return "front"
    if ay >= 135:
        return "back"
    return "left side" if yaw > 0 else "right side"
