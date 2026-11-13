"""The brain of the handheld HairBarbot: state machine, calibration, guard targeting, clipper permit,
coverage tracking, and safety checks. Runs a 50 Hz loop.

States
  NOT_HOMED -> HOMING -> IDLE (guard homed, sensors not calibrated)
  IDLE/READY -> CALIBRATING -> READY
  READY/DONE -> CUTTING -> DONE
  any -> STOPPED (app STOP, E-stop, board fault, lost connection) -> reset -> READY / IDLE

Every loop while CUTTING:
  1. read both orientation sensors -> where on the head the clipper is (yaw, pitch)
  2. look up the hair length the chosen style wants there -> send that guard length to the board
  3. allow the clipper ONLY if: trigger held, sensors OK, not near the face/ears, and the guard
     is already at the right length for this spot ("wrong spot -> clipper off immediately")
  4. mark the area under the clipper as cut -> coverage map for the app
"""
import collections
import math
import threading
import time
import traceback

import numpy as np

import config
from orientation import calibrate, direction, in_cut_zone, locate, max_pitch, measured_vector
from styles import STYLES, guard_length, region_name, validate_lengths

# coverage grid: same layout as styles.preview_grid (pitch rows 0..110 step 5, yaw cols -180..180 step 10)
GRID_YAW = list(range(-180, 181, 10))
GRID_PITCH = list(range(0, 111, 5))

HINTS = {
    "trigger": "Hold the trigger to cut.",
    "zone": "Too close to the face or ears. Trim there by hand.",
    "guard": "Slow down: the guard is adjusting.",
    "sensors": "Can't tell where the clipper is. Check the sensors.",
    "estop": "E-stop is pressed.",
}


class ControllerError(Exception):
    pass


class Controller:
    def __init__(self, link, sim=False):
        self.link = link
        self.sim = sim
        self.state = "NOT_HOMED"
        self.message = "Press Home to get the guard ready."
        self.busy = False
        self.M = None                       # calibration rotation (head sensor -> head)
        self.calib_err = None
        self.calib_pairs = {}               # pose index -> (v, n)
        self.recent_v = collections.deque(maxlen=15)
        self.lengths = None
        self.fade_to = None
        self.style_key = None
        self.loc = None                     # (yaw, pitch) or None
        self.target = config.GUARD_MAX
        self.block = None                   # why the clipper is not allowed right now
        self.contact = False
        self.started_at = None
        self.finished_at = None
        self.events = collections.deque(maxlen=60)
        self._clip_bad_since = None
        self._last_zone_log = 0.0
        # coverage
        self._cells = [(p, y) for p in GRID_PITCH for y in GRID_YAW]
        self._cell_dir = np.array([direction(y, p) for p, y in self._cells])
        self._cuttable = np.array([p <= max_pitch(y) for p, y in self._cells])
        self._dwell = np.zeros(len(self._cells))
        threading.Thread(target=self._loop, daemon=True).start()

    # ------------------------------------------------------------ helpers
    def _log(self, text, kind="info"):
        self.events.append({"t": time.time(), "text": text, "kind": kind})

    def _require(self, *states):
        if self.state not in states:
            raise ControllerError(f"Not allowed while {self.state.replace('_', ' ').lower()}.")

    def _bg(self, fn):
        if self.busy:
            raise ControllerError("Busy, try again in a moment.")
        self.busy = True

        def run():
            try:
                fn()
            except Exception as e:
                traceback.print_exc()
                self.stop(f"Software error: {e}")
            finally:
                self.busy = False
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------ homing
    def home(self):
        self._require("NOT_HOMED", "IDLE", "READY", "DONE")

        def run():
            self.state, self.message = "HOMING", "Homing the guard..."
            self.link.home()
            ok = self.link.wait_done(40)
            t_end = time.time() + 1.0          # DONE arrives before the next status line says "homed"
            while ok and not self.link.get_status()["homed"] and time.time() < t_end:
                time.sleep(0.02)
            if not ok or not self.link.get_status()["homed"]:
                self.stop(f"Homing failed: {self.link.last_fault or self.link.last_error or 'timeout'}")
                return
            self._log("Guard homed")
            if self.M is not None:
                self.state, self.message = "READY", "Ready. Choose a haircut."
            else:
                self.state, self.message = "IDLE", "Put on the headband, then calibrate."
        self._bg(run)

    # ------------------------------------------------------------ calibration
    def calib_start(self):
        self._require("IDLE", "READY", "DONE")
        self.calib_pairs = {}
        self.state = "CALIBRATING"
        self.message = "Hold the clipper at each spot, pointing straight at the head, and press Record."
        self._log("Calibration started")

    def calib_record(self, i):
        self._require("CALIBRATING")
        if not 0 <= i < len(config.CALIB_POSES):
            raise ControllerError("Unknown calibration spot.")
        name, yaw, pitch = config.CALIB_POSES[i]
        if self.sim:
            self.link.sim_place(yaw, pitch)
            time.sleep(0.4)                         # let a few readings arrive at the new spot
        st = self.link.get_status()
        if not (st["clip_imu"] and st["head_imu"]):
            raise ControllerError("Both orientation sensors must be working to calibrate.")
        if len(self.recent_v) < 5:
            raise ControllerError("No sensor readings yet. Wait a second and try again.")
        v = np.mean(list(self.recent_v)[-10:], axis=0)
        v /= np.linalg.norm(v)
        self.calib_pairs[i] = (v, direction(yaw, pitch))
        self.message = f"Recorded: {name}. {len(self.calib_pairs)} of {len(config.CALIB_POSES)} spots."

    def calib_finish(self):
        self._require("CALIBRATING")
        try:
            M, err = calibrate(list(self.calib_pairs.values()))
        except ValueError as e:
            raise ControllerError(str(e))
        if err > config.CALIB_MAX_ERROR_DEG:
            raise ControllerError(f"Spots disagree by {err:.0f} degrees. Re-record them, holding the clipper "
                                  "straight at the head and keeping the head still.")
        self.M, self.calib_err = M, err
        self.state = "READY"
        self.message = f"Calibrated (accuracy about {err:.0f}°). Choose a haircut."
        self._log(f"Calibrated, worst spot off by {err:.1f}°", "ok")

    def calib_default(self):
        """Simulation only: use the simulator's true mounting instead of touching spots."""
        if not self.sim:
            raise ControllerError("Only available in simulation.")
        self._require("IDLE", "READY", "DONE", "CALIBRATING")
        self.M, self.calib_err = self.link.M_true.copy(), 0.0
        self.state, self.message = "READY", "Calibrated (simulation). Choose a haircut."
        self._log("Simulated calibration loaded")

    # ------------------------------------------------------------ session
    def start(self, lengths, fade_to=None, style=None):
        self._require("READY", "DONE")
        self.lengths = validate_lengths(lengths)
        self.fade_to = None if fade_to in (None, "", False) else float(fade_to)
        self.style_key = style if style in STYLES else None
        self._dwell[:] = 0.0
        self.started_at, self.finished_at = time.time(), None
        self.link.vacuum(True)
        self.state = "CUTTING"
        self.message = HINTS["trigger"]
        name = STYLES[self.style_key]["name"] if self.style_key else "Custom"
        self._log(f"Haircut started: {name}", "ok")
        if self.sim:
            self.link.sim_auto(True)

    def finish(self, reason="Haircut finished"):
        self._require("CUTTING")
        self.state = "DONE"
        self.finished_at = time.time()
        self.link.permit(False)
        self.link.vacuum(False)
        self.message = "All done!"
        self._log(reason, "ok")
        if self.sim:
            self.link.sim_auto(False)

    def stop(self, reason="Stopped from the app"):
        self.link.stop()
        if self.sim:
            self.link.sim_auto(False)
        if self.state != "STOPPED":
            self._before_stop = self.state
            self.state = "STOPPED"
            self.message = reason
            self._log(f"STOP: {reason}", "error")

    def reset(self):
        self._require("STOPPED")
        self.link.reset()
        time.sleep(0.2)
        st = self.link.get_status()
        if st["state"] == 4:
            raise ControllerError("Still in fault. Is the E-stop released?")
        if not st["homed"]:
            self.state, self.message = "NOT_HOMED", "Press Home."
        elif self.M is None:
            self.state, self.message = "IDLE", "Calibrate the sensors."
        else:
            self.state, self.message = "READY", "Reset. Start the haircut again when ready."
        self._log("Reset after stop")

    # ------------------------------------------------------------ 50 Hz loop
    def _loop(self):
        period = 1.0 / config.LOOP_HZ
        last = time.time()
        while True:
            time.sleep(period)
            now = time.time()
            dt = now - last
            last = now
            try:
                self._tick(now, dt)
            except Exception:
                traceback.print_exc()

    def _tick(self, now, dt):
        st = self.link.get_status()
        imus = st["clip_imu"] and st["head_imu"]
        if imus:
            self.recent_v.append(measured_vector(st["qc"], st["qh"]))
        self.loc = locate(st["qc"], st["qh"], self.M) if (imus and self.M is not None) else None
        self.contact = st["tof_ok"] and 0 < st["tof"] < st["guard"] + config.TOF_OFFSET + config.CONTACT_MARGIN

        cutting = self.state == "CUTTING"
        if cutting and self.loc:
            self.target = guard_length(self.loc[0], self.loc[1], self.lengths, self.fade_to)
        else:
            self.target = config.GUARD_MAX         # idle: longest guard = safest
        if st["homed"] and self.state != "STOPPED":
            self.link.guard(self.target)

        # ---- may the clipper run?
        self.block = None
        if cutting:
            if not st["estop_ok"]:
                self.block = "estop"
            elif not self.loc:
                self.block = "sensors"
            elif not in_cut_zone(*self.loc):
                self.block = "zone"
            elif abs(st["guard"] - self.target) > config.GUARD_TOL:
                self.block = "guard"
            elif not st["trigger"]:
                self.block = "trigger"
        allowed = cutting and self.block is None
        self.link.permit(allowed)

        # ---- safety: things that STOP the session
        if self.state in ("CUTTING", "CALIBRATING", "HOMING") and st["age"] > config.STATUS_STALE_S:
            self.stop("Lost contact with the HairBarbot board.")
            return
        if self.state in ("CUTTING", "CALIBRATING", "READY") and st["state"] == 4:
            self.stop(f"Board fault: {self.link.last_fault}")
            return
        if st["clipper"] and not allowed and not st["permit"]:
            self._clip_bad_since = self._clip_bad_since or now
            if now - self._clip_bad_since > config.UNEXPECTED_CLIP_S:
                self.stop("Clipper was on without permission.")
                return
        else:
            self._clip_bad_since = None

        # ---- messages + coverage
        if cutting:
            if self.block == "zone" and now - self._last_zone_log > 4:
                self._log("Clipper paused near the face/ears")
                self._last_zone_log = now
            if st["clipper"] and self.loc:
                self.message = f"Cutting the {region_name(*self.loc)} at {st['guard']:.0f} mm."
                if self.contact or not st["tof_ok"]:
                    n = direction(*self.loc)
                    near = self._cell_dir @ n > math.cos(math.radians(config.COVER_RADIUS_DEG))
                    self._dwell[near] += dt
            else:
                self.message = HINTS.get(self.block, "Hold the trigger to cut.")
            if self.coverage_pct() >= config.COVER_DONE:
                self.finish("Whole head covered. Haircut finished!")

    # ------------------------------------------------------------ coverage
    def _done_mask(self):
        return self._dwell >= config.COVER_DWELL_S

    def coverage_pct(self):
        return float(np.sum(self._done_mask() & self._cuttable) / np.sum(self._cuttable))

    def coverage(self):
        done = self._done_mask()
        rows = []
        k = 0
        for p in GRID_PITCH:
            row = []
            for y in GRID_YAW:
                row.append((1 if done[k] else 0) if self._cuttable[k] else None)
                k += 1
            rows.append(row)
        regions = {}
        for (p, y), d, c in zip(self._cells, done, self._cuttable):
            if not c:
                continue
            r = region_name(y, p)
            a, b = regions.get(r, (0, 0))
            regions[r] = (a + int(d), b + 1)
        reg = {r: round(a / b, 3) for r, (a, b) in regions.items()}
        todo = [r for r, v in sorted(reg.items(), key=lambda kv: kv[1]) if v < 0.9]
        return {"pct": round(self.coverage_pct(), 3), "rows": rows, "yaw_step": 10, "pitch_step": 5,
                "regions": reg, "todo": todo}

    # ------------------------------------------------------------ status for the apps
    def status(self):
        st = self.link.get_status()
        loc = self.loc
        live = {"need_guard": round(self.target, 1) if self.state == "CUTTING" and loc else None,
                "guard_err": round(st["guard"] - self.target, 2), "block": self.block,
                "hint": HINTS.get(self.block), "contact": self.contact, "elapsed": None}
        if self.started_at:
            live["elapsed"] = round((self.finished_at or time.time()) - self.started_at, 1)
        return {
            "state": self.state,
            "message": self.message,
            "busy": self.busy,
            "sim": self.sim,
            "machine": {k: v for k, v in st.items()},
            "fault": self.link.last_fault,
            "location": ({"yaw": round(loc[0], 1), "pitch": round(loc[1], 1), "region": region_name(*loc),
                          "in_zone": in_cut_zone(*loc)} if loc else None),
            "live": live,
            "coverage": self.coverage(),
            "calibration": {"poses": [p[0] for p in config.CALIB_POSES], "recorded": sorted(self.calib_pairs),
                            "calibrated": self.M is not None,
                            "error_deg": None if self.calib_err is None else round(self.calib_err, 1)},
            "lengths": self.lengths,
            "fade_to": self.fade_to,
            "style": self.style_key,
            "events": list(self.events)[-25:],
            "server_time": time.time(),
        }
