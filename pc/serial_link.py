"""Talks to the Arduino (SerialLink) or pretends to be it (SimLink).

Both expose the same interface so the rest of the software doesn't care which one it has.
"""
import math
import threading
import time

import config
from kinematics import max_pitch

STATE_NAMES = {0: "BOOT", 1: "HOMING", 2: "IDLE", 3: "MOVING", 4: "FAULT"}


class LinkBase:
    def __init__(self):
        self.lock = threading.Lock()
        self.status = {"yaw": 0.0, "pitch": 0.0, "rad": 0.0, "guard": 40.0, "tof1": 0, "tof2": 0,
                       "state": 0, "state_name": "BOOT", "homed": False, "clipper": False,
                       "vacuum": False, "estop_ok": True, "tof_ok": False, "age": 0.0}
        self._status_t = 0.0
        self._done = threading.Event()
        self.last_fault = None
        self.last_error = None

    # --- helpers shared by both
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

    def wait_done(self, timeout, abort_event=None):
        """Wait for DONE. Returns False on timeout/abort/fault."""
        t_end = time.time() + timeout
        while time.time() < t_end:
            if self._done.wait(0.02):
                return self.get_status()["state"] != 4
            if abort_event is not None and abort_event.is_set():
                return False
        return False


class SerialLink(LinkBase):
    def __init__(self, port=config.SERIAL_PORT, baud=config.BAUD):
        super().__init__()
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=0.05)
        time.sleep(2.0)  # the Mega resets when the port opens
        self._wlock = threading.Lock()
        self._alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def _write(self, line):
        with self._wlock:
            self.ser.write((line + "\n").encode())

    def _heartbeat(self):
        while self._alive:
            try:
                self._write("P")
            except Exception:
                pass
            time.sleep(0.1)

    def _reader(self):
        buf = b""
        while self._alive:
            try:
                chunk = self.ser.read(256)
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
            if len(p) != 9:
                return
            try:
                flags = int(p[8])
                self._set_status(yaw=float(p[1]), pitch=float(p[2]), rad=float(p[3]), guard=float(p[4]),
                                 tof1=int(p[5]), tof2=int(p[6]), state=int(p[7]),
                                 homed=bool(flags & 1), clipper=bool(flags & 2), vacuum=bool(flags & 4),
                                 estop_ok=bool(flags & 8), tof_ok=bool(flags & 16))
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

    def move(self, yaw, pitch, rad, guard, feed):
        self._done.clear()
        self._write(f"M {yaw:.2f} {pitch:.2f} {rad:.2f} {guard:.2f} {feed:.0f}")

    def clipper(self, on):
        self.last_error = None
        self._write("C 1" if on else "C 0")
        time.sleep(0.05)
        return self.last_error is None

    def vacuum(self, on):
        self._write("V 1" if on else "V 0")

    def stop(self):
        self._write("S")

    def reset(self):
        self.last_fault = None
        self._write("R")


class SimLink(LinkBase):
    """Fake machine for testing the software with no hardware. Mimics the firmware's behavior."""
    VMAX = {"yaw": 30.0, "pitch": 15.0, "rad": 10.0, "guard": 4.0}
    LIMITS = {"yaw": (config.YAW_MIN, config.YAW_MAX), "pitch": (config.PITCH_MIN, config.PITCH_MAX),
              "rad": (config.RAD_MIN, config.RAD_MAX), "guard": (config.GUARD_MIN, config.GUARD_MAX)}

    def __init__(self, speedup=1.0):
        super().__init__()
        self.speedup = speedup
        self.pos = {"yaw": 0.0, "pitch": 0.0, "rad": 0.0, "guard": 40.0}
        self.start = dict(self.pos)
        self.target = dict(self.pos)
        self.t0 = 0.0
        self.dur = 0.0
        self.state = 0
        self.homed = False
        self.clip = False
        self.vac = False
        self.retracting = False
        self._home_until = None
        self._set_status(state=0, tof_ok=True)
        threading.Thread(target=self._run, daemon=True).start()

    def _fault(self, why):
        if self.state != 4:
            self.last_fault = why
        self.state = 4
        self.clip = False
        self.vac = False
        self.target = dict(self.pos)
        self.retracting = self.homed
        self._done.set()

    def _run(self):
        last = time.time()
        while True:
            time.sleep(0.01)
            now = time.time()
            dt = (now - last) * self.speedup
            last = now
            if self.state == 1 and now >= self._home_until:
                self.pos = {"yaw": 0.0, "pitch": 0.0, "rad": 0.0, "guard": 40.0}
                self.homed = True
                self.state = 2
                self._done.set()
            elif self.state == 3:
                frac = min(1.0, (now - self.t0) * self.speedup / self.dur)
                for k in self.pos:
                    self.pos[k] = self.start[k] + (self.target[k] - self.start[k]) * frac
                if frac >= 1.0:
                    self.state = 2
                    self._done.set()
            elif self.state == 4 and self.retracting:
                self.pos["rad"] = max(0.0, self.pos["rad"] - 8.0 * dt)
            if self.clip and self.pos["pitch"] > max_pitch(self.pos["yaw"]) + 5.0:
                self._fault("forbidden zone")
            self._set_status(yaw=self.pos["yaw"], pitch=self.pos["pitch"], rad=self.pos["rad"],
                             guard=self.pos["guard"], tof1=60, tof2=60, state=self.state, homed=self.homed,
                             clipper=self.clip, vacuum=self.vac, estop_ok=True, tof_ok=True)

    def home(self):
        self._done.clear()
        if self.state == 4:
            self.last_error = "reset first"
            self._done.set()
            return
        self.state = 1
        self.clip = False
        self._home_until = time.time() + 2.0 / self.speedup

    def move(self, yaw, pitch, rad, guard, feed):
        self._done.clear()
        tgt = {"yaw": yaw, "pitch": pitch, "rad": rad, "guard": guard}
        if not self.homed or self.state in (3, 4):
            self.last_error = "not ready"
            self._done.set()
            return
        for k, v in tgt.items():
            lo, hi = self.LIMITS[k]
            if not lo - 0.01 <= v <= hi + 0.01:
                self.last_error = f"limit {k}"
                self._done.set()
                return
        feed = max(1.0, min(100.0, feed))
        dur = max(abs(tgt[k] - self.pos[k]) / (self.VMAX[k] * feed / 100.0) for k in tgt)
        if dur < 1e-3:
            self._done.set()
            return
        self.start, self.target, self.t0, self.dur = dict(self.pos), tgt, time.time(), dur
        self.state = 3

    def clipper(self, on):
        if on and (not self.homed or self.state == 4 or self.pos["pitch"] > max_pitch(self.pos["yaw"]) + 5.0):
            self.last_error = "clipper refused"
            return False
        self.clip = on
        return True

    def vacuum(self, on):
        self.vac = on and self.state != 4

    def stop(self):
        self._fault("STOP_CMD")

    def reset(self):
        if self.state == 4:
            self.state = 2 if self.homed else 0
            self.retracting = False
            self.last_fault = None
