"""Find the cutter in a camera picture from the ArUco tags stuck on it.

The cutter has three tag plates (left, right, rear; see config.TAGS). Each tag the camera sees gives its 4
corners. We know where those corners are on the cutter (from the CAD), so one solvePnP over all the corners
it sees gives the cutter's pose in the camera: where its scalp face is and which way it points.
More tags seen -> more corners -> a steadier answer.

Combined with the head pose from the face tracker (head_scalp.py, same camera), that becomes "where is the
cutter on the head" (camera_head.py does that step).

Print the tags:   python vision/cutter_tags.py --print tags.png      (then print at 100% scale)
Live test:        python vision/cutter_tags.py --camera 0            (shows the cutter's axes on the tags)
"""
import argparse
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import config  # noqa: E402


def _dictionary(name=None):
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name or config.TAG_DICT))


def tag_corners_on_cutter(tag, size):
    """3D corners of one tag (cutter axes, mm) in ArUco's order: top-left, top-right, bottom-right, bottom-left
    as seen looking at the printed tag."""
    c = np.asarray(tag["center"], float)
    n = np.asarray(tag["normal"], float)
    n /= np.linalg.norm(n)
    up = np.asarray(tag["up"], float)
    up = up - n * (up @ n)                          # make "up" lie in the tag's plane
    up /= np.linalg.norm(up)
    right = np.cross(up, n)                         # looking at the tag (n toward you), x right, y up
    h = size / 2.0
    return np.array([c - h * right + h * up, c + h * right + h * up, c + h * right - h * up, c - h * right - h * up])


class CutterTags:
    def __init__(self, tags=None, size=None, dict_name=None):
        self.tags = tags or config.TAGS
        self.size = size or config.TAG_SIZE_MM
        self.corners3d = {i: tag_corners_on_cutter(t, self.size) for i, t in self.tags.items()}
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.detector = cv2.aruco.ArucoDetector(_dictionary(dict_name), params)
        self._prev = None

    def detect(self, frame):
        """-> {tag id: 4x2 corner pixels} for OUR tags only."""
        gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self.detector.detectMarkers(gray)
        out = {}
        if ids is not None:
            for c, i in zip(corners, ids.ravel()):
                if int(i) in self.corners3d:
                    out[int(i)] = c.reshape(4, 2).astype(np.float64)
        return out

    def pose(self, found, K, dist=None):
        """found: from detect(). -> (R cutter->camera, t = scalp-face center in camera mm, n tags, reproj px)
        or None."""
        if not found:
            self._prev = None
            return None
        obj = np.concatenate([self.corners3d[i] for i in found]).astype(np.float64)
        img = np.concatenate([found[i] for i in found]).astype(np.float64)
        dist = np.zeros(5) if dist is None else dist
        best = None
        if len(found) == 1:
            # one flat square: IPPE gives the 2 possible poses; keep the one closest to last frame (or best fit)
            i = next(iter(found))
            ok, rvecs, tvecs, errs = cv2.solvePnPGeneric(obj, img, K, dist, flags=cv2.SOLVEPNP_IPPE)
            if not ok:
                return None
            cands = list(zip(rvecs, tvecs, np.ravel(errs)))
            if self._prev is not None:
                Rp = cv2.Rodrigues(self._prev[0])[0]
                cands.sort(key=lambda c: np.linalg.norm(cv2.Rodrigues(c[0])[0] - Rp))
            else:
                cands.sort(key=lambda c: c[2])
            rvec, tvec = cands[0][0], cands[0][1]
            # the tag must face the camera
            n_cam = cv2.Rodrigues(rvec)[0] @ np.asarray(self.tags[i]["normal"], float)
            if n_cam[2] > 0 and len(cands) > 1:
                rvec, tvec = cands[1][0], cands[1][1]
            best = (rvec, tvec)
        else:
            guess = self._prev
            ok, rvec, tvec = cv2.solvePnP(obj, img, K, dist, *(guess if guess else ()),
                                          useExtrinsicGuess=guess is not None, flags=cv2.SOLVEPNP_ITERATIVE)
            if not ok:
                return None
            best = (rvec, tvec)
        rvec, tvec = best
        proj, _ = cv2.projectPoints(obj, rvec, tvec, K, dist)
        err = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img) ** 2, axis=1))))
        if err > 6.0:                                   # corners don't fit the cutter: wrong tag or bad read
            self._prev = None
            return None
        self._prev = (rvec.copy(), tvec.copy())
        return cv2.Rodrigues(rvec)[0], tvec.ravel(), len(found), err


def cutter_in_head(R_cut, t_cut, R_head, t_head):
    """Cutter pose (camera) + head pose (camera, from the face tracker) -> (scalp-face point, into-scalp axis)
    in head axes. Both poses must come from the same camera picture and the same camera matrix."""
    point = R_head.T @ (np.asarray(t_cut, float) - np.asarray(t_head, float).ravel())
    axis = R_head.T @ (R_cut @ np.array([0.0, 0.0, 1.0]))
    return point, axis


def draw(frame, found, pose, K, dist=None):
    """Outline seen tags; draw the cutter axes at the scalp face (red x, green y, blue = into the scalp)."""
    for i, c in found.items():
        pts = c.astype(int)
        cv2.polylines(frame, [pts], True, (0, 200, 255), 2)
        cv2.putText(frame, f"{i} {config.TAGS[i]['name']}", tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 200, 255), 1, cv2.LINE_AA)
    if pose is not None:
        R, t, _, _ = pose
        ax = np.array([[0, 0, 0], [30, 0, 0], [0, 30, 0], [0, 0, 30]], float)
        p, _ = cv2.projectPoints(ax, cv2.Rodrigues(R)[0], t, K, np.zeros(5) if dist is None else dist)
        p = p.reshape(-1, 2).astype(int)
        for k, col in zip(range(1, 4), [(0, 0, 255), (0, 255, 0), (255, 0, 0)]):
            cv2.line(frame, tuple(p[0]), tuple(p[k]), col, 2, cv2.LINE_AA)
    return frame


def print_sheet(path, dpi=300):
    """A white sheet with every tag at its real size plus a 50 mm check bar. Print at 100% (no 'fit to page')."""
    mm = dpi / 25.4
    size = int(round(config.TAG_SIZE_MM * mm))
    quiet = int(round(4 * mm))                          # white border around each tag (needed to detect it)
    W, H = int(210 * mm), int(297 * mm)                 # A4 / fits on US letter too
    sheet = np.full((H, W), 255, np.uint8)
    d = _dictionary()
    x, y = int(15 * mm), int(20 * mm)
    for i, t in config.TAGS.items():
        img = cv2.aruco.generateImageMarker(d, i, size)
        sheet[y:y + size, x:x + size] = img
        cv2.putText(sheet, f"id {i}: {t['name']}  (top edge = 'up')", (x, y + size + int(6 * mm)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9 * dpi / 300, 0, 2)
        x += size + quiet * 6
        if x + size > W - int(15 * mm):
            x, y = int(15 * mm), y + size + int(20 * mm)
    yb = H - int(30 * mm)
    cv2.rectangle(sheet, (int(15 * mm), yb), (int(65 * mm), yb + int(3 * mm)), 0, -1)
    cv2.putText(sheet, f"this bar must measure 50 mm. tag squares: {config.TAG_SIZE_MM:g} mm",
                (int(15 * mm), yb + int(10 * mm)), cv2.FONT_HERSHEY_SIMPLEX, 0.8 * dpi / 300, 0, 2)
    cv2.imwrite(path, sheet)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print", dest="sheet", help="write a printable sheet of the tags (PNG)")
    ap.add_argument("--camera", type=int, help="live test with this webcam")
    ap.add_argument("--fov", type=float, default=60.0, help="camera horizontal field of view (deg)")
    a = ap.parse_args()
    if a.sheet:
        print("Wrote", print_sheet(a.sheet), "- print at 100% scale and check the 50 mm bar.")
    if a.camera is None:
        return
    cap = cv2.VideoCapture(a.camera)
    tags = CutterTags()
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        f = (w / 2) / np.tan(np.radians(a.fov / 2))
        K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
        found = tags.detect(frame)
        pose = tags.pose(found, K)
        draw(frame, found, pose, K)
        if pose is not None:
            cv2.putText(frame, f"{pose[2]} tag(s), scalp face at {np.round(pose[1]).astype(int)} mm, fit {pose[3]:.1f} px",
                        (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imshow("HairBarbot cutter tags (q quits)", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break


if __name__ == "__main__":
    main()
