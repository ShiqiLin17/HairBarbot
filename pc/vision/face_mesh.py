"""MediaPipe Face Landmarker: 478 3D face points that keep tracking when the head turns (about ±60-70°).

The model file (~3.6 MB) downloads automatically into pc/vision/models the first time.
If MediaPipe isn't installed or the download fails, head_scalp.py falls back to the simpler
YuNet detector (needs both eyes visible).
"""
import os
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "models", "face_landmarker.task")
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"

# Landmark indices for the 5 points our 3D face model uses (person's right/left)
RIGHT_EYE = (33, 133)      # outer + inner corner of the person's right eye
LEFT_EYE = (362, 263)
NOSE_TIP = 1
MOUTH_RIGHT, MOUTH_LEFT = 61, 291


def five_points(px):
    """478 landmark pixels -> right eye, left eye, nose tip, right mouth corner, left mouth corner."""
    return np.array([px[list(RIGHT_EYE)].mean(axis=0), px[list(LEFT_EYE)].mean(axis=0), px[NOSE_TIP],
                     px[MOUTH_RIGHT], px[MOUTH_LEFT]], dtype=np.float64)


def ensure_model(path=MODEL_PATH, url=MODEL_URL):
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print("Downloading the MediaPipe face model (one time, ~3.6 MB)...")
    tmp = path + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, path)
    return path


class FaceMesh:
    def __init__(self, model_path=MODEL_PATH):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        self.mp = mp
        opts = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=ensure_model(model_path)),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            min_face_detection_confidence=0.5, min_face_presence_confidence=0.5, min_tracking_confidence=0.5)
        self.landmarker = vision.FaceLandmarker.create_from_options(opts)
        self.edges = np.array([(c.start, c.end) for c in vision.FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION])
        self._t = 0

    def detect(self, frame_bgr):
        """-> (px Nx2 pixels, z N (MediaPipe depth, same scale as x in pixels, 0 = head center)) or None."""
        import cv2
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        self._t += 33                                   # timestamps must increase in VIDEO mode
        res = self.landmarker.detect_for_video(image, self._t)
        if not res.face_landmarks:
            return None
        lm = res.face_landmarks[0]
        px = np.array([[p.x * w, p.y * h] for p in lm], dtype=np.float64)
        z = np.array([p.z * w for p in lm], dtype=np.float64)
        return px, z


def mesh_to_head(px, z, K, R, t):
    """Back-project the 2D mesh into 3D head coordinates (mm), using the head pose (R, t).
    MediaPipe's z is depth relative to the head center, in the same units as x (pixels here)."""
    f, cx, cy = K[0, 0], K[0, 2], K[1, 2]
    tz = float(t[2])
    Zc = tz + z * tz / f
    pc = np.stack([(px[:, 0] - cx) * Zc / f, (px[:, 1] - cy) * Zc / f, Zc], axis=1)
    return (pc - np.asarray(t).reshape(1, 3)) @ R          # = R^T (p - t) for each row
