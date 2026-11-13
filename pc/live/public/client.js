// HairBarbot client app (handheld): what the user sees while cutting their own hair.
import { createHeadView, lengthColor } from "./head3d.js";

const $ = (s) => document.querySelector(s);
const REGIONS = ["top", "front", "sides", "back", "nape"];
const socket = io();
let styles = {}, gmin = 3, gmax = 60, current = "fade25", state = null;
let showPick = true, prevState = null;
let previewKey = "", previewTimer = null;

const view = createHeadView($("#view"));
$("#legendBar").style.background = `linear-gradient(90deg, ${lengthColor(3)}, ${lengthColor(60)})`;

// ---------------------------------------------------------------- helpers
function toast(text) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = text;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}
function cmd(action, body) {
  return new Promise((res) => socket.emit("cmd", { action, body }, (r) => {
    if (!r || !r.ok) toast((r && r.error) || "Something went wrong.");
    res(r || {});
  }));
}
const fmtTime = (s) => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const pctOf = (v) => Math.max(0, Math.min(100, ((v - gmin) / (gmax - gmin)) * 100));

function lengths() {
  const o = {};
  REGIONS.forEach((r) => (o[r] = +$("#s_" + r).value));
  return o;
}
const fadeTo = () => ($("#fadeOn").checked ? +$("#fadeTo").value : null);

// ---------------------------------------------------------------- style picker
function buildPicker() {
  const box = $("#styles");
  box.innerHTML = "";
  Object.entries(styles).forEach(([k, s]) => {
    const b = document.createElement("button");
    b.className = "style"; b.dataset.k = k; b.type = "button";
    b.innerHTML = `<b>${s.name}</b><small>${s.desc}</small>`;
    b.onclick = () => pickStyle(k);
    box.appendChild(b);
  });
  const sl = $("#sliders");
  sl.innerHTML = "";
  REGIONS.forEach((r) => {
    const row = document.createElement("div");
    row.className = "srow";
    row.innerHTML = `<label for="s_${r}">${r}</label><input type="range" id="s_${r}" min="${gmin}" max="${gmax}" step="1"><output class="num" id="o_${r}"></output>`;
    row.querySelector("input").oninput = () => { current = null; markStyle(); preview(); };
    sl.appendChild(row);
  });
  $("#fadeOn").onchange = preview;
  $("#fadeTo").oninput = preview;
  pickStyle(current && styles[current] ? current : Object.keys(styles)[0]);
}
function markStyle() { document.querySelectorAll(".style").forEach((b) => b.classList.toggle("sel", b.dataset.k === current)); }
function pickStyle(k) {
  current = k; markStyle();
  const s = styles[k];
  REGIONS.forEach((r) => ($("#s_" + r).value = s.lengths[r]));
  $("#fadeOn").checked = s.fade_to != null;
  if (s.fade_to != null) $("#fadeTo").value = s.fade_to;
  preview();
}
function preview(len = lengths(), fade = fadeTo()) {
  REGIONS.forEach((r) => { const o = $("#o_" + r); if (o) o.textContent = $("#s_" + r).value + " mm"; });
  const key = JSON.stringify([len, fade]);
  if (key === previewKey) return;
  previewKey = key;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => socket.emit("preview", { lengths: len, fade_to: fade }, (r) => r && r.ok && view.setLengths(r.grid)), 80);
}

// ---------------------------------------------------------------- live state
function chip(el, cls, text) { el.className = "chip " + cls; el.lastChild.textContent = text; }

function render(s) {
  state = s;
  const st = s.state, m = s.machine, live = s.live || {}, loc = s.location, cov = s.coverage || { pct: 0, todo: [] };
  const cutting = st === "CUTTING";
  const stopped = st === "STOPPED";
  if (st === "DONE" && prevState && prevState !== "DONE") showPick = false;
  if (st !== "DONE" && !cutting && !stopped) showPick = true;
  prevState = st;
  const done = st === "DONE" && !showPick;

  $("#pickPanel").hidden = cutting || stopped || done;
  $("#cutPanel").hidden = !cutting;
  $("#donePanel").hidden = !done;
  $("#stopPanel").hidden = !stopped;
  if ((cutting || stopped || done) && s.lengths) preview(s.lengths, s.fade_to);

  const stepIdx = done ? 3 : cutting || stopped ? 2 : ["NOT_HOMED", "HOMING", "IDLE", "CALIBRATING"].includes(st) ? 1 : 0;
  [...$("#steps").children].forEach((d, i) => { d.className = i < stepIdx ? "done" : i === stepIdx ? "cur" : ""; });

  const sensorsOk = m.imu_ok && m.enc_ok;
  chip($("#sensChip"), sensorsOk ? "on" : "hot", sensorsOk ? "Sensors OK" : "Check sensors");
  chip($("#clipChip"), m.clipper ? "hot" : "", m.clipper ? "Clipper on" : "Clipper off");
  const label = { NOT_HOMED: "Setting up", HOMING: "Setting up", IDLE: "Setting up", CALIBRATING: "Calibrating", READY: "Ready",
                  CUTTING: "Cutting", DONE: "Done", STOPPED: "Stopped" }[st] || st;
  chip($("#stateChip"), stopped ? "hot" : ["READY", "DONE", "CUTTING"].includes(st) ? "on" : "warn", label + (s.sim ? " · demo" : ""));

  const canStart = (st === "READY" || st === "DONE") && !s.busy;
  $("#startBtn").disabled = !canStart;
  $("#waitNote").textContent = canStart ? "Sit upright facing forward, press the rollers against your head and squeeze the trigger." :
    st === "CALIBRATING" ? "Calibrating: hold the device at each spot the operator asks for." :
    "Getting HairBarbot ready. You can choose your haircut now.";

  if (cutting) {
    const pct = Math.round(cov.pct * 100);
    $("#pct").textContent = pct + "%";
    $("#ringArc").style.strokeDashoffset = 326.7 * (1 - cov.pct);
    $("#now").textContent = m.clipper && loc ? `Cutting the ${loc.region}` : loc ? `On the ${loc.region}` : "Bring the rollers to your head";
    $("#elapsed").textContent = live.elapsed != null ? `${fmtTime(live.elapsed)} so far` : "";
    const hint = $("#hint");
    hint.hidden = !live.hint || live.block === "trigger";
    hint.textContent = live.hint || "";
    hint.className = "hint" + (live.block === "zone" ? " zone" : "");
    $("#gval").textContent = live.need_guard != null ? `${m.guard.toFixed(1)} mm (needs ${live.need_guard.toFixed(0)})` : `${m.guard.toFixed(1)} mm`;
    $("#gfill").style.width = pctOf(m.guard) + "%";
    $("#gneed").hidden = live.need_guard == null;
    if (live.need_guard != null) $("#gneed").style.left = `calc(${pctOf(live.need_guard)}% - 1px)`;
    $("#todo").innerHTML = cov.todo.length ? cov.todo.map((r) => `<span class="chip warn"><i></i>${r}</span>`).join("") : `<span class="chip on"><i></i>Everything covered</span>`;
    chip($("#trigChip"), m.trigger ? "on" : "", m.trigger ? "Trigger held" : "Trigger released");
    chip($("#contactChip"), live.rolling ? "on" : "", live.rolling ? `Rolling · ${(live.cut_distance / 10).toFixed(0)} cm cut` : "Not rolling");
    chip($("#vacChip"), m.vacuum ? "on" : "", m.vacuum ? "Vacuum on" : "Vacuum off");
  }
  if (done) {
    $("#doneSub").textContent = live.elapsed ? `Finished in ${fmtTime(live.elapsed)}. Check the edges and trim around your ears by hand.` : "Check the edges and trim around your ears by hand.";
    $("#summary").innerHTML = s.lengths ? REGIONS.map((r) => `<div>${r}<b class="num">${s.lengths[r]}</b>mm</div>`).join("") : "";
  }
  if (stopped) $("#stopWhy").textContent = s.message;

  const ev = (s.events || []).slice(-6).reverse();
  $("#feed").innerHTML = ev.length ? ev.map((e) => `<li class="${e.kind}"><time>${clock(e.t)}</time><span>${e.text}</span></li>`).join("") : `<li><time></time><span>Nothing yet.</span></li>`;

  view.update(s);
}

// ---------------------------------------------------------------- socket
socket.on("styles", (j) => { if (Object.keys(styles).length) return; styles = j.styles; gmin = j.guard_min; gmax = j.guard_max; buildPicker(); });
socket.on("state", render);
socket.on("link", (l) => { $("#offline").hidden = l.python; });
socket.on("disconnect", () => { $("#offline").hidden = false; });
socket.on("connect", () => { $("#offline").hidden = true; });

$("#startBtn").onclick = () => cmd("start", { lengths: lengths(), fade_to: fadeTo(), style: current });
$("#finishBtn").onclick = () => cmd("finish");
$("#newBtn").onclick = () => { showPick = true; $("#donePanel").hidden = true; $("#pickPanel").hidden = false; previewKey = ""; preview(); };
$("#stopBtn").onclick = () => cmd("stop");
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" || (e.code === "Space" && e.target === document.body)) { e.preventDefault(); cmd("stop"); }
});
setTimeout(() => ($("#dragHint").hidden = true), 8000);
