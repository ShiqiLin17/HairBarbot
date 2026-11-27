"""Cutter tracking: ArUco tags, force pads and the IMU together.   python tests/test_cutter_tracking.py"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "vision"))

import cv2
import numpy as np

import config
from app import create_app
from orientation import axis_angle

from cutter_tags import CutterTags, _dictionary, cutter_in_head


# ---------------------------------------------------------------- helpers
def render_cutter(R, t, K, W=1280, H=720):
    """Draw the cutter's tags into a fake camera picture for a known cutter pose (R cutter->camera, t mm)."""
    img = np.full((H, W), 200, np.uint8)
    tags = CutterTags()
    d = _dictionary()
    px = 200
    for i, c3 in tags.corners3d.items():
        if (R @ np.array(config.TAGS[i]["normal"]))[2] > -0.15:      # facing away from the camera
            continue
        pc = (R @ c3.T).T + t
        p = (K @ pc.T).T
        p = p[:, :2] / p[:, 2:]
        m = cv2.aruco.generateImageMarker(d, i, px)
        b = px // 6
        m = cv2.copyMakeBorder(m, b, b, b, b, cv2.BORDER_CONSTANT, value=255)
        src = np.float32([[b, b], [b + px, b], [b + px, b + px], [b, b + px]])
        Hm = cv2.getPerspectiveTransform(src, np.float32(p))
        warped = cv2.warpPerspective(m, Hm, (W, H))
        mask = cv2.warpPerspective(np.full(m.shape, 255, np.uint8), Hm, (W, H))
        img[mask > 0] = warped[mask > 0]
    return img


def rot_err(Ra, Rb):
    return float(np.degrees(np.arccos(np.clip((np.trace(Ra.T @ Rb) - 1) / 2, -1, 1))))


def wait(c, cond, timeout=20):
    t = time.time() + timeout
    while time.time() < t:
        s = c.get("/api/state").get_json()
        if cond(s):
            return s
        time.sleep(0.03)
    raise AssertionError(f"{s['state']}: {s['message']} block={s['live']['block']}")


def ready(**kw):
    app = create_app(sim=True, **kw)
    c = app.test_client()
    c.post("/api/home")
    wait(c, lambda s: s["state"] == "IDLE")
    c.post("/api/calibrate/default")
    return app, c, app.config["ctl"]


def ang_err(loc, yaw, pitch):
    dy = (loc[0] - yaw + 180) % 360 - 180
    return max(abs(dy) * np.sin(np.radians(max(pitch, 1))), abs(loc[1] - pitch))


# ---------------------------------------------------------------- tags in a picture
def test_tags_give_the_cutter_pose():
    K = np.array([[900.0, 0, 640], [0, 900.0, 360], [0, 0, 1]])
    tags = CutterTags()
    for ang in [0, 30, 60, 100]:          # turning the cutter: 1 tag, 2 tags, 2 tags, 1 tag in view
        R = axis_angle([0, 1, 0], ang) @ axis_angle([1, 0, 0], -100)
        t = np.array([20.0, -10.0, 400.0])
        tags._prev = None
        found = tags.detect(render_cutter(R, t, K))
        pose = tags.pose(found, K)
        assert pose is not None, ang
        Rm, tm, n, err = pose
        assert np.linalg.norm(tm - t) < 8 and rot_err(Rm, R) < 5, (ang, tm, rot_err(Rm, R))
        if n >= 2:                         # two tags: much better
            assert np.linalg.norm(tm - t) < 3 and rot_err(Rm, R) < 1.5, (ang, tm, rot_err(Rm, R))


def test_cutter_in_head_frame():
    R_head = axis_angle([0, 0, 1], 25) @ axis_angle([0, 1, 0], 10)       # head -> camera
    t_head = np.array([10.0, -20.0, 450.0])
    p_true = np.array([30.0, 60.0, 50.0])                                # on the head, head axes
    a_true = -p_true / np.linalg.norm(p_true)                            # pointing into the head
    # any cutter rotation whose z axis is a_true (in camera axes: R_head @ a_true)
    z = R_head @ a_true
    x = np.cross([0, 1, 0], z)
    x /= np.linalg.norm(x)
    R_cut = np.column_stack([x, np.cross(z, x), z])
    p, a = cutter_in_head(R_cut, R_head @ p_true + t_head, R_head, t_head)
    assert np.allclose(p, p_true) and np.allclose(a, a_true)


def test_print_sheet():
    import tempfile
    from cutter_tags import print_sheet
    with tempfile.TemporaryDirectory() as d:
        path = print_sheet(os.path.join(d, "tags.png"), dpi=150)
        img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        assert set(CutterTags().detect(img)) == set(config.TAGS)


# ---------------------------------------------------------------- tags + IMU in the controller
def test_tags_correct_imu_drift_at_the_back_of_the_head():
    # IMU heading drifts 40 deg per (real) minute here, so the effect is big in a short test
    results = {}
    for tags_on in (True, False):
        app, c, ctl = ready(speedup=20, imu_drift=2.0, sim_tags=tags_on)
        ctl.link.sim_place(20, 40)                  # front-left: the camera sees the tags
        time.sleep(12)                             # ~8 deg of drift builds up meanwhile
        ctl.link.sim_place(170, 85)                 # back of the head: no tags, IMU only
        time.sleep(0.2)
        assert ctl.loc_source == "imu"
        results[tags_on] = ang_err(ctl.loc, 170, 85)
    assert results[True] < 2.5, results
    assert results[False] > 5, results              # what the tags fix


def test_lifted_cutter_is_seen_but_cannot_cut():
    app, c, ctl = ready(speedup=20, imu_drift=0.0)
    c.post("/api/start", json={"lengths": {r: 20 for r in ["top", "front", "sides", "back", "nape"]}})
    ctl.link.sim_auto(False)
    ctl.link.trigger = True
    ctl.link.sim_place(0, 35)
    wait(c, lambda s: s["machine"]["clipper"])
    c.post("/api/sim/lift")
    s = wait(c, lambda s: s["live"]["block"] == "contact")
    assert s["location"] is not None and not s["live"]["seated"]
    time.sleep(0.05)
    assert not c.get("/api/state").get_json()["machine"]["clipper"]


def test_iphone_sightings_and_disagreement():
    # no simulated camera tags: the "iPhone" posts sightings through the API instead
    app, c, ctl = ready(speedup=20, imu_drift=0.0, sim_tags=False)
    c.post("/api/start", json={"lengths": {r: 20 for r in ["top", "front", "sides", "back", "nape"]}})
    ctl.link.sim_auto(False)
    ctl.link.trigger = True
    ctl.link.sim_place(-40, 45)
    wait(c, lambda s: s["machine"]["clipper"])
    surf = ctl.locator
    good_p, good_n = surf.point(-40, 45), surf.normal(-40, 45)
    for _ in range(8):                               # the iPhone agrees with the IMU
        r = c.post("/api/cutter", json={"point_mm": list(good_p), "axis": list(-good_n), "age_s": 0.02, "tags": 2})
        assert r.get_json()["accepted"]
        time.sleep(0.03)
    assert ctl.fusion.trusted() and ctl.loc_source == "tags"
    # a sighting far off the head (a misread) is rejected
    r = c.post("/api/cutter", json={"point_mm": [0, 0, 300], "axis": [0, 0, -1]})
    assert not r.get_json()["accepted"]
    # a sighting ON the head but somewhere else entirely: tags and IMU disagree -> clipper off
    bad_p, bad_n = surf.point(60, 45), surf.normal(60, 45)
    t_end = time.time() + 2
    blocked = False
    while time.time() < t_end and not blocked:
        c.post("/api/cutter", json={"point_mm": list(bad_p), "axis": list(-bad_n)})
        s = c.get("/api/state").get_json()
        blocked = s["live"]["block"] == "unsure"
        time.sleep(0.02)
    assert blocked
    for _ in range(5):                              # while the bad sightings keep coming, the clipper stays off
        c.post("/api/cutter", json={"point_mm": list(bad_p), "axis": list(-bad_n)})
        time.sleep(0.02)
    assert not c.get("/api/state").get_json()["machine"]["clipper"]
    # the misread didn't change what the IMU learned: once it stops, the IMU alone finds the right spot
    time.sleep(config.MARKER_FRESH_S + 0.1)
    assert ctl.loc_source == "imu" and ang_err(ctl.loc, -40, 45) < 2, ctl.loc


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
