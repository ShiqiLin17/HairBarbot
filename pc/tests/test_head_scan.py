"""Tests for importing a phone head scan:  python tests/test_head_scan.py"""
import math
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "vision"))

import numpy as np

from head_profile import load_profile
from head_scan import import_scan


def synthetic_head(a=96.0, b=75.0, c=129.0, nose=True, n=60000, seed=1):
    """Points on a capped head (ellipsoid centered at ear height) + nose + neck, in head coordinates (mm).
    Includes 3 mm of cap/hair on top of the scalp."""
    rng = np.random.default_rng(seed)
    u = rng.normal(size=(n, 3))
    u /= np.linalg.norm(u, axis=1, keepdims=True)
    r = 1 / np.sqrt((u[:, 0] / a) ** 2 + (u[:, 1] / b) ** 2 + (u[:, 2] / c) ** 2)
    pts = u * (r + 3.0)[:, None]
    pts = pts[pts[:, 2] > -110]                                   # stop at the jaw
    parts = [pts]
    if nose:                                                      # nose: a small bump ~ 140 mm below the top
        t = rng.uniform(0, 1, 3000)
        ang = rng.uniform(-math.pi, math.pi, 3000)
        h = c - 140 + 25 * (t - 0.5)
        nx = a * 0.92 + 22 * (1 - abs(t - 0.5) * 2) * np.clip(np.cos(ang), 0, 1)
        parts.append(np.column_stack([nx, 10 * np.sin(ang), h]))
    ang = rng.uniform(-math.pi, math.pi, 4000)                    # neck
    parts.append(np.column_stack([-10 + 55 * np.cos(ang), 50 * np.sin(ang), rng.uniform(-200, -110, 4000)]))
    return np.vstack(parts)


def to_phone_scan(P_head, turn_deg=0.0, shift=(0.3, 1.2, -0.4)):
    """Head coords (mm, z up) -> a phone-style scan: meters, Y up, turned and moved in the room."""
    t = math.radians(turn_deg)
    Rz = np.array([[math.cos(t), -math.sin(t), 0], [math.sin(t), math.cos(t), 0], [0, 0, 1]])
    p = P_head @ Rz.T / 1000.0
    return np.column_stack([p[:, 0], p[:, 2], -p[:, 1]]) + np.array(shift)   # z-up -> y-up


def write_obj(path, V):
    with open(path, "w") as f:
        f.writelines(f"v {x:.6f} {y:.6f} {z:.6f}\n" for x, y, z in V)


def write_ply(path, V):
    with open(path, "wb") as f:
        f.write(f"ply\nformat binary_little_endian 1.0\nelement vertex {len(V)}\nproperty float x\n"
                f"property float y\nproperty float z\nproperty uchar red\nend_header\n".encode())
        rec = np.zeros(len(V), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("red", "u1")])
        rec["x"], rec["y"], rec["z"] = V[:, 0], V[:, 1], V[:, 2]
        f.write(rec.tobytes())


def write_stl(path, V):
    tri = V[: len(V) // 3 * 3].reshape(-1, 3, 3)
    with open(path, "wb") as f:
        f.write(b"\0" * 80 + struct.pack("<I", len(tri)))
        for t in tri:
            f.write(struct.pack("<12fH", 0, 0, 0, *t.ravel(), 0))


def check(prof, a=96.0, b=75.0, c=129.0):
    # the profile is the SCALP: cap thickness removed again
    assert abs(prof.radius(0, 0) - c) < 4, prof.radius(0, 0)
    # the nose must end up at the FRONT (yaw 0), ~140 mm below the top -> pitch ~95
    assert prof.radius(0, 95) > prof.radius(180, 95) + 10, (prof.radius(0, 95), prof.radius(180, 95))
    for yaw, pitch in [(0, 40), (90, 60), (180, 80), (-90, 50), (45, 30)]:
        d = np.array([math.sin(math.radians(pitch)) * math.cos(math.radians(yaw)),
                      math.sin(math.radians(pitch)) * math.sin(math.radians(yaw)), math.cos(math.radians(pitch))])
        true_r = 1 / math.sqrt((d[0] / a) ** 2 + (d[1] / b) ** 2 + (d[2] / c) ** 2)
        assert abs(prof.radius(yaw, pitch) - true_r) < 5, (yaw, pitch, prof.radius(yaw, pitch), true_r)
    assert abs(prof.length - 2 * a) < 12 and abs(prof.breadth - 2 * b) < 12, (prof.length, prof.breadth)
    assert 520 < prof.circumference < 590, prof.circumference


def test_import_obj_ply_stl_any_facing_direction():
    P = synthetic_head()
    with tempfile.TemporaryDirectory() as d:
        for k, (turn, ext, writer) in enumerate([(0, "obj", write_obj), (137, "ply", write_ply),
                                                  (-70, "stl", write_stl)]):
            path = os.path.join(d, f"scan.{ext}")
            writer(path, to_phone_scan(P, turn))
            prof = import_scan(path, cap_mm=3.0, name="test")
            check(prof)


def test_save_and_load_roundtrip():
    P = synthetic_head()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "scan.obj")
        write_obj(path, to_phone_scan(P, 30))
        prof = import_scan(path)
        out = prof.save(os.path.join(d, "me.json"))
        back = load_profile(out)
        assert back.grid is not None
        for y, p in [(0, 0), (90, 60), (-150, 90)]:
            assert abs(back.radius(y, p) - prof.radius(y, p)) < 0.2
        pt, n = back.surface(20, 50)
        assert n @ pt > 0                                         # normals point outward


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
