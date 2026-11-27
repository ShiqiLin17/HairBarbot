"""Tests for the face -> head pose -> scalp estimate:  python tests/test_vision.py"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vision"))

import cv2
import numpy as np

from head_scalp import FACE_POINTS, HeadScalpEstimator, _head_to_cam_facing, draw, head_angles, order_landmarks


def rot(axis, deg):
    v = np.asarray(axis, float) * math.radians(deg)
    R, _ = cv2.Rodrigues(v)
    return R


def make_pose(yaw, pitch, roll, dist=500.0, dx=0.0, dy=0.0):
    """Head turned (yaw: to their left, pitch: up, roll: toward left shoulder), in camera coordinates."""
    # rotations in the HEAD frame (x fwd, y left, z up): yaw about z, pitch about -y (nose up), roll about x
    R_head = rot([0, 0, 1], yaw) @ rot([0, -1, 0], pitch) @ rot([1, 0, 0], -roll)
    R = _head_to_cam_facing() @ R_head
    return R, np.array([dx, dy, dist], dtype=float)


def project(R, t, K):
    rvec, _ = cv2.Rodrigues(R)
    px, _ = cv2.projectPoints(FACE_POINTS, rvec, t.reshape(3, 1), K, None)
    return px.reshape(-1, 2)


def test_angles_signs():
    for yaw, pitch, roll in [(0, 0, 0), (25, 0, 0), (-25, 0, 0), (0, 15, 0), (0, -15, 0), (0, 0, 12), (20, 10, -8)]:
        R, _ = make_pose(yaw, pitch, roll)
        y, p, r = head_angles(R)
        assert abs(y - yaw) < 0.5 and abs(p - pitch) < 0.5 and abs(r - roll) < 0.5, ((yaw, pitch, roll), (y, p, r))


def test_facing_camera_puts_right_eye_on_image_left():
    est = HeadScalpEstimator(tracker="yunet")
    K = est.camera_matrix(640, 480)
    R, t = make_pose(0, 0, 0)
    px = project(R, t, K)
    assert px[0, 0] < px[1, 0]          # person's right eye is further left in the image
    assert px[2, 1] > px[0, 1]          # nose below the eyes


def test_pose_recovered_from_landmarks_even_with_swapped_labels():
    est = HeadScalpEstimator(smooth=0, tracker="yunet")
    K = est.camera_matrix(640, 480)
    for yaw, pitch, roll, dist in [(0, 0, 0, 450), (30, 5, 0, 500), (-35, -10, 5, 600), (15, 15, -10, 400)]:
        R, t = make_pose(yaw, pitch, roll, dist, dx=20, dy=-15)
        px = project(R, t, K)
        swapped = px[[1, 0, 2, 4, 3]]                # detector labels left/right the other way round
        est._prev = None
        rvec, tvec, err = est.solve_pose(order_landmarks(swapped), 640, 480)
        y, p, r = head_angles(cv2.Rodrigues(rvec)[0])
        assert err < 0.5, err
        assert abs(y - yaw) < 2 and abs(p - pitch) < 2 and abs(r - roll) < 2, ((yaw, pitch, roll), (y, p, r))
        assert abs(np.linalg.norm(tvec) - np.linalg.norm(t)) < 10


def test_scalp_is_above_the_face_and_drawn():
    est = HeadScalpEstimator(smooth=0, tracker="yunet")
    K = est.camera_matrix(640, 480)
    R, t = make_pose(0, -5, 0, 600)
    px = project(R, t, K)
    # fake a detection so we can run the whole pipeline without a photo
    box = [px[:, 0].min() - 30, px[:, 1].min() - 40, np.ptp(px[:, 0]) + 60, np.ptp(px[:, 1]) + 90]
    fake = np.array(box + list(px.reshape(-1)) + [0.95], dtype=np.float32)
    est.detect = lambda frame: fake
    frame = np.full((480, 640, 3), 90, np.uint8)
    e = est.estimate(frame, "fade25")
    assert e.found and len(e.scalp_px) > 50
    eye_y = px[:2, 1].mean()
    assert np.mean([y for _, y, *_ in e.scalp_px]) < eye_y          # scalp is above the eyes
    assert e.crown_px and e.crown_px[1] < eye_y
    lengths = [L for *_, L in e.scalp_px]
    assert max(lengths) == 40 and min(lengths) < 30                  # fade 2 -> 4 cm shows on the head
    out = draw(frame, e, K, "fade25", mirror=True)
    assert out.shape == frame.shape


def test_no_face():
    est = HeadScalpEstimator(tracker="yunet")
    e = est.estimate(np.zeros((480, 640, 3), np.uint8))
    assert not e.found



# ---------------------------------------------------------------- MediaPipe path, with a simulated mesh
def fake_mesh(R, t, K, n=478, seed=0):
    """478 'face' points in head coordinates, with the 5 key landmarks placed on FACE_POINTS,
    projected like MediaPipe reports them: pixels + depth relative to the head center (pixel scale)."""
    from face_mesh import LEFT_EYE, MOUTH_LEFT, MOUTH_RIGHT, NOSE_TIP, RIGHT_EYE
    rng = np.random.default_rng(seed)
    P = np.column_stack([rng.uniform(70, 100, n), rng.uniform(-60, 60, n), rng.uniform(-70, 40, n)])
    for idx, c in zip(RIGHT_EYE, ([0, -12, 0], [0, 12, 0])):
        P[idx] = FACE_POINTS[0] + c
    for idx, c in zip(LEFT_EYE, ([0, -12, 0], [0, 12, 0])):
        P[idx] = FACE_POINTS[1] + c
    P[NOSE_TIP], P[MOUTH_RIGHT], P[MOUTH_LEFT] = FACE_POINTS[2], FACE_POINTS[3], FACE_POINTS[4]
    pc = P @ R.T + t
    f, cx, cy = K[0, 0], K[0, 2], K[1, 2]
    px = np.column_stack([f * pc[:, 0] / pc[:, 2] + cx, f * pc[:, 1] / pc[:, 2] + cy])
    z = (pc[:, 2] - t[2]) * f / t[2]
    return P, px, z


class FakeMesh:
    def __init__(self, px, z):
        self.px, self.z = px, z
        self.edges = np.array([(i, i + 1) for i in range(0, 470, 2)])

    def detect(self, frame):
        return self.px, self.z


def test_mediapipe_path_pose_and_3d_mesh():
    from face_mesh import mesh_to_head
    est = HeadScalpEstimator(smooth=0, tracker="yunet")
    K = est.camera_matrix(640, 480)
    R, t = make_pose(40, 5, 0, 550)          # head turned 40 deg: YuNet would often lose this
    P, px, z = fake_mesh(R, t, K)
    est.mesh = FakeMesh(px, z)
    est.mesh_edges = est.mesh.edges
    e = est.estimate(np.zeros((480, 640, 3), np.uint8))
    assert e.found and abs(e.yaw - 40) < 2 and e.mesh_px.shape == (478, 2)
    err = np.linalg.norm(e.mesh_head - P, axis=1)
    assert np.median(err) < 3, np.median(err)               # 3D mesh lands back where it was, within ~mm
    assert np.allclose(mesh_to_head(px, z, K, R, t), P, atol=1e-6)
    out = draw(np.zeros((480, 640, 3), np.uint8), e, K, mesh_edges=est.mesh_edges, tracker="mediapipe")
    assert out.any()


def test_hold_last_pose_briefly():
    est = HeadScalpEstimator(smooth=0, tracker="yunet")
    K = est.camera_matrix(640, 480)
    R, t = make_pose(0, 0, 0, 500)
    P, px, z = fake_mesh(R, t, K)
    est.mesh = FakeMesh(px, z)
    assert est.estimate(np.zeros((480, 640, 3), np.uint8)).found
    est.mesh.detect = lambda frame: None                      # face disappears
    e = est.estimate(np.zeros((480, 640, 3), np.uint8))
    assert e.found and e.holding


def test_viewer_renders_with_mesh():
    from head_profile import average_profile
    from head_viewer import HeadViewer
    est = HeadScalpEstimator(smooth=0, tracker="yunet")
    K = est.camera_matrix(640, 480)
    R, t = make_pose(0, 0, 0, 500)
    P, px, z = fake_mesh(R, t, K)
    img = HeadViewer().render(average_profile("female"), P, np.array([(i, i + 1) for i in range(0, 470, 2)]))
    assert img.shape == (560, 560, 3) and (img != img[0, 0]).any()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
