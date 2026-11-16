"""Turn a phone 3D scan of the head (taken WITH A CAP ON) into a HairBarbot head profile.

Why a cap: a thin, matte wig cap or swim cap flattens the hair, so the scanned surface sits only a few mm above
the scalp, and matte fabric scans far better than shiny or wet hair. Take the cap off before cutting.

1. Put on the cap. Sit still with the face relaxed and looking straight ahead.
2. Scan with a phone app (Polycam, Scaniverse, or similar): walk slowly around the head, ~30 cm away,
   covering the top and back. Export the mesh as OBJ, PLY or STL (no GLB/USDZ).
3. python vision/head_scan.py my_scan.obj --name shiqi
   A 3D window opens: check that the orange hairline sits at the forehead and the nose points forward.
   Keys: f = flip front/back, [ / ] = turn 5 deg, s = save, q = quit without saving.
4. The profile is saved to pc/vision/profiles/<name>.json and appears as option 4 in the head-size menu,
   or use it directly: python vision/head_scalp.py --scan vision/profiles/shiqi.json

Assumptions (all can be overridden): the scan is gravity-aligned with Y up (true for phone AR scans; use
--up z otherwise), units are detected from the size, the cap + flattened hair add 3 mm (--cap), and the
head center sits at ear height, 129 mm below the top of the head (ANSUR II average).
"""
import argparse
import math
import os
import re
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from head_profile import GRID_PITCH_MAX, GRID_STEP, PROFILE_DIR, HeadProfile  # noqa: E402

EAR_TO_TOP_MM = 129.0          # ANSUR II, average of female and male medians
CIRC_LEVEL_MM = 95.0           # head circumference is measured ~95 mm below the top (just above the brows)


# ---------------------------------------------------------------------- loading (vertices only)
def load_vertices(path):
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        data = f.read()
    if ext == ".obj":
        return _load_obj(data)
    if ext == ".ply":
        return _load_ply(data)
    if ext == ".stl":
        return _load_stl(data)
    raise ValueError(f"Unsupported file type {ext}. Export the scan as OBJ, PLY or STL.")


def _load_obj(data):
    pts = [list(map(float, ln.split()[1:4])) for ln in data.decode("utf-8", "ignore").splitlines()
           if ln.startswith("v ")]
    if not pts:
        raise ValueError("No vertices found in the OBJ file.")
    return np.array(pts, dtype=np.float64)


PLY_TYPES = {"char": "b", "int8": "b", "uchar": "B", "uint8": "B", "short": "h", "int16": "h", "ushort": "H",
             "uint16": "H", "int": "i", "int32": "i", "uint": "I", "uint32": "I", "float": "f", "float32": "f",
             "double": "d", "float64": "d"}


def _load_ply(data):
    end = data.find(b"end_header")
    if end < 0:
        raise ValueError("Not a valid PLY file.")
    header = data[:end].decode("ascii", "ignore").splitlines()
    body = data[data.index(b"\n", end) + 1:]
    fmt = next(ln.split()[1] for ln in header if ln.startswith("format"))
    n, props, in_vertex = 0, [], False
    for ln in header:
        p = ln.split()
        if p[:1] == ["element"]:
            in_vertex = p[1] == "vertex"
            if in_vertex:
                n = int(p[2])
        elif p[:1] == ["property"] and in_vertex:
            if p[1] == "list":
                raise ValueError("Unsupported PLY vertex layout.")
            props.append((p[2], PLY_TYPES[p[1]]))
    names = [nm for nm, _ in props]
    ix, iy, iz = names.index("x"), names.index("y"), names.index("z")
    if fmt == "ascii":
        rows = body.decode("ascii", "ignore").split("\n")[:n]
        arr = np.array([list(map(float, r.split()[:len(props)])) for r in rows])
        return arr[:, [ix, iy, iz]]
    endian = "<" if fmt == "binary_little_endian" else ">"
    dt = np.dtype([(nm, endian + t) for nm, t in props])
    arr = np.frombuffer(body, dtype=dt, count=n)
    return np.column_stack([arr["x"], arr["y"], arr["z"]]).astype(np.float64)


def _load_stl(data):
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        nums = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)
        return np.array([[float(a), float(b), float(c)] for a, b, c in nums])
    n = struct.unpack("<I", data[80:84])[0]
    rec = np.frombuffer(data[84:84 + 50 * n], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]))
    return rec["v"].reshape(-1, 3).astype(np.float64)


# ---------------------------------------------------------------------- alignment
def to_mm_zup(verts, up="y", units="auto"):
    v = np.asarray(verts, dtype=np.float64)
    if up == "y":
        v = np.column_stack([v[:, 0], -v[:, 2], v[:, 1]])        # rotate +90 deg about x: Y-up -> Z-up
    elif up != "z":
        raise ValueError("up must be 'y' or 'z'")
    ext = float(np.max(v.max(axis=0) - v.min(axis=0)))
    if units == "auto":
        scale = 1000.0 if ext < 3 else (10.0 if ext < 100 else 1.0)    # m / cm / mm
    else:
        scale = {"m": 1000.0, "cm": 10.0, "mm": 1.0}[units]
    return v * scale


def _band(v, top, lo, hi):
    return v[(v[:, 2] <= top - lo) & (v[:, 2] >= top - hi)]


def find_frame(v):
    """-> (center (3,), forward unit (3,)) for Z-up mm vertices of a head scan."""
    top = float(v[:, 2].max())
    v = v[v[:, 2] > top - 260]                                 # head + a bit of neck, no shoulders
    cran = _band(v, top, 40, 90)
    if len(cran) < 50:
        raise ValueError("Too few points near the top of the head. Is the scan upright? Try --up z.")
    c_xy = (cran[:, :2].min(axis=0) + cran[:, :2].max(axis=0)) / 2
    # nose: the narrowest bump in the horizontal outline ~110-170 mm below the top
    face = _band(v, top, 110, 170)
    d = face[:, :2] - c_xy
    ang = np.degrees(np.arctan2(d[:, 1], d[:, 0]))
    r = np.linalg.norm(d, axis=1)
    bins = np.full(72, np.nan)
    for b in range(72):
        m = (ang >= -180 + 5 * b) & (ang < -175 + 5 * b)
        if m.any():
            bins[b] = r[m].max()
    filled = np.where(np.isnan(bins), np.nanmedian(bins), bins)
    # how much each direction sticks out compared with its neighbors 15-35 deg away (nose = sharp bump)
    peak = np.array([filled[b] - np.median(np.take(filled, list(range(b - 7, b - 2)) + list(range(b + 3, b + 8)),
                                                   mode="wrap")) for b in range(72)])
    nose_b = int(np.argmax(peak))
    a = math.radians(-177.5 + 5 * nose_b)
    fwd = np.array([math.cos(a), math.sin(a), 0.0])
    # center: halfway between front and back of the head at forehead level, at ear height
    lvl = _band(v, top, 70, 90)
    along = (lvl[:, :2] - c_xy) @ fwd[:2]
    mid = c_xy + fwd[:2] * (along.max() + along.min()) / 2
    return np.array([mid[0], mid[1], top - EAR_TO_TOP_MM]), fwd


def head_frame(v, center, fwd, turn_deg=0.0):
    a = math.radians(turn_deg)
    f = np.array([fwd[0] * math.cos(a) - fwd[1] * math.sin(a), fwd[0] * math.sin(a) + fwd[1] * math.cos(a), 0.0])
    z = np.array([0.0, 0.0, 1.0])
    y = np.cross(z, f)
    R = np.vstack([f, y, z])                                    # rows = head axes in scan coordinates
    return (v - center) @ R.T


# ---------------------------------------------------------------------- profile
def build_profile(vh, cap_mm=3.0, name="Scan"):
    """vh: vertices in head coordinates (mm). -> HeadProfile with a scalp radius grid."""
    r = np.linalg.norm(vh, axis=1)
    pitch = np.degrees(np.arccos(np.clip(vh[:, 2] / np.maximum(r, 1e-9), -1, 1)))
    yaw = np.degrees(np.arctan2(vh[:, 1], vh[:, 0]))
    rows = int(GRID_PITCH_MAX / GRID_STEP) + 1
    cols = int(360 / GRID_STEP) + 1
    grid = np.full((rows, cols - 1), np.nan)
    ii = np.clip(np.rint(pitch / GRID_STEP).astype(int), 0, None)
    jj = np.rint((yaw + 180) / GRID_STEP).astype(int) % (cols - 1)
    ok = ii < rows
    for i, j, rr in zip(ii[ok], jj[ok], r[ok]):                 # outer surface = largest radius per cell
        if not grid[i, j] >= rr:
            grid[i, j] = rr
    if np.isnan(grid).all():
        raise ValueError("The scan has no points around the head center. Check --up and --units.")
    grid[0, :] = np.nanmax(grid[0, :]) if not np.isnan(grid[0, :]).all() else np.nan   # crown: one point
    for _ in range(200):                                         # fill holes from neighbors
        nan = np.isnan(grid)
        if not nan.any():
            break
        padded = np.pad(grid, ((1, 1), (0, 0)), mode="edge")
        neigh = np.stack([padded[:-2], padded[2:], np.roll(grid, 1, 1), np.roll(grid, -1, 1)])
        grid[nan] = np.nanmean(neigh, axis=0)[nan]
    grid = np.nan_to_num(grid, nan=float(np.nanmedian(grid))) - cap_mm
    grid = np.column_stack([grid, grid[:, 0]])                   # yaw +180 == -180
    prof = HeadProfile(name, 0, 0, 0, 0, grid.round(1).tolist())
    # measurements, ANSUR style
    ys = np.arange(-180, 181, 2.0)
    lvl_z = EAR_TO_TOP_MM - CIRC_LEVEL_MM
    ring = []
    for y in ys:                                                  # horizontal ring just above the brows
        lo, hi = 0.0, 120.0
        for _ in range(30):
            mid = (lo + hi) / 2
            p, _ = prof.surface(y, mid)
            lo, hi = (mid, hi) if p[2] > lvl_z else (lo, mid)
        ring.append(prof.surface(y, (lo + hi) / 2)[0][:2])
    ring = np.array(ring)
    prof.circumference = float(np.sum(np.linalg.norm(np.diff(ring, axis=0), axis=1)))
    prof.length = float(ring[:, 0].max() - ring[:, 0].min())
    widths = [np.ptp(np.array([prof.surface(y, p)[0][1] for y in (90, -90)])) for p in range(40, 100, 5)]
    prof.breadth = float(max(widths))
    prof.ear_to_top = float(prof.radius(0, 0))
    return prof


def import_scan(path, up="y", units="auto", cap_mm=3.0, name=None, turn_deg=0.0, flip=False):
    v = to_mm_zup(load_vertices(path), up, units)
    center, fwd = find_frame(v)
    vh = head_frame(v, center, fwd, turn_deg + (180.0 if flip else 0.0))
    return build_profile(vh, cap_mm, name or os.path.splitext(os.path.basename(path))[0])


def main():
    ap = argparse.ArgumentParser(description="Make a head profile from a phone 3D scan (taken with a cap on).")
    ap.add_argument("scan", help="OBJ, PLY or STL file exported from the scanning app")
    ap.add_argument("--name", help="profile name (default: the file name)")
    ap.add_argument("--up", choices=["y", "z"], default="y", help="which axis points up in the scan (phone apps: y)")
    ap.add_argument("--units", choices=["auto", "m", "cm", "mm"], default="auto")
    ap.add_argument("--cap", type=float, default=3.0, help="cap + flattened hair thickness to subtract, mm")
    ap.add_argument("--no-window", action="store_true", help="save without the 3D check window")
    a = ap.parse_args()
    name = a.name or os.path.splitext(os.path.basename(a.scan))[0]
    out = os.path.join(PROFILE_DIR, re.sub(r"[^A-Za-z0-9_-]+", "_", name) + ".json")
    turn, flip = 0.0, False
    prof = import_scan(a.scan, a.up, a.units, a.cap, name)
    if not a.no_window:
        import cv2
        from head_viewer import HeadViewer
        viewer = HeadViewer(title="HairBarbot - check the scan")
        while True:
            viewer.show(prof, info=["check: hairline at the forehead, nose facing forward",
                                    "f flip   [ ] turn 5 deg   s save   q quit"])
            k = cv2.waitKey(30) & 0xFF
            if k in (ord("q"), 27):
                print("Not saved.")
                return
            if k == ord("s"):
                break
            if k in (ord("f"), ord("["), ord("]")):
                flip = not flip if k == ord("f") else flip
                turn += {ord("["): 5.0, ord("]"): -5.0}.get(k, 0.0)
                prof = import_scan(a.scan, a.up, a.units, a.cap, name, turn, flip)
            viewer.handle_key(k)
        viewer.close()
    prof.save(out)
    print(f"Saved {out}\n{prof.describe()}")
    print("Use it: python vision/head_scalp.py --scan " + os.path.relpath(out, os.path.dirname(HERE)))


if __name__ == "__main__":
    main()
