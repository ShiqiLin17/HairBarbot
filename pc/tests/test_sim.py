"""Tests in simulation:  python tests/test_sim.py   (or: python -m pytest tests)"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import config
from app import create_app
from orientation import calibrate, direction, in_cut_zone, matrix_to_quat, quat_to_matrix
from serial_link import _axis_angle
from styles import STYLES, guard_length


def wait(c, cond, timeout=60, what=""):
    t = time.time() + timeout
    while time.time() < t:
        s = c.get("/api/state").get_json()
        if cond(s):
            return s
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for {what}: state {s['state']}, {s['message']}")


def setup(speedup=40):
    app = create_app(sim=True, speedup=speedup)
    c = app.test_client()
    assert c.post("/api/home").status_code == 200
    wait(c, lambda s: s["state"] == "IDLE", what="homed")
    return app, c


def test_quaternion_roundtrip():
    for k in range(20):
        R = _axis_angle(np.random.randn(3), np.random.uniform(0, 180))
        assert np.allclose(quat_to_matrix(matrix_to_quat(R)), R, atol=1e-9)


def test_calibration_math_recovers_mounting():
    M_true = _axis_angle([0, 0, 1], 123) @ _axis_angle([1, 0, 0], 3)
    pairs = [(M_true.T @ direction(y, p), direction(y, p)) for _, y, p in config.CALIB_POSES]
    M, err = calibrate(pairs)
    assert np.allclose(M, M_true, atol=1e-6) and err < 1e-3


def test_calibrate_through_app_and_locate_with_wrist_roll():
    app, c = setup()
    ctl = app.config["ctl"]
    assert c.post("/api/calibrate/start").status_code == 200
    for i in range(len(config.CALIB_POSES)):
        r = c.post(f"/api/calibrate/record/{i}")
        assert r.status_code == 200, r.get_json()
    r = c.post("/api/calibrate/finish")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["status"]["calibration"]["error_deg"] < 3
    # location must follow the hand, whatever the wrist roll is doing
    for yaw, pitch in [(0, 20), (90, 50), (-120, 70), (175, 90), (-30, 40)]:
        ctl.link.sim_place(yaw, pitch)
        time.sleep(0.15)
        y, p = ctl.loc
        dy = (y - yaw + 180) % 360 - 180
        assert abs(p - pitch) < 3 and (abs(dy) < 3 or pitch < 5), (yaw, pitch, y, p)


def test_full_session_guard_follows_and_safety():
    # real time: the fake user moves at 30 deg/s, like a person (takes ~2-3 minutes)
    app, c = setup(speedup=1)
    ctl = app.config["ctl"]
    c.post("/api/calibrate/default")
    st = STYLES["fade"]
    r = c.post("/api/start", json={"lengths": st["lengths"], "fade_to": st["fade_to"], "style": "fade"})
    assert r.status_code == 200, r.get_json()
    # while cutting, the clipper must never be on with the wrong guard or in a no-cut zone
    checked = 0
    face_tested = trigger_tested = False
    t_end = time.time() + 400
    while time.time() < t_end:
        s = c.get("/api/state").get_json()
        if s["state"] != "CUTTING":
            break
        # check the TRUE state inside the simulator: where the hand really is vs the real guard length
        sim = ctl.link
        if sim.clip:
            yaw, pitch = sim.hand
            need = guard_length(yaw, pitch, st["lengths"], st["fade_to"])
            # allowed: the controller's tolerance + one 20 ms loop of hand movement
            assert abs(sim.guard_mm - need) <= config.GUARD_TOL + 1.0, (sim.guard_mm, need, sim.hand)
            assert in_cut_zone(yaw, pitch - 2), sim.hand
            checked += 1
        pct = s["coverage"]["pct"]
        if pct > 0.3 and not face_tested:
            c.post("/api/sim/face")
            s2 = wait(c, lambda s: s["live"]["block"] == "zone", 5, "zone block")
            time.sleep(0.05)
            assert not c.get("/api/state").get_json()["machine"]["clipper"]
            face_tested = True
        if pct > 0.5 and not trigger_tested:
            c.post("/api/sim/trigger")            # user lets go
            wait(c, lambda s: not s["machine"]["clipper"], 2, "clipper off after trigger release")
            c.post("/api/sim/trigger")            # and grabs it again
            trigger_tested = True
        time.sleep(0.005)
    s = c.get("/api/state").get_json()
    assert s["state"] == "DONE", (s["state"], s["message"], s["coverage"]["pct"])
    assert s["coverage"]["pct"] >= config.COVER_DONE
    assert checked > 50 and face_tested and trigger_tested
    assert s["live"]["cut_distance"] > 1000, s["live"]       # the roller measured real distance
    time.sleep(0.2)
    assert not ctl.link.get_status()["clipper"]


def test_stop_and_reset():
    app, c = setup()
    c.post("/api/calibrate/default")
    c.post("/api/start", json={"lengths": STYLES["buzz"]["lengths"]})
    wait(c, lambda s: s["machine"]["clipper"], 20, "clipper on")
    c.post("/api/stop")
    s = wait(c, lambda s: s["state"] == "STOPPED" and not s["machine"]["clipper"], 3, "stopped")
    r = c.post("/api/reset")
    assert r.status_code == 200 and r.get_json()["status"]["state"] == "READY"


def test_fade_2_to_5_cm_style():
    st = STYLES["fade25"]
    assert guard_length(0, 0, st["lengths"], st["fade_to"]) == 50                    # crown: 5 cm
    assert abs(guard_length(180, 104, st["lengths"], st["fade_to"]) - 20) < 0.5     # bottom of the back: 2 cm
    assert abs(guard_length(90, 74, st["lengths"], st["fade_to"]) - 20) < 2.0       # just above the ear: ~2 cm


def test_start_refused_before_calibration():
    app, c = setup()
    r = c.post("/api/start", json={"lengths": STYLES["buzz"]["lengths"]})
    assert r.status_code == 400


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
