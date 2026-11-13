"""Find the person's face with a webcam and estimate where their head and scalp are.

How it works
  1. YuNet (OpenCV's built-in face detector) finds the face and 5 landmarks:
     both eyes, nose tip, both mouth corners.
  2. solvePnP matches those 5 points to an average 3D face, which gives the head's position and
     rotation relative to the camera (head pose).
  3. A head-sized ellipsoid is attached behind the face. The part of it above the face/ear no-cut line
     (same zones as pc/orientation.py) is the scalp HairBarbot is allowed to cut.
  4. The visible part of that scalp is drawn on the video, colored by the hair length the chosen style
     wants there, plus the crown, the head axes, and the head angles.

Run it (from the pc folder):
  python vision/head_scalp.py                      # webcam 0
  python vision/head_scalp.py --camera 1           # another webcam
  python vision/head_scalp.py --image photo.jpg    # a photo (saves photo_scalp.png next to it)
  python vision/head_scalp.py --style buzz         # color by another style (see styles.py)
Keys: q = quit, s = save a screenshot.

Accuracy: it's an estimate. It assumes an average adult head (scale it with --head-scale) and a
typical webcam field of view (--fov). It cannot see the back of the head; it infers it from the face.
"""
import argparse
import math
import os
import sys
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # so we can import pc/ modules

from orientation import max_pitch                   # noqa: E402  (same no-cut zones as the controller)
from styles import STYLES, guard_length, region_name  # noqa: E402

MODEL_PATH = os.path.join(HERE, "models", "face_detection_yunet_2023mar.onnx")

# Average adult head, in mm, in the HEAD frame used everywhere in HairBarbot:
#   x forward (nose), y to the person's LEFT, z up. Origin = head center (between the ears, a bit above them).
# Order matches YuNet's landmarks: right eye, left eye, nose tip, right mouth corner, left mouth corner.
# ("right" = the person's right, which appears on the LEFT of a normal, unmirrored camera image.)
FACE_POINTS = np.array([
    [80.0, -32.0, 10.0],    # right eye
    [80.0, 32.0, 10.0],     # left eye
    [102.0, 0.0, -22.0],    # nose tip
    [82.0, -25.0, -50.0],   # right mouth corner
    [82.0, 25.0, -50.0],    # left mouth corner
])
HEAD_AXES = (100.0, 78.0, 112.0)   # ellipsoid half-sizes: front/back, side, top (mm) — same as the 3D app view


def ellipsoid_point(yaw, pitch, axes):
    """Point on the head ellipsoid at (yaw, pitch) degrees, and its outward normal (head frame)."""
    y, p = math.radians(yaw), math.radians(pitch)
    d = np.array([math.sin(p) * math.cos(y), math.sin(p) * math.sin(y), math.cos(p)])
    a, b, c = axes
    r = 1.0 / math.sqrt((d[0] / a) ** 2 + (d[1] / b) ** 2 + (d[2] / c) ** 2)
    pt = d * r
    n = np.array([pt[0] / a ** 2, pt[1] / b ** 2, pt[2] / c ** 2])
    return pt, n / np.linalg.norm(n)


def build_scalp_grid(yaw_step=6, pitch_step=4):
    """Sample points over the whole head: (yaw, pitch, cuttable?)."""
    pts = []
    for p in range(0, 124, pitch_step):
        for y in range(-180, 180, yaw_step):
            pts.append((float(y), float(p), p <= max_pitch(y)))
    return pts


@dataclass
class HeadEstimate:
    found: bool
    box: tuple = None                 # x, y, w, h in pixels
    landmarks: np.ndarray = None      # 5x2 pixels
    score: float = 0.0
    rvec: np.ndarray = None           # head -> camera rotation (Rodrigues)
    tvec: np.ndarray = None           # head center in camera coords, mm
    yaw: float = 0.0                  # + = person turned to THEIR left
    pitch: float = 0.0                # + = chin up / looking up
    roll: float = 0.0                 # + = head tilted toward their left shoulder
    distance_mm: float = 0.0
    scalp_px: list = field(default_factory=list)   # visible scalp points: (x, y, yaw, pitch, length_mm)
    crown_px: tuple = None
    reproj_err_px: float = 0.0


class HeadScalpEstimator:
    def __init__(self, model_path=MODEL_PATH, fov_deg=60.0, head_scale=1.0, min_score=0.8, smooth=0.5):
        if not hasattr(cv2, "FaceDetectorYN"):
            raise RuntimeError("Your OpenCV is too old. Run: pip install --upgrade opencv-python  (needs 4.8+)")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Face model not found: {model_path}")
        self.detector = cv2.FaceDetectorYN.create(model_path, "", (320, 320), min_score, 0.3, 5000)
        self.fov = fov_deg
        self.scale = head_scale
        self.smooth = smooth            # 0 = no smoothing, 0.9 = very smooth (laggy)
        self.grid = build_scalp_grid()
        self._prev = None               # (rvec, tvec) from the last frame
        self._size = None

    # ---- camera model: a webcam with roughly `fov` degrees across the image width
    def camera_matrix(self, w, h):
        f = (w / 2) / math.tan(math.radians(self.fov) / 2)
        return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float64)

    def detect(self, frame):
        h, w = frame.shape[:2]
        if self._size != (w, h):
            self.detector.setInputSize((w, h))
            self._size = (w, h)
            self._prev = None
        _, faces = self.detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None
        f = max(faces, key=lambda r: r[2] * r[3])          # biggest face = the person being cut
        return f

    def solve_pose(self, landmarks, w, h):
        """5 landmark pixels -> (rvec, tvec, reprojection error)."""
        K = self.camera_matrix(w, h)
        obj = FACE_POINTS * self.scale
        img = np.asarray(landmarks, dtype=np.float64).reshape(-1, 1, 2)
        if self._prev is not None:
            ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, self._prev[0].copy(), self._prev[1].copy(),
                                          useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
        else:
            # start from "facing the camera, ~50 cm away", then refine
            rvec0, _ = cv2.Rodrigues(_head_to_cam_facing())
            tvec0 = np.array([[0.0], [0.0], [500.0]])
            ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, rvec0, tvec0, useExtrinsicGuess=True,
                                          flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            return None
        proj, _ = cv2.projectPoints(obj, rvec, tvec, K, None)
        err = float(np.mean(np.linalg.norm(proj.reshape(-1, 2) - img.reshape(-1, 2), axis=1)))
        if self._prev is not None and self.smooth > 0:
            a = self.smooth
            rvec = a * self._prev[0] + (1 - a) * rvec
            tvec = a * self._prev[1] + (1 - a) * tvec
        self._prev = (rvec, tvec)
        return rvec, tvec, err

    def estimate(self, frame, style="fade25"):
        h, w = frame.shape[:2]
        f = self.detect(frame)
        if f is None:
            self._prev = None
            return HeadEstimate(found=False)
        box = tuple(int(v) for v in f[:4])
        lm = order_landmarks(f[4:14].reshape(5, 2))
        sol = self.solve_pose(lm, w, h)
        if sol is None:
            return HeadEstimate(found=False)
        rvec, tvec, err = sol
        R, _ = cv2.Rodrigues(rvec)
        yaw, pitch, roll = head_angles(R)
        est = HeadEstimate(found=True, box=box, landmarks=lm, score=float(f[14]), rvec=rvec, tvec=tvec,
                           yaw=yaw, pitch=pitch, roll=roll, distance_mm=float(np.linalg.norm(tvec)),
                           reproj_err_px=err)
        # ---- visible scalp points
        K = self.camera_matrix(w, h)
        st = STYLES.get(style)
        axes = tuple(a * self.scale for a in HEAD_AXES)
        pts3, keep = [], []
        for (gy, gp, cuttable) in self.grid:
            if not cuttable:
                continue
            p, n = ellipsoid_point(gy, gp, axes)
            pc = R @ p + tvec.ravel()
            if (R @ n) @ pc >= 0:                 # surface faces away from the camera -> hidden
                continue
            pts3.append(p)
            keep.append((gy, gp))
        if pts3:
            px, _ = cv2.projectPoints(np.array(pts3), rvec, tvec, K, None)
            for (x, y), (gy, gp) in zip(px.reshape(-1, 2), keep):
                L = guard_length(gy, gp, st["lengths"], st["fade_to"]) if st else None
                est.scalp_px.append((float(x), float(y), gy, gp, L))
        # crown: usually just out of sight at eye level, so always show where it is estimated to be
        crown, _ = ellipsoid_point(0, 0, axes)
        c, _ = cv2.projectPoints(crown.reshape(1, 3), rvec, tvec, K, None)
        est.crown_px = tuple(float(v) for v in c.reshape(2))
        return est


def order_landmarks(lm):
    """Put the 5 landmarks in FACE_POINTS order without trusting the detector's left/right labels:
    in a normal (unmirrored) camera image the person's RIGHT eye / mouth corner is the one further LEFT."""
    lm = np.asarray(lm, dtype=np.float64).reshape(5, 2)
    eyes = sorted([lm[0], lm[1]], key=lambda p: p[0])
    mouth = sorted([lm[3], lm[4]], key=lambda p: p[0])
    return np.array([eyes[0], eyes[1], lm[2], mouth[0], mouth[1]])


def _head_to_cam_facing():
    """Rotation for a head looking straight at the camera: head x (forward) -> camera -z,
    head y (person's left) -> camera +x (image right, unmirrored), head z (up) -> camera -y."""
    return np.array([[0.0, 1.0, 0.0], [0.0, 0.0, -1.0], [-1.0, 0.0, 0.0]])


def head_angles(R):
    """Head yaw/pitch/roll in degrees relative to looking straight at the camera."""
    rel = _head_to_cam_facing().T @ R          # rotation of the head away from "facing the camera"
    # rel maps head axes into a "facing" head frame: x fwd, y left, z up
    fwd = rel @ np.array([1.0, 0, 0])
    yaw = math.degrees(math.atan2(fwd[1], fwd[0]))            # + = turned to their left
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, fwd[2]))))  # + = looking up
    left = rel @ np.array([0, 1.0, 0])
    roll = math.degrees(math.asin(max(-1.0, min(1.0, -left[2]))))  # + = tilted toward their left shoulder
    return yaw, pitch, roll


# ---------------------------------------------------------------------- drawing
def length_color(L, lo=3, hi=60):
    """Short hair = light, long = dark (BGR). Matches the app's colors."""
    t = 0.0 if L is None else max(0.0, min(1.0, (L - lo) / (hi - lo))) ** 0.7
    a, b = np.array([178, 196, 216]), np.array([28, 33, 43])     # BGR of #d8c4b2 -> #2b211c
    return tuple(int(v) for v in a + (b - a) * t)


def draw(frame, est, K=None, style="fade25", mirror=False):
    """Overlay the estimate. With mirror=True the picture is flipped for display (text stays readable);
    the estimate itself is always made on the unflipped camera image."""
    out = frame.copy()
    if not est.found:
        out = cv2.flip(out, 1) if mirror else out
        cv2.putText(out, "No face found - face the camera", (16, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (40, 40, 220), 2)
        return out
    overlay = out.copy()
    # scalp: filled dots colored by the style's length; hull outline
    if est.scalp_px:
        r = max(3, int(est.box[2] / 45))
        for x, y, gy, gp, L in est.scalp_px:
            cv2.circle(overlay, (int(x), int(y)), r, length_color(L), -1, cv2.LINE_AA)
        hull = cv2.convexHull(np.array([[int(x), int(y)] for x, y, *_ in est.scalp_px], np.int32))
        cv2.polylines(out, [hull], True, (90, 200, 255), 2, cv2.LINE_AA)
    out = cv2.addWeighted(overlay, 0.55, out, 0.45, 0)
    # face box + landmarks
    x, y, w, h = est.box
    cv2.rectangle(out, (x, y), (x + w, y + h), (80, 200, 80), 2)
    for (lx, ly) in est.landmarks:
        cv2.circle(out, (int(lx), int(ly)), 3, (80, 200, 80), -1)
    # head axes from the head center: red = forward, green = left, blue = up
    if K is not None:
        axes = np.float32([[0, 0, 0], [120, 0, 0], [0, 80, 0], [0, 0, 140]])
        p, _ = cv2.projectPoints(axes, est.rvec, est.tvec, K, None)
        p = p.reshape(-1, 2).astype(int)
        for i, col in zip((1, 2, 3), ((40, 40, 230), (60, 190, 60), (230, 120, 40))):
            cv2.line(out, tuple(p[0]), tuple(p[i]), col, 2, cv2.LINE_AA)
    if est.crown_px:
        cx, cy = (int(v) for v in est.crown_px)
        cv2.drawMarker(out, (cx, cy), (0, 215, 255), cv2.MARKER_CROSS, 18, 2)
        cv2.putText(out, "crown (est.)", (cx + 8, cy - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 215, 255), 1, cv2.LINE_AA)
    if mirror:
        out = cv2.flip(out, 1)
    # text panel
    name = STYLES[style]["name"] if style in STYLES else style
    name = name.replace("\u2192", "->")              # OpenCV's font has no arrow character
    lines = [f"yaw {est.yaw:+.0f}  pitch {est.pitch:+.0f}  roll {est.roll:+.0f} deg",
             f"distance {est.distance_mm / 10:.0f} cm   fit error {est.reproj_err_px:.1f} px",
             f"style: {name}"]
    cv2.rectangle(out, (8, 8), (400, 16 + 24 * len(lines)), (30, 30, 30), -1)
    for i, t in enumerate(lines):
        cv2.putText(out, t, (16, 30 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return out


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Detect the face and estimate where the scalp is.")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--image", help="run on a photo instead of the webcam")
    ap.add_argument("--style", default="fade25", choices=sorted(STYLES))
    ap.add_argument("--fov", type=float, default=60.0, help="webcam horizontal field of view in degrees")
    ap.add_argument("--head-scale", type=float, default=1.0, help="1.1 = 10%% bigger head than average")
    ap.add_argument("--mirror", action="store_true", help="show the video flipped like a mirror (display only)")
    a = ap.parse_args()
    est = HeadScalpEstimator(fov_deg=a.fov, head_scale=a.head_scale)

    if a.image:
        frame = cv2.imread(a.image)
        if frame is None:
            sys.exit(f"Can't read {a.image}")
        e = est.estimate(frame, a.style)
        out = draw(frame, e, est.camera_matrix(frame.shape[1], frame.shape[0]), a.style)
        path = os.path.splitext(a.image)[0] + "_scalp.png"
        cv2.imwrite(path, out)
        print(("found face: " + f"yaw {e.yaw:+.0f}, pitch {e.pitch:+.0f}, roll {e.roll:+.0f}, "
               f"{e.distance_mm / 10:.0f} cm away") if e.found else "no face found")
        print("saved", path)
        return

    cap = cv2.VideoCapture(a.camera)
    if not cap.isOpened():
        sys.exit(f"Can't open camera {a.camera}. Try --camera 1, and allow camera access for your terminal "
                 "(Mac: System Settings > Privacy & Security > Camera).")
    t_last, fps = time.time(), 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        e = est.estimate(frame, a.style)
        out = draw(frame, e, est.camera_matrix(frame.shape[1], frame.shape[0]), a.style, mirror=a.mirror)
        now = time.time()
        fps = 0.9 * fps + 0.1 / max(1e-3, now - t_last)
        t_last = now
        cv2.putText(out, f"{fps:.0f} fps   q quit  s save", (16, out.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1, cv2.LINE_AA)
        cv2.imshow("HairBarbot - face & scalp", out)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord("s"):
            name = time.strftime("scalp_%H%M%S.png")
            cv2.imwrite(name, out)
            print("saved", name)
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
