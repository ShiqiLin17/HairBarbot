// HairBarbot operator dashboard: live joints, safety checks, sensors, camera, log, controls.
import { createHeadView } from "./head3d.js";

const $ = (s) => document.querySelector(s);
const socket = io();
const view = createHeadView($("#view"), { follow: false });
let state = null;
let lastLink = { python: false, t: 0 };

const AXES = [
  { k: "yaw", label: "Yaw", unit: "°", min: -170, max: 170 },
  { k: "pitch", label: "Pitch", unit: "°", min: -12, max: 112 },
  { k: "rad", label: "Radial", unit: "mm", min: 0, max: 110 },
  { k: "guard", label: "Guard", unit: "mm", min: 3, max: 40 },
];
$("#gauges").innerHTML = AXES.map((a) => `
  <div class="gauge" id="g_${a.k}">
    <div class="top"><span>${a.label}</span><b class="num">--</b></div>
    <div class="track"><div class="band" hidden></div><div class="fill"></div><div class="mark" hidden></div></div>
    <div class="ends"><span>${a.min}${a.unit}</span><span>${a.max}${a.unit}</span></div>
  </div>`).join("");

// ---------------------------------------------------------------- charts (last 30 s)
const hist = [];
const WINDOW = 30;
function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
function drawChart(canvas, series, { min, max, band, limit }) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const c = canvas.getContext("2d");
  c.scale(dpr, dpr);
  c.clearRect(0, 0, w, h);
  const L = 34, R = 6, T = 8, B = 18;
  const now = performance.now() / 1000;
  const X = (t) => L + ((t - (now - WINDOW)) / WINDOW) * (w - L - R);
  const Y = (v) => T + (1 - (v - min) / (max - min)) * (h - T - B);
  c.font = `11px ${css("--mono")}`;
  c.fillStyle = css("--muted");
  c.strokeStyle = css("--line");
  c.lineWidth = 1;
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const v = min + ((max - min) * i) / ticks, y = Y(v);
    c.beginPath(); c.moveTo(L, y); c.lineTo(w - R, y); c.stroke();
    c.fillText(String(Math.round(v)), 2, y + 4);
  }
  c.fillText("−30 s", L, h - 4);
  c.fillText("now", w - R - 22, h - 4);
  if (band) {
    c.fillStyle = css("--accent") + "38";
    c.beginPath();
    const pts = hist.filter((p) => p[band.key] != null);
    pts.forEach((p, i) => { const x = X(p.t), y = Y(p[band.key] + band.w); i ? c.lineTo(x, y) : c.moveTo(x, y); });
    [...pts].reverse().forEach((p) => c.lineTo(X(p.t), Y(p[band.key] - band.w)));
    c.closePath(); c.fill();
  }
  if (limit != null) {
    c.strokeStyle = css("--stop"); c.setLineDash([5, 4]);
    c.beginPath(); c.moveTo(L, Y(limit)); c.lineTo(w - R, Y(limit)); c.stroke(); c.setLineDash([]);
  }
  series.forEach((s) => {
    c.strokeStyle = s.color; c.lineWidth = 2; c.beginPath();
    let started = false;
    hist.forEach((p) => {
      const v = p[s.key];
      if (v == null) { started = false; return; }
      const x = X(p.t), y = Y(Math.max(min, Math.min(max, v)));
      started ? c.lineTo(x, y) : c.moveTo(x, y);
      started = true;
    });
    c.stroke();
    const last = [...hist].reverse().find((p) => p[s.key] != null);
    if (last) { c.fillStyle = s.color; c.beginPath(); c.arc(X(last.t), Y(Math.max(min, Math.min(max, last[s.key]))), 3.5, 0, 7); c.fill(); }
  });
}
function charts() {
  drawChart($("#guardChart"), [{ key: "need", color: css("--accent") }, { key: "guard", color: css("--data") }], { min: 0, max: 40, band: { key: "need", w: 1.5 } });
  drawChart($("#depthChart"), [{ key: "depth", color: css("--data") }], { min: -10, max: 30, limit: -6 });
  requestAnimationFrame(charts);
}
requestAnimationFrame(charts);

// ---------------------------------------------------------------- helpers
function toast(text) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = text;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}
function cmd(action, body) {
  socket.emit("cmd", { action, body }, (r) => { if (!r || !r.ok) toast((r && r.error) || "Command failed."); });
}
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
const yes = (b, a = "yes", n = "no") => `<span class="${b ? "good" : "bad"}">${b ? a : n}</span>`;

// ---------------------------------------------------------------- render
function render(s) {
  state = s;
  const m = s.machine, live = s.live || {}, t = s.tracker || {};
  const st = s.state;

  const msg = $("#msg");
  msg.textContent = s.message;
  msg.className = "msgbar" + (st === "STOPPED" ? " bad" : "");

  $("#stateChip").className = "chip " + (st === "STOPPED" ? "hot" : st === "CUTTING" ? "on" : "");
  $("#stateChip").lastChild.textContent = st.replace("_", " ") + (s.sim ? " · SIM" : "");
  $("#fwChip").className = "chip " + (m.state_name === "FAULT" ? "hot" : m.homed ? "on" : "warn");
  $("#fwChip").lastChild.textContent = "Firmware " + m.state_name + (s.fault ? ` · ${s.fault}` : "");
  $("#progTxt").textContent = s.progress.total ? `${s.progress.done}/${s.progress.total} strokes` : "";

  // gauges
  AXES.forEach((a) => {
    const el = $("#g_" + a.k), v = m[a.k];
    el.querySelector("b").textContent = `${v.toFixed(1)} ${a.unit}`;
    const f = (x) => Math.max(0, Math.min(1, (x - a.min) / (a.max - a.min))) * 100;
    el.querySelector(".fill").style.width = f(v) + "%";
    if (a.k === "guard") {
      const mark = el.querySelector(".mark"), band = el.querySelector(".band");
      const need = live.need_guard;
      mark.hidden = band.hidden = need == null;
      if (need != null) {
        mark.style.left = `calc(${f(need)}% - 1px)`;
        band.style.left = f(need - 1.5) + "%";
        band.style.width = f(need + 1.5) - f(need - 1.5) + "%";
      }
    }
  });

  // chart samples
  const now = performance.now() / 1000;
  const depth = live.tip_r != null && live.scalp_r != null && m.clipper ? live.tip_r - live.scalp_r : null;
  hist.push({ t: now, guard: m.guard, need: m.clipper ? live.need_guard : null, depth });
  while (hist.length && hist[0].t < now - 32) hist.shift();
  $("#guardErr").textContent = m.clipper && live.need_guard != null ? `error ${(m.guard - live.need_guard).toFixed(2)} mm` : "clipper off";
  $("#depthTxt").textContent = depth != null ? `${depth.toFixed(1)} mm` : "";

  // sensors
  $("#sensors").innerHTML = `
    <span>Clipper</span><span>${m.clipper ? '<span class="bad">ON</span>' : "off"}</span>
    <span>Vacuum</span><span>${m.vacuum ? "on" : "off"}</span>
    <span>E-stop</span><span>${yes(m.estop_ok, "released", "PRESSED")}</span>
    <span>ToF sensors</span><span>${m.tof_ok ? `${m.tof1} / ${m.tof2} mm` : '<span class="bad">not ok</span>'}</span>
    <span>Head check</span><span>${yes(t.ok, "ok", t.reason || "fail")}</span>
    <span>Head moved</span><span>${t.move_mm != null ? t.move_mm.toFixed(1) + " mm" : "--"}</span>
    <span>Head turned</span><span>${t.rot_deg != null ? t.rot_deg.toFixed(1) + "°" : "--"}</span>
    <span>Cutting area</span><span>${live.region || "--"}</span>
    <span>Status age</span><span>${(m.age * 1000).toFixed(0)} ms</span>
    <span>Elapsed / left</span><span>${live.elapsed != null ? Math.round(live.elapsed) + " s" : "--"} / ${live.eta_s != null ? live.eta_s + " s" : "--"}</span>`;

  // controls
  $("#homeBtn").disabled = !["NOT_HOMED", "IDLE", "READY", "DONE"].includes(st) || s.busy;
  $("#resetBtn").disabled = st !== "STOPPED";
  $("#pauseBtn").disabled = !(st === "CUTTING" || st === "PAUSED");
  $("#pauseBtn").textContent = st === "PAUSED" ? "Resume" : "Pause";
  $("#simTools").hidden = !s.sim;
  $("#camNote").hidden = !s.sim;
  $("#cam").hidden = s.sim;

  // calibration
  const c = s.calibration;
  $("#headSize").textContent = c.calibrated ? `${(2 * c.head.a).toFixed(0)} × ${(2 * c.head.b).toFixed(0)} mm` : "not calibrated";
  $("#pts").innerHTML = c.poses.map((n, i) => `<li class="${c.current === i ? "cur" : ""}"><span>${c.recorded.includes(n) ? "✓ " : ""}${n}</span><button class="b" data-goto="${i}" ${st !== "CALIBRATING" ? "disabled" : ""}>Go</button></li>`).join("");
  document.querySelectorAll("[data-jog],#calRec,#calFin").forEach((b) => (b.disabled = st !== "CALIBRATING"));
  $("#calStart").disabled = !["IDLE", "READY", "DONE"].includes(st);

  // log
  $("#log").innerHTML = (s.events || []).slice().reverse().map((e) => `<li class="${e.kind}"><time>${clock(e.t)}</time><span>${e.text}</span></li>`).join("") || "<li><time></time><span>No events yet.</span></li>";

  view.update(s);
}

// ---------------------------------------------------------------- socket
socket.on("state", render);
socket.on("plan", (p) => view.setPlan(p));
let lengthsKey = "";
socket.on("state", (s) => {
  const key = JSON.stringify([s.lengths, s.fade_to]);
  if (s.lengths && key !== lengthsKey) {
    lengthsKey = key;
    socket.emit("preview", { lengths: s.lengths, fade_to: s.fade_to }, (r) => r && r.ok && view.setLengths(r.grid));
  }
});
socket.on("link", (l) => {
  lastLink = l;
  $("#offline").hidden = l.python;
  $("#linkChip").className = "chip " + (l.python ? "on" : "hot");
  $("#linkChip").lastChild.textContent = l.python ? "Controller linked" : "Controller offline";
});
socket.on("disconnect", () => { $("#offline").hidden = false; });

// ---------------------------------------------------------------- buttons
$("#stopBtn").onclick = () => cmd("stop");
$("#homeBtn").onclick = () => cmd("home");
$("#resetBtn").onclick = () => cmd("reset");
$("#pauseBtn").onclick = () => cmd(state && state.state === "PAUSED" ? "resume" : "pause");
$("#defBtn").onclick = () => cmd("calibDefault");
$("#bumpBtn").onclick = () => cmd("simHeadMove");
$("#calStart").onclick = () => cmd("calibStart");
$("#calRec").onclick = () => cmd("calibRecord");
$("#calFin").onclick = () => cmd("calibFinish");
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) cmd("calibGoto", { i: +g.dataset.goto });
  const j = e.target.closest("[data-jog]");
  if (j) cmd("jog", { mm: +j.dataset.jog });
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); cmd("stop"); } });

// camera feed (real machine only)
setInterval(() => {
  if (state && !state.sim) $("#cam").src = "/camera.jpg?t=" + Date.now();
}, 250);
