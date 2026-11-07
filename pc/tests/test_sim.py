"""End-to-end test in simulation:  python -m pytest tests  (or: python tests/test_sim.py)"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from app import create_app
from kinematics import HeadModel, max_pitch, rad_for
from planner import plan_haircut, estimate_minutes
from styles import STYLES, guard_length


def wait_state(c, states, timeout=60):
    t = time.time() + timeout
    while time.time() < t:
        s = c.get("/api/state").get_json()
        if s["state"] in states:
            return s
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for {states}, at {s['state']}: {s['message']}")


def test_plans_reachable_for_all_styles_and_head_sizes():
    for a, b, c in [(90, 70, 100), (100, 78, 112), (112, 88, 125)]:
        head = HeadModel(a, b, c)
        for k, st in STYLES.items():
            strokes = plan_haircut(st["lengths"], st["fade_to"], head)
            assert len(strokes) == 23
            for s in strokes:
                for wp in s:
                    assert wp.pitch <= max_pitch(wp.yaw) - config.ZONE_MARGIN + 1e-6


def test_head_fit_recovers_model():
    true = HeadModel(104, 80, 115)
    pts = [(y, p, true.radius(y, p)) for y, p in [(0, 0), (90, 60), (-90, 60), (170, 75), (0, 35)]]
    fit = HeadModel.fit(pts)
    assert abs(fit.a - 104) < 1 and abs(fit.b - 80) < 1 and abs(fit.c - 115) < 1


def test_full_haircut_and_safety_stops():
    app = create_app(sim=True, speedup=60)
    ctl = app.config["ctl"]
    c = app.test_client()
    assert c.post("/api/home").status_code == 200
    wait_state(c, {"IDLE"})
    # calibration with sim: go to points, jog to touch the default head, record
    head = HeadModel()
    c.post("/api/calibrate/start")
    for i, (name, y, p) in enumerate([("Crown", 0, 0), ("L", 90, 60), ("R", -90, 60), ("Back", 170, 75)]):
        assert c.post(f"/api/calibrate/goto/{i}").status_code == 200
        while ctl.busy: time.sleep(0.02)
        target = rad_for(head.radius(y, p), 10.0)
        while abs(ctl.link.get_status()["rad"] - target) > 0.6:
            step = max(-5, min(5, round(target - ctl.link.get_status()["rad"])))
            c.post("/api/jog", json={"mm": step if step else (1 if target > ctl.link.get_status()["rad"] else -1)})
            while ctl.busy: time.sleep(0.02)
        assert c.post("/api/calibrate/record").status_code == 200
    r = c.post("/api/calibrate/finish")
    assert r.status_code == 200, r.get_json()
    s = wait_state(c, {"READY"})
    assert abs(s["calibration"]["head"]["a"] - 100) < 3

    # full haircut
    st = STYLES["fade"]
    r = c.post("/api/cut", json={"lengths": st["lengths"], "fade_to": st["fade_to"]})
    assert r.status_code == 200, r.get_json()
    # stop mid-way with a simulated head movement
    time.sleep(1.0)
    c.post("/api/sim/head_move")
    s = wait_state(c, {"STOPPED"}, 10)
    assert "Head" in s["message"], s["message"]
    assert not ctl.link.get_status()["clipper"]
    time.sleep(1.6)
    while ctl.busy: time.sleep(0.02)
    assert c.post("/api/reset").status_code == 200
    # continue from where it stopped
    r = c.post("/api/cut", json={"lengths": st["lengths"], "fade_to": st["fade_to"], "resume": True})
    assert r.status_code == 200, r.get_json()
    s = wait_state(c, {"DONE", "STOPPED"}, 300)
    assert s["state"] == "DONE", s["message"]
    assert s["progress"]["done"] == s["progress"]["total"] == 23
    m = ctl.link.get_status()
    assert not m["clipper"] and not m["vacuum"] and m["rad"] == 0.0


def test_wrong_spot_detection():
    app = create_app(sim=True, speedup=60)
    ctl = app.config["ctl"]
    c = app.test_client()
    c.post("/api/home"); wait_state(c, {"IDLE"})
    c.post("/api/calibrate/default")
    st = STYLES["classic"]
    c.post("/api/cut", json={"lengths": st["lengths"], "fade_to": None})
    # wait until actually cutting, then sabotage: force the guard to a wrong length
    t = time.time() + 30
    while not ctl.link.get_status()["clipper"] and time.time() < t: time.sleep(0.005)
    ctl.link.start["guard"] = ctl.link.target["guard"] = ctl.link.pos["guard"] = 35.0  # simulate a slipped guard
    s = wait_state(c, {"STOPPED"}, 5)
    assert "WRONG SPOT" in s["message"], s["message"]
    time.sleep(0.2)
    assert not ctl.link.get_status()["clipper"]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("PASS", name)
