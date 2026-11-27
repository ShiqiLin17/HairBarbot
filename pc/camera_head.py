"""Camera head tracking for the controller.

The webcam watches the user's face (same code as vision/head_scalp.py) and reports the head's rotation
relative to the camera. The controller uses it so the user can turn their head while cutting:

  room -> head (now) = R_cam(now)^T @ R_cam(calibration) @ M

where M is the calibration and R_cam is the head -> camera rotation from the face. The camera's own
placement cancels out, so it only has to stay still (on the table, facing the user).

It also measures the top of the forehead (the top of the face mesh), which the controller uses as this
person's front no-cut line instead of the average.

And it looks for the ArUco tags on the cutter (vision/cutter_tags.py) in the same picture. With the head pose
from the face, that gives where the cutter touches the head (a "sighting", in head axes), which the controller
combines with the IMU (cutter_tracking.py).
"""
import math
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "vision"))

FOREHEAD_LANDMARK = 10        # MediaPipe face mesh: top-center of the forehead


class CameraHead:
    """Runs the face tracker in a background thread."""
    def __init__(self, camera_index=0, profile=None, fov=60.0, style="fade25"):
        import cv2
        from head_scalp import HeadScalpEstimator, draw
        self.cv2, self._draw = cv2, draw
        self.est = HeadScalpEstimator(fov_deg=fov, profile=profile)
        self.style = style
        self.cap = cv2.VideoCapture(camera_index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Can't open camera {camera_index} (allow camera access for your terminal).")
        self.lock = threading.Lock()
        self.R, self.t_seen, self.found, self.yaw = None, 0.0, False, None
        self._forehead = []
        self._jpeg = None
        self.tracker = self.est.tracker
        self.tags = None
        try:
            from cutter_tags import CutterTags
            self.tags = CutterTags()
        except Exception as e:          # old OpenCV without aruco: head tracking still works
            print(f"[camera] cutter tags disabled: {e}")
        self._sighting = None           # (t, point, axis, n_tags)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        cv2 = self.cv2
        while True:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue
            e = self.est.estimate(frame, self.style)
            fresh = e.found and not e.holding
            K = self.est.camera_matrix(frame.shape[1], frame.shape[0])
            found, cpose = {}, None
            if self.tags is not None:
                from cutter_tags import cutter_in_head
                found = self.tags.detect(frame)
                cpose = self.tags.pose(found, K)
                if cpose is not None and fresh:
                    p, a = cutter_in_head(cpose[0], cpose[1], cv2.Rodrigues(e.rvec)[0], e.tvec)
                    with self.lock:
                        self._sighting = (time.time(), p, a, cpose[2])
            with self.lock:
                if fresh:
                    self.R = cv2.Rodrigues(e.rvec)[0]
                    self.t_seen = time.time()
                    self.yaw = e.yaw
                    if e.mesh_head is not None:
                        p = e.mesh_head[FOREHEAD_LANDMARK]
                        self._forehead.append(math.degrees(math.acos(max(-1, min(1, p[2] / np.linalg.norm(p))))))
                        self._forehead = self._forehead[-60:]
                self.found = fresh
            if found:
                from cutter_tags import draw as draw_tags
                draw_tags(frame, found, cpose, K)
            out = self._draw(frame, e, K, self.style,
                             mirror=True, profile=self.est.profile, mesh_edges=self.est.mesh_edges,
                             tracker=self.tracker)
            ok, buf = cv2.imencode(".jpg", cv2.resize(out, (480, int(480 * out.shape[0] / out.shape[1]))),
                                   [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                with self.lock:
                    self._jpeg = buf.tobytes()

    def pose(self):
        """-> (R head->camera or None, seconds since the face was last seen)."""
        with self.lock:
            return (None if self.R is None else self.R.copy()), time.time() - self.t_seen

    def forehead_pitch(self):
        with self.lock:
            return float(np.median(self._forehead)) if len(self._forehead) >= 10 else None

    def sighting(self):
        """Latest cutter sighting: (time, scalp-face point mm, into-scalp axis, tags seen), head axes; or None."""
        with self.lock:
            return self._sighting

    def info(self):
        R, age = self.pose()
        return {"enabled": True, "simulated": False, "found": bool(age < 0.3), "tags": self.tags is not None,
                "yaw": None if self.yaw is None else float(self.yaw),
                "tracker": self.tracker, "forehead_pitch": self.forehead_pitch()}

    def jpeg(self):
        with self.lock:
            return self._jpeg


class SimCameraHead:
    """Simulated camera: reads the simulated user's real head rotation from SimLink, and "sees" the cutter's
    tags whenever the cutter is on the side of the head facing the camera (not the back)."""
    TAG_NOISE_MM = 1.5

    def __init__(self, link, tags=True):
        self.link = link
        self.tracker = "simulated"
        self.hidden = False             # test hook: the face is out of view
        self.tags = tags                # simulate the cutter's tags
        self.tags_hidden = False        # test hook: a hand covers the tags
        self._rng = np.random.default_rng(3)

    def pose(self):
        if self.hidden:
            return self.link.head_to_camera(), 99.0
        return self.link.head_to_camera(), 0.0

    def forehead_pitch(self):
        return None

    def sighting(self):
        if not self.tags or self.tags_hidden or self.hidden:
            return None
        s = self.link.sim_cutter_truth()            # (point, axis) in head axes
        if s is None:
            return None
        point, axis = s
        # the camera sits in front of the face: it sees the tags when the cutter's spot faces it
        to_cam = self.link.head_to_camera().T @ np.array([0.0, 0.0, -1.0])     # head axes, toward the camera
        if float(-axis @ to_cam) < -0.25:            # spot faces away (back of the head)
            return None
        noise = self._rng.normal(0, self.TAG_NOISE_MM, 3)
        return (time.time(), point + noise, axis, 2)

    def info(self):
        return {"enabled": True, "simulated": True, "found": not self.hidden, "tags": self.tags,
                "yaw": float(self.link.head_yaw),
                "tracker": self.tracker, "forehead_pitch": None}

    def jpeg(self):
        return None
