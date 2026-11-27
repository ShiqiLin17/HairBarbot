"""Talks to the ESP32 (SerialLink) or pretends to be it (SimLink). Same interface for both."""
import math
import random
import threading
import time

import numpy as np

import config
from orientation import matrix_to_quat, max_pitch

STATE_NAMES = {0: "NOT_HOMED", 1: "HOMING", 2: "READY", 4: "FAULT"}


def _empty_status():
    return {"q": (1.0, 0.0, 0.0, 0.0), "fsr": (0, 0), "guard": config.GUARD_MAX, "target": config.GUARD_MAX,
            "state": 0, "state_name": "NOT_HOMED", "homed": False, "clipper": False, "vacuum": False,
            "estop_ok": True, "drive_ok": False, "imu_ok": False, "trigger": False, "permit": False, "age": 99.0}


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
            # ST qw qx qy qz fsrA fsrB guard target state flags
            if len(p) != 11:
                return
            try:
                f = int(p[10])
                self._set_status(q=tuple(float(x) for x in p[1:5]), fsr=(int(p[5]), int(p[6])), guard=float(p[7]),
                                 target=float(p[8]), state=int(p[9]), homed=bool(f & 1), clipper=bool(f & 2),
                                 vacuum=bool(f & 4), estop_ok=bool(f & 8), drive_ok=bool(f & 16), imu_ok=bool(f & 32),
                                 trigger=bool(f & 64), permit=bool(f & 128))
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


def _placements():
    """Where the simulated user puts the cutter down, one spot after another: rows from the nape up to the
    crown, each row going around the head. Spots are ~10 deg apart so each patch overlaps the last."""
    spots = []
    flip = False
    for pitch in np.arange(100.0, -1.0, -10.0):
        ring = 2 * math.pi * math.sin(math.radians(max(pitch, 1.0)))
        n = max(1, int(math.ceil(ring * 180 / math.pi / 10.0)))
        ys = [-180.0 + 360.0 * (k + 0.5) / n for k in range(n)]
        if flip:
            ys = ys[::-1]
        flip = not flip
        for y in ys:
            if pitch <= max_pitch(y) - 3.0:
                spots.append((float(y), float(pitch)))
    return spots


class SimLink(LinkBase):
    """Fake board + fake user for testing with no hardware.

    The fake user faces a random direction in the room (so the calibration math is exercised) and cuts by
    PLACING the cutter: put it down flat on a spot (both force pads pressed), wait for the guard if it's still
    moving, cut for a moment, lift it, move to the next spot. The IMU's heading drifts slowly, like a real one
    (BNO085 game rotation vector), which the camera's tag sightings correct."""
    GUARD_SPEED = 5.5    # mm/s: Carlos's D2.2 screw drive, ~31.75 mm in 5-7 s
    DWELL_S = 0.7        # time the user keeps the cutter on one spot with the clipper running
    LIFT_S = 0.35        # time in the air moving to the next spot
    LIFT_MM = 15.0       # how high the cutter is lifted between spots
    FSR_PRESSED = 1500   # ADC counts with the cutter resting on the head

    def __init__(self, speedup=1.0, seed=1, profile=None, imu_drift_deg_per_min=2.0):
        super().__init__()
        rnd = random.Random(seed)
        self._rng = np.random.default_rng(seed)
        self.speedup = speedup
        from orientation import SurfaceLocator
        self.surface = SurfaceLocator(profile)   # cutter is held flat: it points along the head's surface normal
        self.head_yaw = 0.0                       # the user turning their head (deg, + = to their left)
        self._turn = None                         # (start, end, t0, duration) of a head turn in progress
        # a webcam on the table in front of the user: room -> camera rotation (fixed)
        from vision_geometry import head_to_cam_facing
        self.C_room_to_cam = None
        self._head_to_cam_facing = head_to_cam_facing
        # the user faces a random direction in the room (head upright): M_true = room axes -> head axes
        self.M_true = _axis_angle([0, 0, 1], rnd.uniform(-180, 180)) @ _axis_angle([1, 0, 0], rnd.uniform(-5, 5))
        self.drift_rate = imu_drift_deg_per_min / 60.0
        self.drift = 0.0                          # IMU heading error so far (deg, about the room's vertical)
        self.state = 0
        self.homed = False
        self.guard_mm = config.GUARD_MAX
        self.target_mm = config.GUARD_MAX
        self.permit_until = 0.0
        self.clip = False
        self.vac = False
        self.trigger = False
        self.hand = (0.0, 0.0)          # spot the cutter is over
        self.seated = False             # resting flat on the head (both pads pressed)
        self.tilt = 0.0                 # cutter tilted off flat (deg): one pad lifts
        self.auto = False               # user placing the cutter spot by spot during a session
        self.spots = _placements()
        self.spot_i = 0
        self._phase, self._phase_t = "lift", 0.0
        self._from = (0.0, 0.0)
        self.roll = 0.0
        self.placements = 0
        self._home_until = None
        threading.Thread(target=self._run, daemon=True).start()

    # --- test hooks used by the controller in --sim
    def sim_place(self, yaw, pitch):
        """Put the cutter down flat at (yaw, pitch) and hold it there."""
        self.auto = False
        self.hand = (yaw, pitch)
        self.seated, self.tilt = True, 0.0

    def sim_lift(self):
        self.auto = False
        self.seated = False

    def sim_tilt(self, deg):
        """Rock the cutter off flat (one pad lifts) while staying on the spot."""
        self.tilt = float(deg)

    def sim_auto(self, on):
        self.auto = on
        self.trigger = on
        if on:
            self.spot_i = 0
            self._phase, self._phase_t = "lift", 0.0
            self._from = self.hand

    def sim_toggle_trigger(self):
        self.trigger = not self.trigger
        return self.trigger

    def sim_wander_to_face(self, seconds=2.0):
        """User puts the cutter down near the face for a moment (tests the no-cut zone)."""
        self._face_until = time.time() + seconds / self.speedup

    _face_until = 0.0

    def sim_cutter_truth(self):
        """Where the cutter really is (for the simulated camera): (scalp-face point mm, into-scalp axis), head axes."""
        y, p = self.hand
        n = self.surface.normal(y, p)
        pt = self.surface.point(y, p) + n * (0.0 if self.seated else self.LIFT_MM)
        return pt, -self._cutter_dir_head()

    # --- the user's head in the room
    def world_to_head(self):
        """room axes -> head axes right now (the head may be turned)."""
        return self.M_true @ _axis_angle([0, 0, 1], -self.head_yaw)

    def head_to_camera(self):
        if self.C_room_to_cam is None:   # camera placed in front of the user's starting position
            self.C_room_to_cam = self._head_to_cam_facing() @ self.M_true
        return self.C_room_to_cam @ self.world_to_head().T

    def sim_turn_head(self, deg, seconds=1.0):
        """The simulated user turns their head to `deg` (to their left = +) over `seconds`."""
        self._turn = (self.head_yaw, float(deg), time.time(), seconds / self.speedup)

    def _cutter_dir_head(self):
        """Outward direction through the cutter (head axes): the surface normal, tilted if the user rocks it."""
        n = self.surface.normal(*self.hand)
        if self.tilt:
            side = np.cross(n, [0.0, 0.0, 1.0])
            if np.linalg.norm(side) < 1e-6:
                side = np.array([0.0, 1.0, 0.0])
            n = _axis_angle(side, self.tilt) @ n
        return n

    def _quat(self):
        n_world = self.world_to_head().T @ self._cutter_dir_head()
        a = np.array(config.CLIP_AXIS, float)
        R = _axis_angle(-n_world, self.roll) @ _rot_from_to(a, -n_world)
        R = _axis_angle([0, 0, 1], self.drift) @ R            # the IMU's heading has drifted
        return matrix_to_quat(R)

    def _fsr(self):
        if not self.seated:
            return (int(self._rng.integers(0, 40)), int(self._rng.integers(0, 40)))
        a = b = self.FSR_PRESSED
        if abs(self.tilt) > 4:                                 # rocked: one pad comes off the head
            b = 120
        return (int(a + self._rng.normal(0, 40)), int(b + self._rng.normal(0, 40)))

    def _user(self, now, dt):
        """The fake user placing the cutter spot after spot."""
        t = now - self._phase_t
        if now < self._face_until:
            self.hand, self.seated = (0.0, 75.0), True          # forehead / face: must not cut
            return
        if self._phase == "lift":
            self.seated = False
            target = self.spots[self.spot_i]
            f = min(1.0, t * self.speedup / self.LIFT_S)
            (y0, p0), (y1, p1) = self._from, target
            dy = (y1 - y0 + 180.0) % 360.0 - 180.0
            self.hand = (((y0 + dy * f) + 180.0) % 360.0 - 180.0, p0 + (p1 - p0) * f)
            if f >= 1.0:
                self._phase, self._phase_t = "place", now
                self.placements += 1
        elif self._phase == "place":
            self.seated = True
            # the app tells the user to hold still while the guard adjusts; the clipper starts when it can
            if self.clip and t * self.speedup > 0.05:
                self._phase, self._phase_t = "cut", now
            elif t * self.speedup > 15.0:                     # never allowed here (e.g. zone): move on
                self._next(now)
        elif self._phase == "cut":
            self.seated = True
            if t * self.speedup >= self.DWELL_S:
                self._next(now)

    def _next(self, now):
        self._from = self.hand
        if self.spot_i < len(self.spots) - 1:
            self.spot_i += 1
        else:
            self.spot_i = 0                                    # go around again until the app says done
        self._phase, self._phase_t = "lift", now

    def _run(self):
        last = time.time()
        while True:
            time.sleep(0.01)
            now = time.time()
            dt = (now - last) * self.speedup
            last = now
            if self.state == 1 and now >= self._home_until:
                self.homed, self.state, self.guard_mm, self.target_mm = True, 2, config.GUARD_MIN, config.GUARD_MAX
                self._done.set()
            if self.homed:
                step = self.GUARD_SPEED * dt
                d = self.target_mm - self.guard_mm
                self.guard_mm += max(-step, min(step, d))
            if self._turn:
                a, b, t0, dur = self._turn
                f = min(1.0, (now - t0) / max(dur, 1e-6))
                self.head_yaw = a + (b - a) * f
                if f >= 1.0:
                    self._turn = None
            self.drift += self.drift_rate * dt
            self.roll = 25.0 * math.sin(now * 0.7)          # wrist roll: must not affect the location
            if self.auto:
                self._user(now, dt)
            self.clip = self.state == 2 and self.trigger and now < self.permit_until
            self._set_status(q=self._quat(), fsr=self._fsr(), guard=round(self.guard_mm, 2),
                             target=round(self.target_mm, 2), state=self.state, homed=self.homed, clipper=self.clip,
                             vacuum=self.vac, estop_ok=True, drive_ok=True, imu_ok=True, trigger=self.trigger,
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
