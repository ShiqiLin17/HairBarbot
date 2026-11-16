"""HairBarbot handheld controller + API. The live app (pc/live, Node.js) is the user interface.

  python app.py --sim          # no hardware: fake board + fake user + simulated camera (`npm run demo` does this)
  python app.py --port COM3    # real board (Windows), or --port /dev/cu.usbserial-XXXX (Mac)

Head shape (--head): female | male | "57 cm" (your circumference) | vision/profiles/<name>.json (3D scan).
Default: average adult head. Camera head tracking: --camera 0 (webcam index). In --sim it's simulated.
"""
import argparse
import logging
import os
import sys

from flask import Flask, jsonify, request

import config
from controller import Controller, ControllerError
from styles import STYLES, preview_grid, validate_lengths

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision"))
from head_profile import (average_profile, check_circumference, load_profile, parse_length,  # noqa: E402
                          personalized_profile)


def make_profile(spec):
    """'female' | 'male' | '57 cm' | path to a scan .json | None (average adult)."""
    if not spec or spec == "average":
        p = personalized_profile(567.0)
        p.label = "Average adult"
        return p
    if spec in ("female", "male"):
        return average_profile(spec)
    if spec.endswith(".json"):
        return load_profile(spec)
    return personalized_profile(check_circumference(parse_length(spec)))


def create_app(sim=True, port=None, speedup=1.0, head=None, camera=None, sim_camera=True):
    profile = make_profile(head)
    cam = None
    if sim:
        from serial_link import SimLink
        link = SimLink(speedup=speedup, profile=profile)
        if sim_camera:
            from camera_head import SimCameraHead
            cam = SimCameraHead(link)
    else:
        from serial_link import SerialLink
        link = SerialLink(port or config.SERIAL_PORT)
    if camera is not None:
        from camera_head import CameraHead
        cam = CameraHead(camera, profile)
    ctl = Controller(link, sim=sim, profile=profile, camera=cam)
    app = Flask(__name__)
    app.config["ctl"] = ctl

    def ok():
        return jsonify({"ok": True, "status": ctl.status()})

    @app.errorhandler(ControllerError)
    @app.errorhandler(ValueError)
    def handled(e):
        return jsonify({"ok": False, "error": str(e), "status": ctl.status()}), 400

    @app.get("/")
    def index():
        return ("HairBarbot controller is running. Open the live app: cd pc/live && npm start, "
                "then http://localhost:3000"), 200, {"Content-Type": "text/plain"}

    @app.get("/api/state")
    def state():
        return jsonify(ctl.status())

    @app.get("/api/head")
    def head():
        return jsonify(ctl.profile.to_json() if ctl.profile else {})

    @app.get("/api/camera.jpg")
    def camera_jpg():
        jpg = ctl.camera.jpeg() if ctl.camera else None
        if jpg is None:
            return "", 404
        return jpg, 200, {"Content-Type": "image/jpeg", "Cache-Control": "no-store"}

    @app.post("/api/sim/turn_head")
    def sim_turn_head():
        if not ctl.sim:
            raise ControllerError("Only in simulation.")
        deg = float((request.get_json(silent=True) or {}).get("deg", 30))
        ctl.link.sim_turn_head(deg)
        return ok()

    @app.get("/api/styles")
    def styles():
        return jsonify({"styles": STYLES, "guard_min": config.GUARD_MIN, "guard_max": config.GUARD_MAX})

    @app.post("/api/preview")
    def preview():
        body = request.get_json(force=True)
        fade = body.get("fade_to")
        return jsonify(preview_grid(validate_lengths(body["lengths"]), None if fade in (None, "", False) else float(fade)))

    @app.post("/api/home")
    def home():
        ctl.home()
        return ok()

    @app.post("/api/calibrate/start")
    def cal_start():
        ctl.calib_start()
        return ok()

    @app.post("/api/calibrate/record/<int:i>")
    def cal_record(i):
        ctl.calib_record(i)
        return ok()

    @app.post("/api/calibrate/finish")
    def cal_finish():
        ctl.calib_finish()
        return ok()

    @app.post("/api/calibrate/default")
    def cal_default():
        ctl.calib_default()
        return ok()

    @app.post("/api/start")
    def start():
        b = request.get_json(force=True)
        ctl.start(b.get("lengths"), b.get("fade_to"), b.get("style"))
        return ok()

    @app.post("/api/finish")
    def finish():
        ctl.finish("Finished by the user")
        return ok()

    @app.post("/api/stop")
    def stop():
        ctl.stop("Stopped from the app")
        return ok()

    @app.post("/api/reset")
    def reset():
        ctl.reset()
        return ok()

    @app.post("/api/sim/trigger")
    def sim_trigger():
        if not ctl.sim:
            raise ControllerError("Only in simulation.")
        ctl.link.sim_toggle_trigger()
        return ok()

    @app.post("/api/sim/face")
    def sim_face():
        if not ctl.sim:
            raise ControllerError("Only in simulation.")
        ctl.link.sim_wander_to_face()
        return ok()

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="run without hardware")
    ap.add_argument("--port", help="serial port, e.g. COM3 or /dev/cu.usbserial-0001")
    ap.add_argument("--speedup", type=float, default=1.0, help="simulation only: run the fake user faster")
    ap.add_argument("--http", type=int, default=5000)
    ap.add_argument("--head", help='head shape: female, male, "57 cm", or a scan .json (default: average adult)')
    ap.add_argument("--camera", type=int, help="webcam index for camera head tracking, e.g. 0")
    ap.add_argument("--no-sim-camera", action="store_true", help="simulation without the simulated camera")
    a = ap.parse_args()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app = create_app(sim=a.sim, port=a.port, speedup=a.speedup, head=a.head, camera=a.camera,
                     sim_camera=not a.no_sim_camera)
    print(f"HairBarbot controller on http://localhost:{a.http}  ({'SIMULATION' if a.sim else 'REAL BOARD'})")
    app.run(host="127.0.0.1", port=a.http, threaded=True)
