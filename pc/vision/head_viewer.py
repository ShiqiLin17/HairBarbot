"""3D head viewer: a rotatable wireframe of the head model (average estimate or a real scan), with the live
face mesh on it. Opens its own window from the terminal. Drag with the mouse to turn it, scroll to zoom.

  python vision/head_viewer.py                       # average male head
  python vision/head_viewer.py --scan vision/profiles/me.json
  python vision/head_viewer.py --sex female --save head.png
"""
import argparse
import math
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from orientation import max_pitch  # noqa: E402
from head_profile import average_profile, load_profile  # noqa: E402

BG = (58, 58, 58)            # dark gray, like a 3D modelling viewport
LINE = (205, 205, 205)       # scalp wireframe
LINE_BACK = (95, 95, 95)     # back side of the head (hidden lines, dimmer)
NOCUT = (120, 140, 175)      # face / ears / below the hairline (not cut), muted
FACE = (245, 245, 245)       # live face mesh
ACCENT = (60, 170, 255)      # crown + hairline (orange)


def _rot(yaw_deg, pitch_deg):
    """View rotation: turn the head by yaw (around up), then tilt by pitch."""
    y, p = math.radians(yaw_deg), math.radians(pitch_deg)
    Rz = np.array([[math.cos(y), -math.sin(y), 0], [math.sin(y), math.cos(y), 0], [0, 0, 1]])
    Ry = np.array([[math.cos(p), 0, math.sin(p)], [0, 1, 0], [-math.sin(p), 0, math.cos(p)]])
    return Ry @ Rz


class HeadViewer:
    def __init__(self, title="HairBarbot - 3D head", size=560):
        self.title, self.size = title, size
        self.view_yaw, self.view_pitch, self.zoom = 35.0, 12.0, 1.0
        self._drag = None
        self._cache = {}
        self._window = False

    # ---- head wireframe in head coordinates (mm)
    def _wire(self, profile):
        key = id(profile)
        if key not in self._cache:
            rings, meridians = [], []
            for p in range(10, 121, 10):                       # latitude rings
                rings.append([(y, p) for y in range(-180, 181, 6)])
            for y in range(-180, 180, 15):                     # meridians
                meridians.append([(y, p) for p in range(0, 123, 3)])
            hair = [(y, max_pitch(y)) for y in range(-180, 181, 4)]
            pts = lambda path: (np.array([profile.surface(y, p)[0] for y, p in path]),
                                np.array([p <= max_pitch(y) for y, p in path]))
            self._cache = {key: ([pts(r) for r in rings + meridians], pts(hair)[0], profile.surface(0, 0)[0])}
        return self._cache[key]

    def _project(self, P):
        """Head frame (x fwd, y left, z up) -> screen. Viewer looks at the head's front by default."""
        R = _rot(self.view_yaw, self.view_pitch)
        q = P @ R.T
        s = self.size / 330.0 * self.zoom
        # facing the person: their left (+y) is on the viewer's right, up (+z) is up
        sx = self.size / 2 + q[:, 1] * s
        sy = self.size / 2 + 25 - q[:, 2] * s
        depth = q[:, 0]                                          # + = toward the viewer
        return np.stack([sx, sy], axis=1), depth

    def render(self, profile, face_mesh=None, face_edges=None, info=None):
        img = np.full((self.size, self.size, 3), BG, np.uint8)
        wires, hairline, crown = self._wire(profile)
        for P, cut in wires:
            xy, d = self._project(P)
            for k in range(len(P) - 1):
                front = d[k] + d[k + 1] > -40
                col = (LINE if cut[k] else NOCUT) if front else LINE_BACK
                cv2.line(img, tuple(np.int32(xy[k])), tuple(np.int32(xy[k + 1])), col, 1, cv2.LINE_AA)
        xy, d = self._project(hairline)
        for k in range(len(xy) - 1):
            if d[k] > -40:
                cv2.line(img, tuple(np.int32(xy[k])), tuple(np.int32(xy[k + 1])), ACCENT, 2, cv2.LINE_AA)
        if face_mesh is not None and len(face_mesh):
            fxy, fd = self._project(np.asarray(face_mesh))
            if face_edges is not None:
                segs = [np.int32([fxy[a], fxy[b]]) for a, b in face_edges if fd[a] > -30 and fd[b] > -30]
                cv2.polylines(img, segs, False, FACE, 1, cv2.LINE_AA)
            else:
                for (x, y) in fxy:
                    cv2.circle(img, (int(x), int(y)), 1, FACE, -1)
        cxy, _ = self._project(crown.reshape(1, 3))
        cv2.drawMarker(img, tuple(np.int32(cxy[0])), ACCENT, cv2.MARKER_CROSS, 14, 2)
        # small axis gizmo: red = forward (nose), green = left, blue = up
        o = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float) * 30
        gxy, _ = self._project(o)
        base = np.array([45, self.size - 45]) - gxy[0]
        for i, col in zip((1, 2, 3), ((40, 40, 230), (60, 190, 60), (230, 120, 40))):
            cv2.line(img, tuple(np.int32(gxy[0] + base)), tuple(np.int32(gxy[i] + base)), col, 2, cv2.LINE_AA)
        lines = [f"{profile.label}  {'(3D scan)' if profile.grid is not None else '(estimate)'}",
                 f"around {profile.circumference / 10:.1f} cm  length {profile.length / 10:.1f}  "
                 f"width {profile.breadth / 10:.1f} cm"] + (info or []) + ["drag = turn   scroll = zoom   r = reset"]
        for i, t in enumerate(lines):
            cv2.putText(img, t, (12, 22 + 20 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (235, 235, 235), 1, cv2.LINE_AA)
        cv2.putText(img, "orange = hairline (no cutting below)", (12, self.size - 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, ACCENT, 1, cv2.LINE_AA)
        return img

    # ---- window + mouse
    def _mouse(self, event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN:
            self._drag = (x, y, self.view_yaw, self.view_pitch)
        elif event == cv2.EVENT_MOUSEMOVE and self._drag:
            x0, y0, yaw0, p0 = self._drag
            self.view_yaw = yaw0 + (x - x0) * 0.5
            self.view_pitch = max(-80, min(80, p0 + (y - y0) * 0.5))
        elif event == cv2.EVENT_LBUTTONUP:
            self._drag = None
        elif event == cv2.EVENT_MOUSEWHEEL:
            self.zoom = max(0.5, min(3.0, self.zoom * (1.1 if flags > 0 else 1 / 1.1)))

    def show(self, profile, face_mesh=None, face_edges=None, info=None):
        if not self._window:
            cv2.namedWindow(self.title)
            cv2.setMouseCallback(self.title, self._mouse)
            self._window = True
        cv2.imshow(self.title, self.render(profile, face_mesh, face_edges, info))

    def handle_key(self, k):
        if k == ord("r"):
            self.view_yaw, self.view_pitch, self.zoom = 35.0, 12.0, 1.0

    def close(self):
        if self._window:
            cv2.destroyWindow(self.title)
            self._window = False


def main():
    ap = argparse.ArgumentParser(description="Show the HairBarbot head model in 3D.")
    ap.add_argument("--scan", help="saved scan profile (.json)")
    ap.add_argument("--sex", choices=["female", "male"], default="male")
    ap.add_argument("--save", help="save one picture instead of opening a window")
    a = ap.parse_args()
    profile = load_profile(a.scan) if a.scan else average_profile(a.sex)
    v = HeadViewer()
    if a.save:
        cv2.imwrite(a.save, v.render(profile))
        print("saved", a.save)
        return
    while True:
        v.show(profile)
        k = cv2.waitKey(20) & 0xFF
        if k in (ord("q"), 27):
            break
        v.handle_key(k)
    v.close()


if __name__ == "__main__":
    main()
