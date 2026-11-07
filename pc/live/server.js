/*
  HairBarbot live server (Node.js + Socket.io)
  --------------------------------------------
  Sits between the browsers and the Python controller (pc/app.py):
    browsers  <-- Socket.io, real time -->  this server  <-- HTTP, 10x per second -->  Python controller
  The Python side keeps all the safety logic. This server only relays live data and button presses.

  Run (from pc/live):
    npm install
    npm run demo                 # starts the Python simulator for you, then the live app
    npm start                    # connects to an already-running Python app (python app.py ...)

  Options:  --sim  --speedup 3  --py http://localhost:5000  --port 3000
  Pages:    http://localhost:3000            client app (the tablet in front of the client)
            http://localhost:3000/operator   team dashboard
*/
const path = require("path");
const os = require("os");
const http = require("http");
const { spawn } = require("child_process");
const express = require("express");
const { Server } = require("socket.io");

// ---------------------------------------------------------------- options
const args = process.argv.slice(2);
const opt = (name, def) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : def;
};
const SIM = args.includes("--sim");
const PORT = Number(opt("--port", process.env.PORT || 3000));
const PY_URL = opt("--py", process.env.PY_URL || "http://127.0.0.1:5000");
const SPEEDUP = opt("--speedup", "3");
const POLL_MS = 100;

// ---------------------------------------------------------------- optional: start the Python simulator
let child = null;
if (SIM) {
  const py = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  const pyPort = new URL(PY_URL).port || "5000";
  child = spawn(py, ["app.py", "--sim", "--speedup", SPEEDUP, "--http", pyPort], {
    cwd: path.join(__dirname, ".."),
    stdio: ["ignore", "inherit", "inherit"],
  });
  child.on("exit", (code) => console.log(`[python] exited (${code})`));
  const stop = () => { if (child) child.kill(); process.exit(0); };
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
}

// ---------------------------------------------------------------- web server
const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));
app.use("/vendor/three", express.static(path.join(__dirname, "node_modules", "three")));
app.get("/operator", (_req, res) => res.sendFile(path.join(__dirname, "public", "operator.html")));
app.get("/camera.jpg", async (_req, res) => {
  try {
    const r = await fetch(`${PY_URL}/api/camera.jpg`);
    if (!r.ok) return res.sendStatus(404);
    res.set("Content-Type", "image/jpeg").set("Cache-Control", "no-store");
    res.send(Buffer.from(await r.arrayBuffer()));
  } catch {
    res.sendStatus(503);
  }
});

const server = http.createServer(app);
const io = new Server(server);

// ---------------------------------------------------------------- talking to Python
async function py(method, route, body) {
  const r = await fetch(`${PY_URL}${route}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(3000),
  });
  const json = await r.json().catch(() => ({}));
  return { ok: r.ok && json.ok !== false, status: r.status, json };
}

// Only these commands can be sent from a browser.
const COMMANDS = {
  home: "/api/home",
  reset: "/api/reset",
  stop: "/api/stop",
  pause: "/api/pause",
  resume: "/api/resume",
  cut: "/api/cut",
  calibStart: "/api/calibrate/start",
  calibRecord: "/api/calibrate/record",
  calibFinish: "/api/calibrate/finish",
  calibDefault: "/api/calibrate/default",
  jog: "/api/jog",
  simHeadMove: "/api/sim/head_move",
};

let latest = null;      // last controller status
let plan = null;        // current haircut plan (strokes) for the 3D view
let styles = null;
let linkUp = false;

async function poll() {
  try {
    const { json } = await py("GET", "/api/state");
    if (!linkUp) console.log("[live] connected to Python controller");
    linkUp = true;
    latest = json;
    if (!styles) styles = (await py("GET", "/api/styles")).json;
    if (!plan || plan.version !== json.plan_version) {
      plan = (await py("GET", "/api/plan")).json;
      io.emit("plan", plan);
    }
    io.volatile.emit("state", json);
  } catch {
    if (linkUp) console.log("[live] lost the Python controller, retrying...");
    linkUp = false;
  }
  io.volatile.emit("link", { python: linkUp, t: Date.now() });
  setTimeout(poll, POLL_MS);
}

io.on("connection", (socket) => {
  if (styles) socket.emit("styles", styles);
  if (plan) socket.emit("plan", plan);
  if (latest) socket.emit("state", latest);
  socket.emit("link", { python: linkUp, t: Date.now() });

  socket.on("hello", (_m, cb) => cb && cb({ styles, plan, state: latest }));

  socket.on("cmd", async ({ action, body } = {}, cb = () => {}) => {
    if (action === "calibGoto") {
      const i = Number(body && body.i);
      if (!Number.isInteger(i)) return cb({ ok: false, error: "bad point" });
      return relay(`/api/calibrate/goto/${i}`, undefined, cb, action);
    }
    const route = COMMANDS[action];
    if (!route) return cb({ ok: false, error: `unknown command ${action}` });
    relay(route, body, cb, action);
  });

  socket.on("preview", async (body, cb = () => {}) => {
    try {
      const r = await py("POST", "/api/preview", body);
      cb(r.ok ? { ok: true, grid: r.json } : { ok: false, error: r.json.error });
    } catch (e) {
      cb({ ok: false, error: "controller not reachable" });
    }
  });
});

async function relay(route, body, cb, action) {
  try {
    const r = await py("POST", route, body || {});
    if (action === "stop") console.log("[live] STOP pressed in an app");
    cb(r.ok ? { ok: true } : { ok: false, error: r.json.error || `error ${r.status}` });
    if (r.json.status) io.emit("state", r.json.status);
  } catch {
    cb({ ok: false, error: "Can't reach the machine controller." });
  }
}

server.listen(PORT, () => {
  const ips = Object.values(os.networkInterfaces()).flat()
    .filter((n) => n && n.family === "IPv4" && !n.internal).map((n) => n.address);
  console.log(`\nHairBarbot live app${SIM ? " (SIMULATION)" : ""}`);
  console.log(`  client app : http://localhost:${PORT}`);
  console.log(`  operator   : http://localhost:${PORT}/operator`);
  ips.forEach((ip) => console.log(`  on Wi-Fi  : http://${ip}:${PORT}  (open on the tablet)`));
  console.log(`  controller : ${PY_URL}\n`);
  poll();
});
