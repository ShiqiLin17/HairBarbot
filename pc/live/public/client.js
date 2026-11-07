// HairBarbot client app: what the client sees on the tablet while their hair is cut.
import { createHeadView, lengthColor } from "./head3d.js";

const $ = (s) => document.querySelector(s);
const REGIONS = ["top", "front", "sides", "back", "nape"];
const socket = io();
let styles = {}, gmin = 3, gmax = 40, current = "classic", state = null, plan = null;
let showPick = true;          // false while showing the "All done" card
let prevState = null;
let previewKey = "", previewTimer = null;

const view = createHeadView($("#view"));
$("#legendBar").style.background = `linear-gradient(90deg, ${lengthColor(3)}, ${lengthColor(40)})`;

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

// ---------------------------------------------------------------- render live state
function render(s) {
  state = s;
  const st = s.state, m = s.machine, live = s.live || {};
  const cutting = st === "CUTTING" || st === "PAUSED";
  const stopped = st === "STOPPED";
  if (st === "DONE" && prevState !== "DONE") showPick = false;   // just finished: show "All done"
  if (st !== "DONE" && !cutting && !stopped) showPick = true;
  prevState = st;
  const done = st === "DONE" && !showPick;

  // which panel
  $("#pickPanel").hidden = cutting || stopped || done;
  $("#cutPanel").hidden = !cutting;
  $("#donePanel").hidden = !done;
  $("#stopPanel").hidden = !stopped;

  // while a haircut is running, show ITS lengths on the head (not the sliders)
  if ((cutting || stopped || done) && s.lengths) preview(s.lengths, s.fade_to);

  // step tracker
  const stepIdx = done ? 3 : cutting || stopped ? 2 : st === "CALIBRATING" ? 1 : 0;
  [...$("#steps").children].forEach((d, i) => { d.className = i < stepIdx ? "done" : i === stepIdx ? "cur" : ""; });

  // header chips
  const t = s.tracker || {};
  const steady = $("#steadyChip");
  steady.className = "chip " + (t.ok ? "on" : cutting ? "hot" : "");
  steady.lastChild.textContent = t.ok ? "Head steady" : t.face === false ? "Face not visible" : "Head check";
  const clip = $("#clipChip");
  clip.className = "chip " + (m.clipper ? "hot" : "");
  clip.lastChild.textContent = m.clipper ? "Clipper on" : "Clipper off";
  const sc = $("#stateChip");
  const label = { NOT_HOMED: "Setting up", HOMING: "Setting up", IDLE: "Getting ready", CALIBRATING: "Fitting", READY: "Ready",
                  CUTTING: "Cutting", PAUSED: "Paused", DONE: "Done", STOPPED: "Stopped" }[st] || st;
  sc.className = "chip " + (stopped ? "hot" : st === "READY" || st === "DONE" || cutting ? "on" : "warn");
  sc.lastChild.textContent = label + (s.sim ? " · demo" : "");

  // choose panel
  const canStart = (st === "READY" || st === "DONE") && !s.busy;
  $("#startBtn").disabled = !canStart;
  $("#waitNote").textContent = canStart ? "Sit back, rest your chin, and hold the red button in your hand." :
    st === "CALIBRATING" ? "Your barber is fitting the machine to your head. Keep still." :
    "Your barber is getting the machine ready. You can choose your haircut now.";

  // cutting panel
  if (cutting) {
    const p = s.progress, pct = p.total ? Math.round((100 * p.done) / p.total) : 0;
    $("#pct").textContent = pct + "%";
    $("#strokes").textContent = `${p.done} / ${p.total} passes`;
    $("#ringArc").style.strokeDashoffset = 326.7 * (1 - pct / 100);
    $("#eta").textContent = live.eta_s != null ? (live.eta_s < 60 ? "Almost done" : `About ${Math.ceil(live.eta_s / 60)} min left`) : "Starting…";
    $("#elapsed").textContent = live.elapsed != null ? `${fmtTime(live.elapsed)} so far` : "";
    $("#now").innerHTML = st === "PAUSED" ? "Paused" :
      m.clipper && live.region ? `Trimming the <span>${live.region}</span> · ${m.guard.toFixed(0)} mm` : "Moving to the next section";
    $("#cutMsg").textContent = st === "PAUSED" ? "The arm has moved away. Press Resume when you're ready." : "Keep your head still and your chin on the rest.";
    const vac = $("#vacChip"); vac.className = "chip " + (m.vacuum ? "on" : ""); vac.lastChild.textContent = m.vacuum ? "Vacuum on" : "Vacuum off";
    const gc = $("#guardChip"); gc.className = "chip on"; gc.lastChild.textContent = `Guard ${m.guard.toFixed(1)} mm`;
    $("#pauseBtn").textContent = st === "PAUSED" ? "Resume" : "Pause";
  }
  if (done) {
    $("#doneSub").textContent = live.elapsed ? `Finished in ${fmtTime(live.elapsed)}. Have a look in the mirror.` : "Have a look in the mirror.";
    $("#summary").innerHTML = s.lengths ? REGIONS.map((r) => `<div>${r}<b class="num">${s.lengths[r]}</b>mm</div>`).join("") : "";
  }
  if (stopped) $("#stopWhy").textContent = s.message;

  // activity feed
  const ev = (s.events || []).slice(-6).reverse();
  $("#feed").innerHTML = ev.length ? ev.map((e) => `<li class="${e.kind}"><time>${clock(e.t)}</time><span>${e.text}</span></li>`).join("") : `<li><time></time><span>Nothing yet.</span></li>`;

  view.update(s);
}

// ---------------------------------------------------------------- socket events
socket.on("styles", (j) => { if (Object.keys(styles).length) return; styles = j.styles; gmin = j.guard_min; gmax = j.guard_max; buildPicker(); });
socket.on("plan", (p) => { plan = p; view.setPlan(p); });
socket.on("state", render);
socket.on("link", (l) => { $("#offline").hidden = l.python; });
socket.on("disconnect", () => { $("#offline").hidden = false; });
socket.on("connect", () => { $("#offline").hidden = true; });

// ---------------------------------------------------------------- buttons
$("#startBtn").onclick = () => cmd("cut", { lengths: lengths(), fade_to: fadeTo(), style: current });
$("#pauseBtn").onclick = () => cmd(state && state.state === "PAUSED" ? "resume" : "pause");
$("#newBtn").onclick = () => { showPick = true; $("#donePanel").hidden = true; $("#pickPanel").hidden = false; previewKey = ""; preview(); };
$("#stopBtn").onclick = () => cmd("stop");
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" || (e.code === "Space" && e.target === document.body)) { e.preventDefault(); cmd("stop"); }
});
setTimeout(() => ($("#hint").hidden = true), 8000);
