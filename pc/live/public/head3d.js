// Live 3D head view shared by the client app and the operator dashboard.
// Head frame (same as the Python code): x forward (nose), y to the client's LEFT, z up.
// Three.js frame: X = client's left (screen right when facing the client), Y = up, Z = toward the face.
// 1 three.js unit = 100 mm.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const D2R = Math.PI / 180;
const HAIR_SHORT = new THREE.Color("#d8c4b2");   // short hair: scalp shows through
const HAIR_LONG = new THREE.Color("#2b211c");    // long hair: dark
const UNCUT = new THREE.Color("#3a2c25");        // hair not cut yet
const SKIN = new THREE.Color("#e2bfa4");

export function toThree(yaw, pitch, r) {
  const y = yaw * D2R, p = pitch * D2R;
  const xh = r * Math.sin(p) * Math.cos(y), yh = r * Math.sin(p) * Math.sin(y), zh = r * Math.cos(p);
  return new THREE.Vector3(yh, zh, xh);
}

export function createHeadView(container, { follow = true, gmin = 3, gmax = 40 } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(4.2, 2.6, 6.2);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.45, 0);
  controls.enablePan = false;
  controls.enableDamping = true;
  controls.minDistance = 4;
  controls.maxDistance = 12;
  let lastTouch = 0;
  controls.addEventListener("start", () => { lastTouch = performance.now(); });

  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(3, 6, 5);
  scene.add(key);

  // ---- head (ellipsoid) with per-vertex colors
  const geo = new THREE.SphereGeometry(1, 144, 108);
  const pos = geo.attributes.position;
  const n = pos.count;
  const dirs = new Float32Array(n * 3);
  const yawDeg = new Float32Array(n), pitchDeg = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const X = pos.getX(i), Y = pos.getY(i), Z = pos.getZ(i);
    dirs.set([X, Y, Z], i * 3);
    // three -> head frame: xh = Z, yh = X, zh = Y
    pitchDeg[i] = Math.acos(Math.max(-1, Math.min(1, Y))) / D2R;
    yawDeg[i] = Math.atan2(X, Z) / D2R;
  }
  geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  const headMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85, metalness: 0 });
  const head = new THREE.Mesh(geo, headMat);
  scene.add(head);

  // face cues so the client knows which way is forward
  const skinMat = new THREE.MeshStandardMaterial({ color: SKIN, roughness: 0.8 });
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.3, 20), skinMat);
  const ears = [new THREE.Mesh(new THREE.SphereGeometry(1, 20, 16), skinMat), new THREE.Mesh(new THREE.SphereGeometry(1, 20, 16), skinMat)];
  ears.forEach((e) => { e.scale.set(0.05, 0.27, 0.15); scene.add(e); });
  scene.add(nose);
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.55, 1.4, 32), skinMat);
  neck.position.set(0, -1.15, -0.1);
  scene.add(neck);

  // ---- the machine: arc + carriage + comb tip, rotated by yaw
  const machine = new THREE.Group();
  scene.add(machine);
  const arcPts = [];
  for (let p = -15; p <= 115; p += 2.5) arcPts.push(toThree(0, p, 2.3));
  const arcMat = new THREE.MeshStandardMaterial({ color: 0x9aa7b4, roughness: 0.4, metalness: 0.6, transparent: true, opacity: 0.85 });
  machine.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(arcPts), 80, 0.03, 8, false), arcMat));
  const carriage = new THREE.Mesh(new THREE.BoxGeometry(0.34, 0.16, 0.3), new THREE.MeshStandardMaterial({ color: 0x5b6a78, metalness: 0.5, roughness: 0.4 }));
  machine.add(carriage);
  const slideMat = new THREE.LineBasicMaterial({ color: 0x8899aa });
  const slide = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]), slideMat);
  machine.add(slide);
  const tipMat = new THREE.MeshStandardMaterial({ color: 0xffb020, emissive: 0x000000, roughness: 0.3 });
  const tip = new THREE.Mesh(new THREE.SphereGeometry(0.075, 24, 16), tipMat);
  machine.add(tip);
  const glow = new THREE.Mesh(new THREE.RingGeometry(0.12, 0.17, 40), new THREE.MeshBasicMaterial({ color: 0xff3b30, transparent: true, opacity: 0, side: THREE.DoubleSide }));
  machine.add(glow);

  // current stroke trail
  const trailMat = new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: 0.05, gapSize: 0.04 });
  let trail = null;

  // ---- state
  let hm = { a: 100, b: 78, c: 112 };
  let grid = null;
  let strokes = [];
  let progress = { done: Infinity, curYaw: null, curPitch: null, cutting: false };

  function radius(yaw, pitch) {
    const y = yaw * D2R, p = pitch * D2R;
    const dx = Math.sin(p) * Math.cos(y), dy = Math.sin(p) * Math.sin(y), dz = Math.cos(p);
    return 1 / Math.sqrt((dx / hm.a) ** 2 + (dy / hm.b) ** 2 + (dz / hm.c) ** 2);
  }

  function gridValue(yaw, pitch) {
    if (!grid) return null;
    const ys = grid.yaw_step, ps = grid.pitch_step;
    const fi = pitch / ps, fj = (yaw + 180) / ys;
    const i0 = Math.max(0, Math.min(grid.rows.length - 1, Math.floor(fi)));
    const i1 = Math.min(grid.rows.length - 1, i0 + 1);
    const j0 = Math.max(0, Math.min(grid.rows[0].length - 1, Math.floor(fj)));
    const j1 = Math.min(grid.rows[0].length - 1, j0 + 1);
    const ti = fi - i0, tj = fj - j0;
    const c = [[grid.rows[i0][j0], grid.rows[i0][j1]], [grid.rows[i1][j0], grid.rows[i1][j1]]];
    const near = c[Math.round(ti)][Math.round(tj)];
    if (near == null) return null;
    let sum = 0, w = 0;
    [[0, 0, (1 - ti) * (1 - tj)], [0, 1, (1 - ti) * tj], [1, 0, ti * (1 - tj)], [1, 1, ti * tj]].forEach(([a, b, ww]) => {
      if (c[a][b] != null) { sum += c[a][b] * ww; w += ww; }
    });
    return w ? sum / w : near;
  }

  function isCut(yaw, pitch) {
    if (!isFinite(progress.done)) return true;   // preview mode: show the finished look
    for (let k = 0; k < Math.min(progress.done, strokes.length); k++) {
      if (Math.abs(yaw - strokes[k][0][0]) <= 7.6) return true;
    }
    if (progress.cutting && progress.curYaw != null && Math.abs(yaw - progress.curYaw) <= 7.6 && pitch >= progress.curPitch) return true;
    return false;
  }

  const tmp = new THREE.Color();
  function paint() {
    const col = geo.attributes.color;
    for (let i = 0; i < n; i++) {
      const y = yawDeg[i], p = pitchDeg[i];
      const r = radius(y, p) / 100;
      pos.setXYZ(i, dirs[i * 3] * r, dirs[i * 3 + 1] * r, dirs[i * 3 + 2] * r);
      const v = gridValue(y, Math.min(p, 110));
      if (p > 112 || (v == null && grid)) tmp.copy(SKIN);
      else if (!grid) tmp.copy(UNCUT);
      else if (!isCut(y, p)) tmp.copy(UNCUT);
      else tmp.copy(HAIR_SHORT).lerp(HAIR_LONG, Math.pow((v - gmin) / (gmax - gmin), 0.7));
      col.setXYZ(i, tmp.r, tmp.g, tmp.b);
    }
    pos.needsUpdate = true;
    col.needsUpdate = true;
    geo.computeVertexNormals();
    nose.position.copy(toThree(0, 96, radius(0, 96) / 100 + 0.08));
    nose.rotation.set(Math.PI / 2, 0, 0);
    ears[0].position.copy(toThree(90, 98, radius(90, 98) / 100));
    ears[1].position.copy(toThree(-90, 98, radius(-90, 98) / 100));
  }

  let lastPaintKey = "";
  function maybePaint(force) {
    const key = [hm.a, hm.b, hm.c, grid ? grid.v : 0, progress.done, Math.round(progress.curPitch ?? -1), progress.curYaw, progress.cutting].join("|");
    if (force || key !== lastPaintKey) { lastPaintKey = key; paint(); }
  }

  // ---- public API
  let gridVersion = 0;
  const api = {
    setHead(h) { if (h) { hm = { a: h.a, b: h.b, c: h.c }; maybePaint(); } },
    setLengths(g) { grid = g ? { ...g, v: ++gridVersion } : null; maybePaint(true); },
    setPlan(p) { strokes = (p && p.strokes) || []; if (p && p.head) api.setHead(p.head); maybePaint(true); },
    update(s) {
      if (!s) return;
      const m = s.machine;
      const cutting = s.state === "CUTTING" || s.state === "PAUSED" || s.state === "STOPPED";
      if (s.calibration && s.calibration.head) api.setHead(s.calibration.head);
      if (cutting && strokes.length) {
        progress = { done: s.progress.done, cutting: m.clipper, curYaw: m.clipper ? m.yaw : null, curPitch: m.pitch };
      } else if (s.state === "DONE") {
        progress = { done: Infinity, cutting: false, curYaw: null, curPitch: null };
      } else if (!cutting) {
        progress = { done: Infinity, cutting: false, curYaw: null, curPitch: null };
      }
      maybePaint();
      // machine pose
      machine.visible = !!m.homed;
      machine.rotation.y = m.yaw * D2R;
      const tipR = (s.live && s.live.tip_r != null ? s.live.tip_r : 180) / 100;
      carriage.position.copy(toThree(0, m.pitch, 2.3));
      carriage.lookAt(0, 0, 0);
      tip.position.copy(toThree(0, m.pitch, Math.max(tipR, 0.5)));
      slide.geometry.setFromPoints([carriage.position.clone(), tip.position.clone()]);
      glow.position.copy(toThree(0, m.pitch, Math.max(tipR, 0.5) + 0.01));
      glow.lookAt(carriage.position.clone().multiplyScalar(2));
      tipMat.color.set(m.clipper ? 0xff3b30 : 0xffb020);
      tipMat.emissive.set(m.clipper ? 0x661100 : 0x000000);
      glow.material.opacity = m.clipper ? 0.9 : 0;
      // trail of the current stroke
      if (trail) { scene.remove(trail); trail.geometry.dispose(); trail = null; }
      if (m.clipper && strokes.length && s.progress.done < strokes.length) {
        const st = strokes[s.progress.done];
        const pts = st.filter((w) => w[1] >= m.pitch - 0.5).map((w) => toThree(w[0], w[1], radius(w[0], w[1]) / 100 + 0.03));
        if (pts.length > 1) {
          trail = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), trailMat);
          trail.computeLineDistances();
          scene.add(trail);
        }
      }
      // keep the active area facing the viewer unless they just rotated it themselves
      followYaw = follow && m.clipper && performance.now() - lastTouch > 8000 ? m.yaw : null;
    },
    resize() {
      const w = container.clientWidth, h = container.clientHeight || w;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      // keep the whole head + arc (radius ~2.6 units) in frame for any shape of screen
      const fitR = 2.7, vf = (camera.fov / 2) * D2R, hf = Math.atan(Math.tan(vf) * camera.aspect);
      const dist = fitR / Math.sin(Math.min(vf, hf));
      const off = camera.position.clone().sub(controls.target).setLength(dist);
      camera.position.copy(controls.target).add(off);
      controls.maxDistance = dist * 1.6;
      controls.minDistance = Math.min(dist * 0.6, 4);
      camera.updateProjectionMatrix();
    },
  };

  let followYaw = null;
  const sph = new THREE.Spherical();
  function frame(t) {
    if (followYaw != null) {
      const off = camera.position.clone().sub(controls.target);
      sph.setFromVector3(off);
      const want = followYaw * D2R + 0.5;   // look slightly from the front side of the cutter
      let d = want - sph.theta;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      sph.theta += d * 0.03;
      off.setFromSpherical(sph);
      camera.position.copy(controls.target).add(off);
    }
    const pulse = 1 + 0.15 * Math.sin(t / 120);
    glow.scale.setScalar(pulse);
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  new ResizeObserver(() => api.resize()).observe(container);
  api.resize();
  paint();
  requestAnimationFrame(frame);
  return api;
}

export function lengthColor(v, gmin = 3, gmax = 40) {
  return "#" + HAIR_SHORT.clone().lerp(HAIR_LONG, Math.pow((v - gmin) / (gmax - gmin), 0.7)).getHexString();
}
