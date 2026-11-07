"""The brain: state machine, calibration, running a haircut, and the safety watchdog.

States
  NOT_HOMED   -> HOMING -> IDLE (homed, head not calibrated)
  IDLE        -> CALIBRATING -> READY
  READY/DONE  -> CUTTING <-> PAUSED -> DONE
  any         -> STOPPED (E-stop, app STOP, or a safety check failed) -> reset -> READY/IDLE

Safety watchdog (runs 50x per second while cutting) stops the machine if:
  - the camera says the head moved/turned or the face is not visible
  - the firmware reports a fault, or its status stops arriving
  - the clipper is on where the plan doesn't expect it
  - the clipper is on outside the allowed zone (face / ears)
  - "WRONG SPOT": the guard length doesn't match the haircut at the spot the cutter is on
  - the comb is pressing deeper into the head than the head model allows
"""
import threading
import time
import traceback

import config
from kinematics import HeadModel, max_pitch, comb_tip_radius
from planner import plan_haircut, estimate_minutes, PlanError
from styles import guard_length, validate_lengths

CALIB_POSES = [
    ("Crown (top)", 0.0, 0.0),
    ("Left side", 90.0, 60.0),
    ("Right side", -90.0, 60.0),
    ("Back", 170.0, 75.0),
    ("Front top", 0.0, 35.0),
]
CALIB_GUARD = 10.0


class ControllerError(Exception):
    pass


class Abort(Exception):
    pass


class Controller:
    def __init__(self, link, tracker, sim=False):
        self.link = link
        self.tracker = tracker
        self.sim = sim
        self.state = "NOT_HOMED"
        self.message = "Press Home to start."
        self.head = HeadModel()
        self.calibrated = False
        self.calib_points = []          # (name, yaw, pitch, r)
        self.calib_idx = None
        self.lengths = None
        self.fade_to = None
        self.strokes = []
        self.next_stroke = 0
        self.est_minutes = 0.0
        self.clip_expected = False
        self._clip_off_t = 0.0
        self.busy = False
        self._abort = threading.Event()
        self._pause = threading.Event()
        self._worker = None
        self.tracker.start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    # ------------------------------------------------------------ helpers
    def _bg(self, fn, *args):
        if self.busy:
            raise ControllerError("Machine is busy, wait a moment.")
        self.busy = True

        def run():
            try:
                fn(*args)
            except Abort:
                pass
            except Exception as e:  # never leave the clipper on after an error
                traceback.print_exc()
                self.stop(f"Software error: {e}")
            finally:
                self.busy = False
        self._worker = threading.Thread(target=run, daemon=True)
        self._worker.start()

    def _move(self, yaw, pitch, rad, guard, feed, timeout=60):
        if self._abort.is_set():
            raise Abort()
        self.link.move(yaw, pitch, rad, guard, feed)
        if not self.link.wait_done(timeout, self._abort):
            if self._abort.is_set():
                raise Abort()
            raise ControllerError(f"Move failed: {self.link.last_error or self.link.last_fault or 'timeout'}")

    def _require(self, *states):
        if self.state not in states:
            raise ControllerError(f"Not allowed while {self.state}.")

    # ------------------------------------------------------------ homing
    def home(self):
        self._require("NOT_HOMED", "IDLE", "READY", "DONE")

        def run():
            self.state, self.message = "HOMING", "Homing all axes..."
            self.link.home()
            if not self.link.wait_done(120, self._abort) or not self.link.get_status()["homed"]:
                self.stop(f"Homing failed: {self.link.last_fault or self.link.last_error or 'timeout'}")
                return
            self.state = "READY" if self.calibrated else "IDLE"
            self.message = "Homed. Seat the client and calibrate." if not self.calibrated else "Ready."
        self._bg(run)

    # ------------------------------------------------------------ calibration
    def calib_start(self):
        self._require("IDLE", "READY", "DONE")
        self.calib_points = []
        self.calib_idx = None
        self.calibrated = False
        self.state = "CALIBRATING"
        self.message = "Go to each point, jog the comb until it just touches the hair, then Record."

    def calib_goto(self, i):
        self._require("CALIBRATING")
        if not 0 <= i < len(CALIB_POSES):
            raise ControllerError("bad point")
        name, yaw, pitch = CALIB_POSES[i]

        def run():
            st = self.link.get_status()
            self._move(st["yaw"], st["pitch"], 0.0, CALIB_GUARD, config.FEED_TRAVEL)   # pull back first
            self._move(yaw, pitch, 0.0, CALIB_GUARD, config.FEED_TRAVEL)
            self.calib_idx = i
            self.message = f"At '{name}'. Jog in until the comb touches, then Record."
        self._bg(run)

    def jog(self, mm):
        self._require("CALIBRATING")
        if self.calib_idx is None:
            raise ControllerError("Go to a calibration point first.")
        st = self.link.get_status()
        target = max(config.RAD_MIN, min(config.RAD_MAX, st["rad"] + float(mm)))
        self._bg(self._move, st["yaw"], st["pitch"], target, st["guard"], 10)

    def calib_record(self):
        self._require("CALIBRATING")
        if self.calib_idx is None:
            raise ControllerError("Go to a calibration point first.")
        st = self.link.get_status()
        r = comb_tip_radius(st["rad"], st["guard"])
        name = CALIB_POSES[self.calib_idx][0]
        self.calib_points = [p for p in self.calib_points if p[0] != name]
        self.calib_points.append((name, st["yaw"], st["pitch"], r))
        self.message = f"Recorded {name}: {r:.0f} mm from head center."

    def calib_finish(self):
        self._require("CALIBRATING")
        if len(self.calib_points) < 4:
            raise ControllerError("Record at least 4 points.")
        try:
            self.head = HeadModel.fit([(y, p, r) for _, y, p, r in self.calib_points])
        except ValueError as e:
            raise ControllerError(str(e))
        if not self.tracker.set_reference():
            raise ControllerError("Camera can't see the face. Fix the camera, then press Finish again.")

        def run():
            st = self.link.get_status()
            self._move(st["yaw"], st["pitch"], 0.0, st["guard"], config.FEED_TRAVEL)
            self.calibrated = True
            self.state = "READY"
            self.message = (f"Calibrated. Head size {2*self.head.a:.0f} x {2*self.head.b:.0f} mm. "
                            "Choose a haircut and press Start.")
        self._bg(run)

    def calib_default(self):
        """Skip touch-off and use the default head model. For simulation / mannequin testing."""
        self._require("IDLE", "READY", "DONE", "CALIBRATING")
        self.head = HeadModel()
        self.tracker.set_reference()
        self.calibrated = True
        self.state = "READY"
        self.message = "Using default head model (testing only)."

    # ------------------------------------------------------------ preview / planning
    def make_plan(self, lengths, fade_to):
        lengths = validate_lengths(lengths)
        fade_to = None if fade_to in (None, "", False) else float(fade_to)
        try:
            strokes = plan_haircut(lengths, fade_to, self.head)
        except PlanError as e:
            raise ControllerError(str(e))
        return lengths, fade_to, strokes

    # ------------------------------------------------------------ cutting
    def start_cut(self, lengths, fade_to=None, resume=False):
        self._require("READY", "DONE")
        if not self.tracker.snapshot()["ok"]:
            raise ControllerError("Camera check failed: " + self.tracker.snapshot()["reason"])
        if resume and self.strokes and 0 < self.next_stroke < len(self.strokes):
            start = self.next_stroke
        else:
            self.lengths, self.fade_to, self.strokes = self.make_plan(lengths, fade_to)
            self.est_minutes = estimate_minutes(self.strokes)
            start = 0
        self._abort.clear()
        self._pause.clear()
        self.state = "CUTTING"
        self.message = "Cutting. Keep still."
        self._bg(self._run_cut, start)

    def _wait_if_paused(self, wp):
        if not self._pause.is_set():
            return
        self._clip(False)
        st = self.link.get_status()
        self._move(st["yaw"], st["pitch"], 0.0, st["guard"], config.FEED_PLUNGE)
        self.state, self.message = "PAUSED", "Paused. Press Resume to continue."
        while self._pause.is_set():
            if self._abort.is_set():
                raise Abort()
            time.sleep(0.05)
        self.state, self.message = "CUTTING", "Cutting. Keep still."
        self._move(wp.yaw, wp.pitch, max(0.0, wp.rad - config.APPROACH_GAP), wp.guard, config.FEED_PLUNGE)
        self._move(wp.yaw, wp.pitch, wp.rad, wp.guard, config.FEED_PLUNGE)
        self._clip(True)

    def _clip(self, on):
        if on:
            self.clip_expected = True
            if not self.link.clipper(True):
                self.clip_expected = False
                raise ControllerError(f"Clipper refused: {self.link.last_error}")
        else:
            self.link.clipper(False)
            self.clip_expected = False
            self._clip_off_t = time.time()

    def _run_cut(self, start):
        self.link.vacuum(True)
        for k in range(start, len(self.strokes)):
            self.next_stroke = k
            stroke = self.strokes[k]
            first = stroke[0]
            st = self.link.get_status()
            # travel: retract, rotate to the stroke, set guard, then plunge onto the head
            self._move(st["yaw"], st["pitch"], 0.0, st["guard"], config.FEED_TRAVEL)
            self._move(first.yaw, first.pitch, 0.0, first.guard, config.FEED_TRAVEL)
            self._move(first.yaw, first.pitch, max(0.0, first.rad - config.APPROACH_GAP), first.guard, config.FEED_TRAVEL)
            self._move(first.yaw, first.pitch, first.rad, first.guard, config.FEED_PLUNGE)
            self._clip(True)
            for wp in stroke[1:]:
                self._wait_if_paused(wp)
                self._move(wp.yaw, wp.pitch, wp.rad, wp.guard, config.FEED_CUT)
            self._clip(False)
            last = stroke[-1]
            self._move(last.yaw, last.pitch, max(0.0, last.rad - config.APPROACH_GAP), last.guard, config.FEED_TRAVEL)
        self.next_stroke = len(self.strokes)
        st = self.link.get_status()
        self._move(st["yaw"], st["pitch"], 0.0, st["guard"], config.FEED_TRAVEL)
        self._move(0.0, 0.0, 0.0, config.GUARD_MAX, config.FEED_TRAVEL)
        self.link.vacuum(False)
        self.state, self.message = "DONE", "Haircut finished!"

    def pause(self):
        self._require("CUTTING")
        self._pause.set()
        self.message = "Pausing after this step..."

    def resume(self):
        self._require("PAUSED")
        self._pause.clear()

    def stop(self, reason="Stopped by user"):
        self._abort.set()
        self.clip_expected = False
        try:
            self.link.stop()
        finally:
            if self.state != "STOPPED":
                self.state = "STOPPED"
                self.message = reason

    def reset(self):
        self._require("STOPPED")
        if self.busy:
            raise ControllerError("Still stopping, try again in a second.")
        self.link.reset()
        time.sleep(0.2)
        st = self.link.get_status()
        if st["state"] == 4:
            raise ControllerError("Machine still in fault (is the E-stop released?).")
        self._abort.clear()
        self._pause.clear()
        if not st["homed"]:
            self.state, self.message = "NOT_HOMED", "Press Home."
        elif self.calibrated:
            self.state, self.message = "READY", "Reset. Press Continue to resume, or Start to begin again."
        else:
            self.state, self.message = "IDLE", "Reset. Calibrate the head."

    # ------------------------------------------------------------ watchdog
    def _watchdog(self):
        period = 1.0 / config.WATCHDOG_HZ
        while True:
            time.sleep(period)
            if self.state not in ("CUTTING",):
                # still catch firmware faults in any active state
                if self.state in ("HOMING", "CALIBRATING", "PAUSED") and self.link.get_status()["state"] == 4:
                    self.stop(f"Machine fault: {self.link.last_fault}")
                continue
            reason = self._check()
            if reason:
                self.stop(reason)

    def _check(self):
        snap = self.tracker.snapshot()
        if not snap["ok"]:
            return "Head check failed: " + snap["reason"]
        st = self.link.get_status()
        if st["age"] > 0.5:
            return "Lost contact with the machine"
        if st["state"] == 4:
            return f"Machine fault: {self.link.last_fault}"
        if not st["estop_ok"]:
            return "E-stop pressed"
        if st["clipper"]:
            if not self.clip_expected:
                # status lines are up to 100 ms old; allow time for "clipper off" to show up
                if time.time() - self._clip_off_t > 0.5:
                    return "Clipper on unexpectedly"
                return None
            y, p = st["yaw"], st["pitch"]
            if p > max_pitch(y) + 2.0:
                return f"Outside cutting zone (yaw {y:.0f}, pitch {p:.0f})"
            need = guard_length(y, p, self.lengths, self.fade_to)
            if abs(st["guard"] - need) > config.GUARD_TOL:
                return f"WRONG SPOT: guard {st['guard']:.1f} mm but this spot needs {need:.1f} mm"
            tip = comb_tip_radius(st["rad"], st["guard"])
            if tip < self.head.radius(y, p) - config.DEPTH_TOL:
                return "Comb pressing too deep"
        return None

    # ------------------------------------------------------------ status for the app
    def status(self):
        st = self.link.get_status()
        return {
            "state": self.state,
            "message": self.message,
            "busy": self.busy,
            "sim": self.sim,
            "machine": st,
            "fault": self.link.last_fault,
            "tracker": self.tracker.snapshot(),
            "progress": {"done": min(self.next_stroke, len(self.strokes)), "total": len(self.strokes)},
            "est_minutes": self.est_minutes,
            "calibration": {
                "poses": [p[0] for p in CALIB_POSES],
                "current": self.calib_idx,
                "recorded": [p[0] for p in self.calib_points],
                "calibrated": self.calibrated,
                "head": {"a": round(self.head.a, 1), "b": round(self.head.b, 1), "c": round(self.head.c, 1)},
            },
            "lengths": self.lengths,
            "fade_to": self.fade_to,
        }
