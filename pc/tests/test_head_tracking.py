"""Camera head tracking + head shape in the controller:  python tests/test_head_tracking.py"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import config
import orientation
from app import create_app


def wait(c, cond, timeout=30):
    t = time.time() + timeout
    while time.time() < t:
        s = c.get("/api/state").get_json()
        if cond(s):
            return s
        time.sleep(0.05)
    raise AssertionError(s["state"] + ": " + s["message"])


def ready(sim_camera=True, head=None):
    # IMU-only location here (no cutter tags, no drift): these tests check the camera's HEAD tracking.
    # The tags are tested in test_cutter_tracking.py.
    app = create_app(sim=True, speedup=20, head=head, sim_camera=sim_camera, sim_tags=False, imu_drift=0.0)
    c = app.test_client()
    c.post("/api/home")
    wait(c, lambda s: s["state"] == "IDLE")
    return app, c, app.config["ctl"]


def ang_err(loc, yaw, pitch):
    dy = (loc[0] - yaw + 180) % 360 - 180
    return max(abs(dy) * np.sin(np.radians(max(pitch, 1))), abs(loc[1] - pitch))


def located(ctl, yaw, pitch):
    ctl.link.sim_place(yaw, pitch)
    time.sleep(0.12)
    return ctl.loc


def test_head_turn_is_followed_with_camera():
    app, c, ctl = ready()
    c.post("/api/calibrate/default")
    assert ang_err(located(ctl, 120, 70), 120, 70) < 2
    ctl.link.sim_turn_head(35, seconds=0.2)          # user turns their head 35 deg to the left
    time.sleep(0.15)
    for spot in [(120, 70), (-60, 50), (180, 95), (30, 30)]:
        assert ang_err(located(ctl, *spot), *spot) < 2, (spot, ctl.loc)
    assert c.get("/api/state").get_json()["camera"]["active"]


def test_without_camera_a_head_turn_confuses_the_sides():
    app, c, ctl = ready(sim_camera=False)
    c.post("/api/calibrate/default")
    ctl.link.sim_turn_head(35, seconds=0.2)
    time.sleep(0.15)
    assert ang_err(located(ctl, 120, 70), 120, 70) > 15      # this is what the camera fixes


def test_calibration_while_the_head_moves():
    app, c, ctl = ready()
    c.post("/api/calibrate/start")
    for i, turn in enumerate([0, 15, -10, 25]):              # head turns a bit between spots
        ctl.link.sim_turn_head(turn, seconds=0.05)
        time.sleep(0.05)
        r = c.post(f"/api/calibrate/record/{i}")
        assert r.status_code == 200, r.get_json()
    r = c.post("/api/calibrate/finish")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["status"]["calibration"]["error_deg"] < 2
    for spot in [(90, 60), (-150, 90), (10, 20)]:
        assert ang_err(located(ctl, *spot), *spot) < 3, (spot, ctl.loc)


def test_face_out_of_view_pauses_the_clipper():
    app, c, ctl = ready()
    c.post("/api/calibrate/default")
    c.post("/api/start", json={"lengths": {"top": 20, "front": 20, "sides": 20, "back": 20, "nape": 20}})
    wait(c, lambda s: s["machine"]["clipper"], 20)
    ctl.camera.hidden = True
    s = wait(c, lambda s: s["live"]["block"] == "camera", 5)
    time.sleep(0.1)
    assert not c.get("/api/state").get_json()["machine"]["clipper"]
    ctl.camera.hidden = False
    wait(c, lambda s: s["machine"]["clipper"], 10)
    c.post("/api/stop")


def test_head_shape_changes_where_the_spot_is():
    # same device direction, round head vs real (longer, narrower) head: different spot on the side
    from orientation import SurfaceLocator, direction
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vision"))
    from head_profile import average_profile
    real = SurfaceLocator(average_profile("male"))
    n = real.normal(45, 50)
    yaw_round, _ = orientation.yaw_pitch(n)
    yaw_real, _ = real.spot(n)
    assert abs(yaw_real - 45) < 1 and abs(yaw_round - 45) > 5


def test_forehead_from_camera_sets_front_limit():
    app, c, ctl = ready()
    ctl.camera.forehead_pitch = lambda: 52.0
    c.post("/api/calibrate/default")
    ctl._apply_forehead()
    assert abs(orientation.max_pitch(0) - 49.0) < 0.01 and ctl.forehead_pitch == 49.0
    assert not orientation.in_cut_zone(0, 52)
    orientation.reset_zones()


def test_scan_profile_used_by_controller():
    import tempfile
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
    from test_head_scan import synthetic_head, to_phone_scan, write_obj
    from head_scan import import_scan
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.obj")
        write_obj(p, to_phone_scan(synthetic_head(), 20))
        prof_path = import_scan(p, name="t").save(os.path.join(d, "t.json"))
        app, c, ctl = ready(head=prof_path)
        assert c.get("/api/state").get_json()["head"]["scan"]
        c.post("/api/calibrate/default")
        for spot in [(90, 60), (-120, 80), (0, 30)]:
            assert ang_err(located(ctl, *spot), *spot) < 2, (spot, ctl.loc)
        assert len(c.get("/api/head").get_json()["grid"]) > 10


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
