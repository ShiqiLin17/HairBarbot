// HairBarbot operator dashboard (handheld): sensors, guard tracking, coverage, calibration, controls.
import { createHeadView } from "./head3d.js";

const $ = (s) => document.querySelector(s);
const socket = io();
const view = createHeadView($("#view"), { follow: false });
let state = null;
let lastPts = "";

// ---------------------------------------------------------------- charts (last 30 s)
const hist = [];
const WINDOW = 30;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function drawChart(canvas, series, { min, max, band, limit }) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const c = canvas.getContext("2d");
  c.scale(dpr, dpr);
  const L = 34, R = 6, T = 8, B = 18;
  const now = performance.now() / 1000;
  const X = (t) => L + ((t - (now - WINDOW)) / WINDOW) * (w - L - R);
  const Y = (v) => T + (1 - (v - min) / (max - min)) * (h - T - B);
  c.font = `11px ${css("--mono")}`;
  c.fillStyle = css("--muted"); c.strokeStyle = css("--line"); c.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const v = min + ((max - min) * i) / 4, y = Y(v);
    c.beginPath(); c.moveTo(L, y); c.lineTo(w - R, y); c.stroke();
    c.fillText(String(Math.round(v)), 2, y + 4);
  }
  c.fillText("−30 s", L, h - 4);
  c.fillText("now", w - R - 22, h - 4);
  if (band) {
    c.fillStyle = css("--accent") + "38";
    hist.filter((p) => p[band.key] != null).forEach((p) => {
      const x = X(p.t), y0 = Y(p[band.key] + band.w), y1 = Y(p[band.key] - band.w);
      c.fillRect(x - 1.5, y0, 3, y1 - y0);
    });
  }
  if (limit != null) {
    c.strokeStyle = css("--stop"); c.setLineDash([5, 4]);
    c.beginPath(); c.moveTo(L, Y(limit)); c.lineTo(w - R, Y(limit)); c.stroke(); c.setLineDash([]);
  }
  series.forEach((s) => {
    c.strokeStyle = s.color; c.lineWidth = 2; c.beginPath();
    let started = false, lastT = 0;
    hist.forEach((p) => {
      const v = p[s.key];
      if (v == null || p.t - lastT > 0.5) started = false;
      lastT = p.t;
      if (v == null) return;
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
  drawChart($("#guardChart"), [{ key: "need", color: css("--accent") }, { key: "guard", color: css("--data") }], { min: 0, max: 60, band: { key: "need", w: 1.5 } });
  drawChart($("#tofChart"), [{ key: "speed", color: css("--data") }, { key: "minLine", color: css("--muted") }], { min: 0, max: 80 });
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
function cmd(action, body) { socket.emit("cmd", { action, body }, (r) => { if (!r || !r.ok) toast((r && r.error) || "Command failed."); }); }
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
const yes = (b, a = "yes", n = "no") => `<span class="${b ? "good" : "bad"}">${b ? a : n}</span>`;
const BLOCKS = { trigger: "trigger released", zone: "near face/ears", guard: "guard adjusting", sensors: "no location", estop: "E-stop" };

// ---------------------------------------------------------------- render
function render(s) {
  state = s;
  const m = s.machine, live = s.live || {}, loc = s.location, st = s.state, cov = s.coverage;
  $("#msg").textContent = s.message;
  $("#msg").className = "msgbar" + (st === "STOPPED" ? " bad" : "");
  $("#stateChip").className = "chip " + (st === "STOPPED" ? "hot" : st === "CUTTING" ? "on" : "");
  $("#stateChip").lastChild.textContent = st.replace("_", " ") + (s.sim ? " · SIM" : "");
  $("#fwChip").className = "chip " + (m.state_name === "FAULT" ? "hot" : m.homed ? "on" : "warn");
  $("#fwChip").lastChild.textContent = "Board " + m.state_name + (s.fault ? ` · ${s.fault}` : "");
  $("#covTxt").textContent = cov ? `${Math.round(cov.pct * 100)}% covered` : "";

  // clipper decision
  const allowed = st === "CUTTING" && !live.block;
  $("#decision").className = "decision " + (m.clipper ? "on" : allowed ? "ok" : "off");
  $("#decision").innerHTML = m.clipper ? "<b>CLIPPER ON</b><span>all checks pass and trigger held</span>" :
    st !== "CUTTING" ? "<b>CLIPPER OFF</b><span>no haircut running</span>" :
    `<b>CLIPPER OFF</b><span>${BLOCKS[live.block] || "waiting"}</span>`;

  // location + guard
  $("#loc").innerHTML = `
    <span>Area</span><span>${loc ? loc.region : "--"}</span>
    <span>Yaw (around)</span><span>${loc ? loc.yaw.toFixed(1) + "°" : "--"}</span>
    <span>Pitch (down)</span><span>${loc ? loc.pitch.toFixed(1) + "°" : "--"}</span>
    <span>Allowed zone</span><span>${loc ? yes(loc.in_zone, "yes", "NO (face/ears)") : "--"}</span>
    <span>Guard</span><span>${m.guard.toFixed(2)} mm</span>
    <span>Needed here</span><span>${live.need_guard != null ? live.need_guard.toFixed(2) + " mm" : "--"}</span>
    <span>Guard error</span><span>${live.need_guard != null ? live.guard_err.toFixed(2) + " mm" : "--"}</span>`;

  const now = performance.now() / 1000;
  hist.push({ t: now, guard: m.guard, need: live.need_guard, speed: m.enc_ok ? Math.abs(live.speed || 0) : null, minLine: 5 });
  while (hist.length && hist[0].t < now - 32) hist.shift();

  // sensors
  $("#sensors").innerHTML = `
    <span>Orientation IMU</span><span>${yes(m.imu_ok, "ok", "MISSING")}</span>
    <span>Roller encoder</span><span>${yes(m.enc_ok, "ok", "MISSING")}</span>
    <span>Rolled (counter)</span><span>${m.rolled.toFixed(0)} mm</span>
    <span>Roller speed</span><span>${live.speed != null ? Math.abs(live.speed).toFixed(0) + " mm/s" : "--"}</span>
    <span>Rolling on head</span><span>${live.rolling ? "yes" : "no"}</span>
    <span>Cut distance</span><span>${live.cut_distance != null ? (live.cut_distance / 10).toFixed(0) + " cm" : "--"}</span>
    <span>Trigger</span><span>${m.trigger ? "held" : "released"}</span>
    <span>Permit lease</span><span>${m.permit ? "active" : "off"}</span>
    <span>Clipper</span><span>${m.clipper ? '<span class="bad">ON</span>' : "off"}</span>
    <span>Vacuum</span><span>${m.vacuum ? "on" : "off"}</span>
    <span>E-stop</span><span>${yes(m.estop_ok, "released", "PRESSED")}</span>
    <span>Status age</span><span>${(m.age * 1000).toFixed(0)} ms</span>`;

  // coverage by region
  $("#regions").innerHTML = cov ? Object.entries(cov.regions).map(([r, v]) =>
    `<div class="reg"><span>${r}</span><div class="rtrack"><div style="width:${Math.round(v * 100)}%"></div></div><b class="num">${Math.round(v * 100)}%</b></div>`).join("") : "";

  // controls
  $("#homeBtn").disabled = !["NOT_HOMED", "IDLE", "READY", "DONE"].includes(st) || s.busy;
  $("#resetBtn").disabled = st !== "STOPPED";
  $("#finishBtn").disabled = st !== "CUTTING";
  $("#simTools").hidden = !s.sim;

  // calibration
  const c = s.calibration;
  $("#calTxt").textContent = c.calibrated ? `calibrated${c.error_deg != null ? ` · ±${c.error_deg}°` : ""}` : "not calibrated";
  const ptsHtml = c.poses.map((n, i) => `<li><span>${c.recorded.includes(i) ? "✓ " : ""}${n}</span><button class="b" data-rec="${i}" ${st !== "CALIBRATING" ? "disabled" : ""}>Record</button></li>`).join("");
  if (ptsHtml !== lastPts) { $("#pts").innerHTML = ptsHtml; lastPts = ptsHtml; }   // only redraw on change, so buttons stay clickable
  $("#calStart").disabled = !["IDLE", "READY", "DONE"].includes(st);
  $("#calFin").disabled = st !== "CALIBRATING";

  $("#log").innerHTML = (s.events || []).slice().reverse().map((e) => `<li class="${e.kind}"><time>${clock(e.t)}</time><span>${e.text}</span></li>`).join("") || "<li><time></time><span>No events yet.</span></li>";
  view.update(s);
}

// ---------------------------------------------------------------- socket
socket.on("state", render);
let lengthsKey = "";
socket.on("state", (s) => {
  const key = JSON.stringify([s.lengths, s.fade_to]);
  if (s.lengths && key !== lengthsKey) {
    lengthsKey = key;
    socket.emit("preview", { lengths: s.lengths, fade_to: s.fade_to }, (r) => r && r.ok && view.setLengths(r.grid));
  }
});
socket.on("link", (l) => {
  $("#offline").hidden = l.python;
  $("#linkChip").className = "chip " + (l.python ? "on" : "hot");
  $("#linkChip").lastChild.textContent = l.python ? "Controller linked" : "Controller offline";
});
socket.on("disconnect", () => { $("#offline").hidden = false; });

$("#stopBtn").onclick = () => cmd("stop");
$("#homeBtn").onclick = () => cmd("home");
$("#resetBtn").onclick = () => cmd("reset");
$("#finishBtn").onclick = () => cmd("finish");
$("#defBtn").onclick = () => cmd("calibDefault");
$("#trigBtn").onclick = () => cmd("simTrigger");
$("#faceBtn").onclick = () => cmd("simFace");
$("#calStart").onclick = () => cmd("calibStart");
$("#calFin").onclick = () => cmd("calibFinish");
document.addEventListener("click", (e) => {
  const r = e.target.closest("[data-rec]");
  if (r) cmd("calibRecord", { i: +r.dataset.rec });
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); cmd("stop"); } });
