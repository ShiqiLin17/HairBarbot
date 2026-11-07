"""HairBarbot server: runs the controller and serves the client app.

  python app.py --sim          # no hardware: fake machine + fake camera (start here!)
  python app.py                # real machine on config.SERIAL_PORT + webcam
  python app.py --port COM3    # override the serial port

Then open http://localhost:5000 (or http://<laptop-ip>:5000 on a phone/tablet on the same Wi-Fi).
"""
import argparse
import logging
import os

from flask import Flask, jsonify, request, send_from_directory, Response

import config
from controller import Controller, ControllerError
from styles import STYLES, preview_grid, validate_lengths

HERE = os.path.dirname(os.path.abspath(__file__))


def create_app(sim=True, port=None, speedup=1.0):
    if sim:
        from serial_link import SimLink
        from head_tracker import SimTracker
        link, tracker = SimLink(speedup=speedup), SimTracker()
    else:
        from serial_link import SerialLink
        from head_tracker import CameraTracker
        link, tracker = SerialLink(port or config.SERIAL_PORT), CameraTracker()
    ctl = Controller(link, tracker, sim=sim)
    app = Flask(__name__, static_folder=None)
    app.config["ctl"] = ctl

    def ok(**kw):
        return jsonify({"ok": True, **kw, "status": ctl.status()})

    @app.errorhandler(ControllerError)
    def ctl_error(e):
        return jsonify({"ok": False, "error": str(e), "status": ctl.status()}), 400

    @app.errorhandler(ValueError)
    def val_error(e):
        return jsonify({"ok": False, "error": str(e), "status": ctl.status()}), 400

    @app.get("/")
    def index():
        return send_from_directory(os.path.join(HERE, "web"), "index.html")

    @app.get("/api/state")
    def state():
        return jsonify(ctl.status())

    @app.get("/api/styles")
    def styles():
        return jsonify({"styles": STYLES, "guard_min": config.GUARD_MIN, "guard_max": config.GUARD_MAX})

    @app.post("/api/preview")
    def preview():
        body = request.get_json(force=True)
        lengths = validate_lengths(body["lengths"])
        fade = body.get("fade_to")
        fade = None if fade in (None, "", False) else float(fade)
        return jsonify(preview_grid(lengths, fade))

    @app.get("/api/plan")
    def plan():
        return jsonify(ctl.plan_dict())

    @app.post("/api/home")
    def home():
        ctl.home()
        return ok()

    @app.post("/api/calibrate/start")
    def cal_start():
        ctl.calib_start()
        return ok()

    @app.post("/api/calibrate/goto/<int:i>")
    def cal_goto(i):
        ctl.calib_goto(i)
        return ok()

    @app.post("/api/jog")
    def jog():
        ctl.jog(float(request.get_json(force=True)["mm"]))
        return ok()

    @app.post("/api/calibrate/record")
    def cal_record():
        ctl.calib_record()
        return ok()

    @app.post("/api/calibrate/finish")
    def cal_finish():
        ctl.calib_finish()
        return ok()

    @app.post("/api/calibrate/default")
    def cal_default():
        ctl.calib_default()
        return ok()

    @app.post("/api/cut")
    def cut():
        body = request.get_json(force=True)
        ctl.start_cut(body.get("lengths"), body.get("fade_to"), resume=bool(body.get("resume")), style=body.get("style"))
        return ok()

    @app.post("/api/pause")
    def pause():
        ctl.pause()
        return ok()

    @app.post("/api/resume")
    def resume():
        ctl.resume()
        return ok()

    @app.post("/api/stop")
    def stop():
        ctl.stop("Stopped from the app")
        return ok()

    @app.post("/api/reset")
    def reset():
        ctl.reset()
        return ok()

    @app.post("/api/sim/head_move")
    def sim_head_move():
        if not ctl.sim:
            raise ControllerError("only in --sim")
        ctl.tracker.simulate_move()
        return ok()

    @app.get("/api/camera.jpg")
    def camera():
        jpg = ctl.tracker.jpeg()
        if jpg is None:
            return Response(status=404)
        return Response(jpg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="run without hardware")
    ap.add_argument("--port", help="serial port, e.g. COM3 or /dev/ttyACM0")
    ap.add_argument("--speedup", type=float, default=1.0, help="sim only: run the fake machine faster")
    ap.add_argument("--http", type=int, default=5000)
    a = ap.parse_args()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # no log line for every 10 Hz status poll
    app = create_app(sim=a.sim, port=a.port, speedup=a.speedup)
    print(f"HairBarbot app: http://localhost:{a.http}   ({'SIMULATION' if a.sim else 'REAL MACHINE'})")
    app.run(host="0.0.0.0", port=a.http, threaded=True)
