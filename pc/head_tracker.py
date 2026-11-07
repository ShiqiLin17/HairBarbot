"""Watches the client's head with a webcam and says whether it is safe to keep cutting.

CameraTracker uses MediaPipe Face Mesh to find face landmarks, then OpenCV solvePnP to get the
head's position/rotation. At calibration we store a reference pose; if the head moves or turns
too much from it, or the face disappears, snapshot()["ok"] goes False and the controller stops.

The chin rest does most of the work of keeping the head still - this is the safety net.
"""
import threading
import time

import numpy as np

import config

# Generic 3D face model points (mm) and the matching MediaPipe Face Mesh landmark indices
MODEL_POINTS = np.array([
    (0.0, 0.0, 0.0),          # nose tip          -> 1
    (0.0, -63.6, -12.5),      # chin              -> 152
    (-43.3, 32.7, -26.0),     # right eye outer   -> 33  (image left)
    (43.3, 32.7, -26.0),      # left eye outer    -> 263 (image right)
    (-28.9, -28.9, -24.1),    # right mouth corner-> 61
    (28.9, -28.9, -24.1),     # left mouth corner -> 291
], dtype=np.float64)
LANDMARK_IDS = [1, 152, 33, 263, 61, 291]


class SimTracker:
    """Always sees a still head, unless you call simulate_move() (button in the app's sim panel)."""
    def __init__(self):
        self._bump_until = 0.0

    def start(self):
        pass

    def set_reference(self):
        return True

    def simulate_move(self, seconds=1.5):
        self._bump_until = time.time() + seconds

    def snapshot(self):
        if time.time() < self._bump_until:
            return {"ok": False, "face": True, "move_mm": 15.0, "rot_deg": 2.0, "reason": "head moved 15 mm (simulated)"}
        return {"ok": True, "face": True, "move_mm": 0.0, "rot_deg": 0.0, "reason": ""}

    def jpeg(self):
        return None


class CameraTracker:
    def __init__(self, camera_index=config.CAMERA_INDEX):
        self.camera_index = camera_index
        self.lock = threading.Lock()
        self.ref = None              # (rvec, tvec) at calibration
        self.last_pose = None
        self.last_face_t = 0.0
        self.history = []            # recent (move_mm, rot_deg) for median filtering
        self._jpeg = None
        self.running = False

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        import cv2
        import mediapipe as mp
        cap = cv2.VideoCapture(self.camera_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        mesh = mp.solutions.face_mesh.FaceMesh(max_num_faces=1, refine_landmarks=False,
                                               min_detection_confidence=0.5, min_tracking_confidence=0.5)
        while self.running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            h, w = frame.shape[:2]
            res = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            if res.multi_face_landmarks:
                lm = res.multi_face_landmarks[0].landmark
                img_pts = np.array([(lm[i].x * w, lm[i].y * h) for i in LANDMARK_IDS], dtype=np.float64)
                cam = np.array([[w, 0, w / 2], [0, w, h / 2], [0, 0, 1]], dtype=np.float64)
                okp, rvec, tvec = cv2.solvePnP(MODEL_POINTS, img_pts, cam, np.zeros(4),
                                               flags=cv2.SOLVEPNP_ITERATIVE)
                if okp:
                    with self.lock:
                        self.last_pose = (rvec.copy(), tvec.copy())
                        self.last_face_t = time.time()
                        if self.ref is not None:
                            self.history.append(self._delta(self.last_pose))
                            self.history = self.history[-3:]
                for (x, y) in img_pts:
                    cv2.circle(frame, (int(x), int(y)), 3, (0, 255, 0), -1)
            snap = self.snapshot()
            color = (0, 200, 0) if snap["ok"] else (0, 0, 255)
            cv2.putText(frame, "OK" if snap["ok"] else snap["reason"], (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            okj, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if okj:
                with self.lock:
                    self._jpeg = buf.tobytes()

    def _delta(self, pose):
        import cv2
        rvec, tvec = pose
        r0, t0 = self.ref
        move = float(np.linalg.norm(tvec - t0))
        R0, _ = cv2.Rodrigues(r0)
        R1, _ = cv2.Rodrigues(rvec)
        dR = R0.T @ R1
        rot = float(np.degrees(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1.0, 1.0))))
        return move, rot

    def set_reference(self):
        """Call when the client is seated and still (end of calibration)."""
        with self.lock:
            if self.last_pose is None or time.time() - self.last_face_t > 0.5:
                return False
            self.ref = self.last_pose
            self.history = []
            return True

    def snapshot(self):
        with self.lock:
            age = time.time() - self.last_face_t
            hist = list(self.history)
            has_ref = self.ref is not None
        if age > config.FACE_LOST_S:
            return {"ok": False, "face": False, "move_mm": None, "rot_deg": None, "reason": "face not visible"}
        if not has_ref or not hist:
            return {"ok": False, "face": True, "move_mm": None, "rot_deg": None, "reason": "not calibrated"}
        move = float(np.median([m for m, _ in hist]))
        rot = float(np.median([r for _, r in hist]))
        if move > config.HEAD_MOVE_MM:
            return {"ok": False, "face": True, "move_mm": move, "rot_deg": rot, "reason": f"head moved {move:.0f} mm"}
        if rot > config.HEAD_ROT_DEG:
            return {"ok": False, "face": True, "move_mm": move, "rot_deg": rot, "reason": f"head turned {rot:.0f} deg"}
        return {"ok": True, "face": True, "move_mm": move, "rot_deg": rot, "reason": ""}

    def jpeg(self):
        with self.lock:
            return self._jpeg
