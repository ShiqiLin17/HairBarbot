// Live 3D head view shared by the client app and the operator dashboard (handheld HairBarbot with rollers).
// Head frame (same as the Python code): x forward (nose), y to the client's LEFT, z up.
// Three.js frame: X = client's left, Y = up, Z = toward the face. 1 three.js unit = 100 mm.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const D2R = Math.PI / 180;
const HAIR_SHORT = new THREE.Color("#d8c4b2");   // short hair: scalp shows through
const HAIR_LONG = new THREE.Color("#2b211c");    // long hair: dark
const UNCUT = new THREE.Color("#3a2c25");        // hair not cut yet
const SKIN = new THREE.Color("#e2bfa4");
const HEAD = { a: 100, b: 78, c: 112 };          // ellipsoid half-sizes in mm (front/back, side, top)

export function toThree(yaw, pitch, r) {
  const y = yaw * D2R, p = pitch * D2R;
  const xh = r * Math.sin(p) * Math.cos(y), yh = r * Math.sin(p) * Math.sin(y), zh = r * Math.cos(p);
  return new THREE.Vector3(yh, zh, xh);
}

function radius(yaw, pitch) {
  const y = yaw * D2R, p = pitch * D2R;
  const dx = Math.sin(p) * Math.cos(y), dy = Math.sin(p) * Math.sin(y), dz = Math.cos(p);
  return 1 / Math.sqrt((dx / HEAD.a) ** 2 + (dy / HEAD.b) ** 2 + (dz / HEAD.c) ** 2);
}

function gridLookup(grid, yaw, pitch, smooth) {
  if (!grid) return null;
  const ys = grid.yaw_step, ps = grid.pitch_step, rows = grid.rows;
  const fi = Math.max(0, Math.min(rows.length - 1, pitch / ps));
  const fj = Math.max(0, Math.min(rows[0].length - 1, (yaw + 180) / ys));
  if (!smooth) return rows[Math.round(fi)][Math.round(fj)];
  const i0 = Math.floor(fi), i1 = Math.min(rows.length - 1, i0 + 1), j0 = Math.floor(fj), j1 = Math.min(rows[0].length - 1, j0 + 1);
  const ti = fi - i0, tj = fj - j0;
  if (rows[Math.round(fi)][Math.round(fj)] == null) return null;
  let sum = 0, w = 0;
  [[i0, j0, (1 - ti) * (1 - tj)], [i0, j1, (1 - ti) * tj], [i1, j0, ti * (1 - tj)], [i1, j1, ti * tj]].forEach(([a, b, ww]) => {
    const v = rows[a][b];
    if (v != null) { sum += v * ww; w += ww; }
  });
  return w ? sum / w : null;
}

export function createHeadView(container, { follow = true, gmin = 3, gmax = 60 } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(3.4, 2.4, 4.6);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0.2, 0);
  controls.enablePan = false;
  controls.enableDamping = true;
  let lastTouch = 0;
  controls.addEventListener("start", () => { lastTouch = performance.now(); });

  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(3, 6, 5);
  scene.add(key);

  // ---- head with per-vertex colors
  const geo = new THREE.SphereGeometry(1, 144, 108);
  const pos = geo.attributes.position;
  const n = pos.count;
  const yawDeg = new Float32Array(n), pitchDeg = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const X = pos.getX(i), Y = pos.getY(i), Z = pos.getZ(i);
    pitchDeg[i] = Math.acos(Math.max(-1, Math.min(1, Y))) / D2R;
    yawDeg[i] = Math.atan2(X, Z) / D2R;
    const r = radius(yawDeg[i], pitchDeg[i]) / 100;
    pos.setXYZ(i, X * r, Y * r, Z * r);
  }
  geo.computeVertexNormals();
  geo.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85 })));

  const skinMat = new THREE.MeshStandardMaterial({ color: SKIN, roughness: 0.8 });
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.11, 0.3, 20), skinMat);
  nose.position.copy(toThree(0, 96, radius(0, 96) / 100 + 0.08));
  nose.rotation.set(Math.PI / 2, 0, 0);
  scene.add(nose);
  [90, -90].forEach((yw) => {
    const e = new THREE.Mesh(new THREE.SphereGeometry(1, 20, 16), skinMat);
    e.scale.set(0.05, 0.27, 0.15);
    e.position.copy(toThree(yw, 98, radius(yw, 98) / 100));
    scene.add(e);
  });
  const neck = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.55, 1.4, 32), skinMat);
  neck.position.set(0, -1.15, -0.1);
  scene.add(neck);

  // ---- the handheld device: two rollers on the moving carriage, Flowbee head, handle with hose
  const clipper = new THREE.Group();
  const bodyMat = new THREE.MeshStandardMaterial({ color: 0xf2f2f2, roughness: 0.5 });
  const accentMat = new THREE.MeshStandardMaterial({ color: 0xffb020, roughness: 0.35, emissive: 0x000000 });
  const comb = new THREE.Group();   // rollers + carriage plate
  [-0.15, 0.15].forEach((x) => {
    const roller = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 0.09, 20), accentMat);
    roller.rotation.x = Math.PI / 2;
    roller.position.set(x, 0.06, 0);
    comb.add(roller);
  });
  const plate = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.03, 0.16), accentMat);
  plate.position.y = 0.13;
  comb.add(plate);
  const headPart = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.22, 0.32, 32), bodyMat);
  const collar = new THREE.Mesh(new THREE.CylinderGeometry(0.235, 0.235, 0.07, 32), new THREE.MeshStandardMaterial({ color: 0x2b6f9f, roughness: 0.4 }));
  const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.5, 20), bodyMat);
  const hose = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.6, 16), new THREE.MeshStandardMaterial({ color: 0x8a96a3, roughness: 0.7 }));
  [comb, headPart, collar, handle, hose].forEach((m) => clipper.add(m));
  const glow = new THREE.Mesh(new THREE.RingGeometry(0.24, 0.3, 48), new THREE.MeshBasicMaterial({ color: 0xff3b30, transparent: true, opacity: 0, side: THREE.DoubleSide }));
  glow.rotation.x = Math.PI / 2;
  clipper.add(glow);
  scene.add(clipper);
  clipper.visible = false;
  function layoutClipper(guardMm) {
    const g = Math.max(0.03, guardMm / 100);   // comb sits `guard` mm out from the blade
    comb.position.y = 0.0;
    glow.position.y = 0.0;
    headPart.position.y = g + 0.16;
    collar.position.y = g + 0.2;
    handle.position.y = g + 0.57;
    hose.position.set(0.15, g + 0.6, 0);
    hose.rotation.z = -0.5;
  }
  layoutClipper(20);

  // ---- state
  let lengthsGrid = null;   // hair length everywhere (preview)
  let cover = null;         // coverage grid (1 = cut)
  let showFinished = true;  // before/after a session: show the finished look everywhere

  const tmp = new THREE.Color();
  function paint() {
    const col = geo.attributes.color;
    for (let i = 0; i < n; i++) {
      const y = yawDeg[i], p = pitchDeg[i];
      const v = p <= 112 ? gridLookup(lengthsGrid, y, Math.min(p, 110), true) : null;
      if (p > 112 || (lengthsGrid && v == null)) tmp.copy(SKIN);
      else if (!lengthsGrid) tmp.copy(UNCUT);
      else if (!showFinished && !(cover && gridLookup(cover, y, p, false) === 1)) tmp.copy(UNCUT);
      else tmp.copy(HAIR_SHORT).lerp(HAIR_LONG, Math.pow((v - gmin) / (gmax - gmin), 0.7));
      col.setXYZ(i, tmp.r, tmp.g, tmp.b);
    }
    col.needsUpdate = true;
  }
  let paintKey = "";
  function maybePaint() {
    const k = (lengthsGrid ? lengthsGrid.v : 0) + "|" + showFinished + "|" + (cover ? cover.key : "");
    if (k !== paintKey) { paintKey = k; paint(); }
  }

  let followYaw = null;
  let gridV = 0;
  const api = {
    setLengths(g) { lengthsGrid = g ? { ...g, v: ++gridV } : null; maybePaint(); },
    update(s) {
      if (!s) return;
      const m = s.machine, loc = s.location;
      const session = s.state === "CUTTING" || (s.state === "STOPPED" && s.coverage && s.coverage.pct > 0);
      showFinished = !session;
      if (s.coverage && session) {
        cover = { ...s.coverage, key: s.coverage.rows.map((r) => r.join("")).join("") };
      }
      maybePaint();
      clipper.visible = !!loc;
      if (loc) {
        const r = radius(loc.yaw, loc.pitch) / 100;
        const normal = toThree(loc.yaw, loc.pitch, 1).normalize();
        clipper.position.copy(toThree(loc.yaw, loc.pitch, r));
        clipper.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal);
        layoutClipper(m.guard);
        accentMat.color.set(m.clipper ? 0xff3b30 : (loc.in_zone ? 0xffb020 : 0x888888));
        accentMat.emissive.set(m.clipper ? 0x661100 : 0x000000);
        glow.material.opacity = m.clipper ? 0.9 : 0;
      }
      followYaw = follow && loc && s.state === "CUTTING" && performance.now() - lastTouch > 8000 ? loc.yaw : null;
    },
    resize() {
      const w = container.clientWidth, h = container.clientHeight || w;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      const fitR = 2.0, vf = (camera.fov / 2) * D2R, hf = Math.atan(Math.tan(vf) * camera.aspect);
      const dist = fitR / Math.sin(Math.min(vf, hf));
      const off = camera.position.clone().sub(controls.target).setLength(dist);
      camera.position.copy(controls.target).add(off);
      controls.maxDistance = dist * 1.6;
      controls.minDistance = Math.min(dist * 0.6, 3);
      camera.updateProjectionMatrix();
    },
  };

  const sph = new THREE.Spherical();
  function frame(t) {
    if (followYaw != null) {
      const off = camera.position.clone().sub(controls.target);
      sph.setFromVector3(off);
      let d = followYaw * D2R + 0.4 - sph.theta;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      sph.theta += d * 0.03;
      off.setFromSpherical(sph);
      camera.position.copy(controls.target).add(off);
    }
    glow.scale.setScalar(1 + 0.15 * Math.sin(t / 120));
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

export function lengthColor(v, gmin = 3, gmax = 60) {
  return "#" + HAIR_SHORT.clone().lerp(HAIR_LONG, Math.pow((v - gmin) / (gmax - gmin), 0.7)).getHexString();
}
