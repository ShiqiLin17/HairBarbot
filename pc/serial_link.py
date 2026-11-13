"""Talks to the ESP32 (SerialLink) or pretends to be it (SimLink). Same interface for both."""
import math
import random
import threading
import time

import numpy as np

import config
from orientation import direction, matrix_to_quat, max_pitch

STATE_NAMES = {0: "NOT_HOMED", 1: "HOMING", 2: "READY", 4: "FAULT"}


def _empty_status():
    return {"qc": (1.0, 0.0, 0.0, 0.0), "qh": (1.0, 0.0, 0.0, 0.0), "tof": 0, "guard": config.GUARD_MAX,
            "target": config.GUARD_MAX, "state": 0, "state_name": "NOT_HOMED", "homed": False, "clipper": False,
            "vacuum": False, "estop_ok": True, "tof_ok": False, "clip_imu": False, "head_imu": False,
            "trigger": False, "permit": False, "age": 99.0}


class LinkBase:
    def __init__(self):
        self.lock = threading.Lock()
        self.status = _empty_status()
        self._status_t = 0.0
        self._done = threading.Event()
        self.last_fault = None
        self.last_error = None

    def _set_status(self, **kw):
        with self.lock:
            self.status.update(kw)
            self.status["state_name"] = STATE_NAMES.get(self.status["state"], "?")
            self._status_t = time.time()

    def get_status(self):
        with self.lock:
            s = dict(self.status)
        s["age"] = time.time() - self._status_t
        return s

    def wait_done(self, timeout):
        return self._done.wait(timeout) and self.get_status()["state"] != 4


# ====================================================================== real board
class SerialLink(LinkBase):
    def __init__(self, port=config.SERIAL_PORT, baud=config.BAUD):
        super().__init__()
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=0.05)
        time.sleep(2.0)  # the board resets when the port opens
        self._wlock = threading.Lock()
        self._last_guard = None
        self._last_guard_t = 0.0
        self._last_permit = None
        self._last_permit_t = 0.0
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _write(self, line):
        with self._wlock:
            self.ser.write((line + "\n").encode())

    def _heartbeat(self):
        while True:
            try:
                self._write("P")
            except Exception:
                pass
            time.sleep(0.1)

    def _reader(self):
        buf = b""
        while True:
            try:
                chunk = self.ser.read(512)
            except Exception:
                time.sleep(0.1)
                continue
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._parse(line.decode(errors="ignore").strip())

    def _parse(self, line):
        if line.startswith("ST "):
            p = line.split()
            if len(p) != 14:
                return
            try:
                f = int(p[13])
                self._set_status(qc=tuple(float(x) for x in p[1:5]), qh=tuple(float(x) for x in p[5:9]),
                                 tof=int(p[9]), guard=float(p[10]), target=float(p[11]), state=int(p[12]),
                                 homed=bool(f & 1), clipper=bool(f & 2), vacuum=bool(f & 4), estop_ok=bool(f & 8),
                                 tof_ok=bool(f & 16), clip_imu=bool(f & 32), head_imu=bool(f & 64),
                                 trigger=bool(f & 128), permit=bool(f & 256))
            except ValueError:
                pass
        elif line == "DONE":
            self._done.set()
        elif line.startswith("FAULT"):
            self.last_fault = line[6:] or "FAULT"
            self._set_status(state=4, clipper=False)
            self._done.set()
        elif line.startswith("ERR"):
            self.last_error = line[4:]

    # --- commands
    def home(self):
        self._done.clear()
        self._write("H")

    def guard(self, mm):
        now = time.time()
        if self._last_guard is None or abs(mm - self._last_guard) > 0.05 or now - self._last_guard_t > 0.2:
            self._write(f"G {mm:.2f}")
            self._last_guard, self._last_guard_t = mm, now

    def permit(self, on):
        """Clipper permit lease: "C 1" must be renewed every loop (<150 ms) or the board turns the clipper off."""
        now = time.time()
        if on:
            self._write("C 1")
        elif self._last_permit is not False or now - self._last_permit_t > 0.5:
            self._write("C 0")
            self._last_permit_t = now
        self._last_permit = on

    def vacuum(self, on):
        self._write("V 1" if on else "V 0")

    def stop(self):
        self._write("S")

    def reset(self):
        self.last_fault = None
        self._write("R")


# ====================================================================== simulator
def _rot_from_to(a, b):
    """Rotation matrix turning unit vector a onto unit vector b."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if c < -0.999999:
        axis = np.cross(a, [1, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1, 0])
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def _axis_angle(axis, deg):
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    t = math.radians(deg)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K


def _sweep_path():
    """A user's path over the head: passes front-to-back, each going from the crown down and back up."""
    pts = []
    flip = False
    for yaw in np.arange(-170.0, 170.1, 8.0):
        top = max_pitch(yaw) - 3.0
        ps = list(np.arange(0.0, top + 0.1, 3.0))
        pts += [(float(yaw), float(p)) for p in (ps[::-1] if flip else ps)]
        flip = not flip
    return pts


class SimLink(LinkBase):
    """Fake board + fake user for testing with no hardware.
    It generates real quaternions from a made-up sensor mounting, so the calibration math is exercised."""
    GUARD_SPEED = 12.0   # mm/s, same as firmware
    HAND_SPEED = 30.0    # deg/s along the head

    def __init__(self, speedup=1.0, seed=1):
        super().__init__()
        rnd = random.Random(seed)
        self.speedup = speedup
        # made-up mounting: head sensor tilted on the headband, headband turned in the room
        self.R_head = _axis_angle([rnd.uniform(-1, 1), rnd.uniform(-1, 1), 1], rnd.uniform(20, 160))
        self.M_true = _axis_angle([rnd.uniform(-1, 1), 1, rnd.uniform(-1, 1)], rnd.uniform(10, 60))  # head-sensor -> head
        self.state = 0
        self.homed = False
        self.guard_mm = config.GUARD_MAX
        self.target_mm = config.GUARD_MAX
        self.permit_until = 0.0
        self.clip = False
        self.vac = False
        self.trigger = False
        self.hand = (0.0, 0.0)          # where the "user" holds the clipper
        self.auto = False               # user sweeping the head during a session
        self.path = _sweep_path()
        self.path_i = 0.0
        self.roll = 0.0
        self.on_head = True
        self._home_until = None
        threading.Thread(target=self._run, daemon=True).start()

    # --- test hooks used by the controller in --sim
    def sim_place(self, yaw, pitch):
        self.auto = False
        self.hand = (yaw, pitch)

    def sim_auto(self, on):
        self.auto = on
        self.trigger = on
        if on:
            self.path_i = 0.0

    def sim_toggle_trigger(self):
        self.trigger = not self.trigger
        return self.trigger

    def sim_wander_to_face(self, seconds=2.0):
        """User drifts toward the face for a moment (tests the no-cut zone)."""
        self._face_until = time.time() + seconds / self.speedup

    _face_until = 0.0

    # --- physics
    def _quats(self):
        n_head = direction(*self.hand)
        n_world = self.R_head @ (self.M_true.T @ n_head)
        a = np.array(config.CLIP_AXIS, float)
        R_clip = _axis_angle(-n_world, self.roll) @ _rot_from_to(a, -n_world)
        return matrix_to_quat(R_clip), matrix_to_quat(self.R_head)

    def _run(self):
        last = time.time()
        while True:
            time.sleep(0.01)
            now = time.time()
            dt = (now - last) * self.speedup
            last = now
            if self.state == 1 and now >= self._home_until:
                self.homed, self.state, self.guard_mm, self.target_mm = True, 2, config.GUARD_MAX, config.GUARD_MAX
                self._done.set()
            if self.homed:
                step = self.GUARD_SPEED * dt
                d = self.target_mm - self.guard_mm
                self.guard_mm += max(-step, min(step, d))
            # simulated user
            self.roll = 25.0 * math.sin(now * 0.7)          # wrist roll: must not affect the location
            if self.auto:
                if now < self._face_until:
                    self.hand = (0.0, 75.0)                 # forehead / face zone
                elif abs(self.guard_mm - self.target_mm) > 1.0:
                    pass                                    # user waits for the guard (the app says "slow down")
                elif self.path_i < len(self.path) - 1:
                    i0 = int(self.path_i)
                    (y0, p0), (y1, p1) = self.path[i0], self.path[i0 + 1]
                    seg = max(1e-6, math.hypot((y1 - y0) * math.sin(math.radians(max(p0, 10))), p1 - p0))
                    self.path_i = min(len(self.path) - 1, self.path_i + self.HAND_SPEED * dt / seg)
                    f = self.path_i - int(self.path_i)
                    i0 = int(self.path_i)
                    i1 = min(i0 + 1, len(self.path) - 1)
                    (y0, p0), (y1, p1) = self.path[i0], self.path[i1]
                    self.hand = (y0 + (y1 - y0) * f, p0 + (p1 - p0) * f)
            self.clip = self.state == 2 and self.trigger and now < self.permit_until
            qc, qh = self._quats()
            tof = int(self.guard_mm + config.TOF_OFFSET + random.uniform(-2, 2)) if self.on_head else 0
            self._set_status(qc=qc, qh=qh, tof=tof, guard=round(self.guard_mm, 2), target=round(self.target_mm, 2),
                             state=self.state, homed=self.homed, clipper=self.clip, vacuum=self.vac, estop_ok=True,
                             tof_ok=True, clip_imu=True, head_imu=True, trigger=self.trigger,
                             permit=now < self.permit_until)

    # --- commands (same as SerialLink)
    def home(self):
        self._done.clear()
        if self.state == 4:
            self.last_error = "reset first"
            self._done.set()
            return
        self.state = 1
        self._home_until = time.time() + 1.5 / self.speedup

    def guard(self, mm):
        if self.homed and self.state == 2:
            self.target_mm = max(config.GUARD_MIN, min(config.GUARD_MAX, mm))

    def permit(self, on):
        if on and self.homed and self.state == 2:
            self.permit_until = time.time() + 0.15
        elif not on:
            self.permit_until = 0.0

    def vacuum(self, on):
        self.vac = on and self.state != 4

    def stop(self):
        if self.state != 4:
            self.last_fault = "STOP_CMD"
        self.state = 4
        self.permit_until = 0.0
        self.vac = False
        self.target_mm = config.GUARD_MAX
        self.auto = False
        self._done.set()

    def reset(self):
        if self.state == 4:
            self.state = 2 if self.homed else 0
            self.last_fault = None
