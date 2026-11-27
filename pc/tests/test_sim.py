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


def setup(speedup=40, imu_drift=0.0):
    # IMU drift is in sim minutes, so it's sped up too: off by default, realistic in the full session
    app = create_app(sim=True, speedup=speedup, imu_drift=imu_drift)
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
    # the fake user places the cutter spot by spot (3x faster than a person; takes about a minute)
    app, c = setup(speedup=3, imu_drift=2.0)
    ctl = app.config["ctl"]
    c.post("/api/calibrate/default")
    st = STYLES["fade"]
    r = c.post("/api/start", json={"lengths": st["lengths"], "fade_to": st["fade_to"], "style": "fade"})
    assert r.status_code == 200, r.get_json()
    # while cutting, the clipper must never run on the head with the wrong guard or in a no-cut zone
    checked = 0
    face_tested = trigger_tested = tilt_tested = False
    t_end = time.time() + 300
    while time.time() < t_end:
        s = c.get("/api/state").get_json()
        if s["state"] != "CUTTING":
            break
        # check the TRUE state inside the simulator: where the cutter really is vs the real guard length
        sim = ctl.link
        if sim.clip and sim.seated:
            yaw, pitch = sim.hand
            need = guard_length(yaw, pitch, st["lengths"], st["fade_to"])
            # allowed: the controller's tolerance + location error. The simulated tags are noisy (1.5 mm per
            # picture, ~1 deg), and the steepest part of a fade changes ~1.4 mm per degree.
            assert abs(sim.guard_mm - need) <= config.GUARD_TOL + 1.5, (sim.guard_mm, need, sim.hand)
            assert in_cut_zone(yaw, pitch - 2), sim.hand
            checked += 1
        pct = s["coverage"]["pct"]
        if pct > 0.3 and not face_tested:
            c.post("/api/sim/face")
            wait(c, lambda s: s["live"]["block"] == "zone", 5, "zone block")
            time.sleep(0.05)
            assert not c.get("/api/state").get_json()["machine"]["clipper"]
            face_tested = True
        if pct > 0.5 and not trigger_tested:
            c.post("/api/sim/trigger")            # user lets go
            wait(c, lambda s: not s["machine"]["clipper"], 2, "clipper off after trigger release")
            c.post("/api/sim/trigger")            # and grabs it again
            trigger_tested = True
        if pct > 0.6 and not tilt_tested and sim.seated:
            sim.sim_tilt(15)                      # user rocks the cutter: one pad comes off the head
            wait(c, lambda s: s["live"]["block"] == "contact" and not s["machine"]["clipper"], 2, "tilt -> off")
            sim.sim_tilt(0)
            tilt_tested = True
        time.sleep(0.005)
    s = c.get("/api/state").get_json()
    assert s["state"] == "DONE", (s["state"], s["message"], s["coverage"]["pct"])
    assert s["coverage"]["pct"] >= config.COVER_DONE
    assert checked > 50 and face_tested and trigger_tested and tilt_tested
    assert s["live"]["placements"] > 100, s["live"]
    time.sleep(0.2)
    assert not ctl.link.get_status()["clipper"]


def test_lifted_cutter_never_cuts():
    app, c = setup()
    ctl = app.config["ctl"]
    c.post("/api/calibrate/default")
    c.post("/api/start", json={"lengths": STYLES["buzz"]["lengths"]})
    ctl.link.sim_auto(False)
    ctl.link.trigger = True
    ctl.link.sim_place(0, 30)
    wait(c, lambda s: s["machine"]["clipper"], 20, "clipper on while seated")
    ctl.link.sim_lift()
    s = wait(c, lambda s: s["live"]["block"] == "contact", 2, "lifted -> contact block")
    time.sleep(0.1)
    assert not c.get("/api/state").get_json()["machine"]["clipper"]
    assert s["live"]["seated"] is False


def test_stop_and_reset():
    app, c = setup()
    c.post("/api/calibrate/default")
    c.post("/api/start", json={"lengths": STYLES["buzz"]["lengths"]})
    wait(c, lambda s: s["machine"]["clipper"], 20, "clipper on")
    c.post("/api/stop")
    s = wait(c, lambda s: s["state"] == "STOPPED" and not s["machine"]["clipper"], 3, "stopped")
    r = c.post("/api/reset")
    assert r.status_code == 200 and r.get_json()["status"]["state"] == "READY"


def test_fade_2_to_4_cm_style():
    st = STYLES["fade25"]
    assert guard_length(0, 0, st["lengths"], st["fade_to"]) == 40                    # crown: 4 cm
    assert abs(guard_length(180, 104, st["lengths"], st["fade_to"]) - 20) < 0.5     # bottom of the back: 2 cm
    assert abs(guard_length(90, 74, st["lengths"], st["fade_to"]) - 20) < 2.0       # just above the ear: ~2 cm


def test_status_line_from_the_board():
    # same format the firmware prints (hairbarbot_handheld.ino, sendStatus)
    from serial_link import LinkBase, SerialLink
    link = LinkBase()
    SerialLink._parse(link, "ST 1.0000 0.0000 0.0000 0.0000 1520 87 20.35 20.00 2 " + str(1 | 8 | 16 | 32 | 64))
    st = link.get_status()
    assert st["fsr"] == (1520, 87) and st["guard"] == 20.35 and st["homed"] and st["drive_ok"]
    assert st["imu_ok"] and st["trigger"] and not st["clipper"] and st["state_name"] == "READY"


def test_styles_fit_the_guard():
    for k, st in STYLES.items():
        for v in st["lengths"].values():
            assert config.GUARD_MIN <= v <= config.GUARD_MAX, (k, v)


def test_start_refused_before_calibration():
    app, c = setup()
    r = c.post("/api/start", json={"lengths": STYLES["buzz"]["lengths"]})
    assert r.status_code == 400


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
