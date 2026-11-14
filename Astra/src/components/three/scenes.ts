// 3D models for the overview. The body is a bundled glTF file served with the app, so
// nothing is fetched from the internet; the station and the fallback body are built in
// code. This module holds three.js and is only ever loaded lazily.
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import {
  AmbientLight, Box3, BoxGeometry, CapsuleGeometry, Color, CylinderGeometry, DirectionalLight, DoubleSide, Group, HemisphereLight,
  Mesh, MeshBasicMaterial, MeshStandardMaterial, Object3D, PerspectiveCamera, Raycaster, RingGeometry, Scene, SphereGeometry, Vector3, WebGLRenderer,
} from 'three';
import type { Domain, Status } from '../../types';

export type Statuses = Partial<Record<Domain, Status>>;
export interface MarkerHit {
  domain: Domain;
  /** Marker centre in canvas pixels. */
  x: number;
  y: number;
}
export interface Mounted {
  setStatuses?: (s: Statuses) => void;
  /** The marker nearest a point in canvas pixels, if one is within reach. */
  markerAt?: (x: number, y: number) => MarkerHit | null;
  setActive: (visible: boolean) => void;
  dispose: () => void;
}

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function stage(canvas: HTMLCanvasElement, fov: number, camera: Vector3, target: Vector3, frame: (t: number, still: boolean) => void, scene: Scene): Mounted & { camera: PerspectiveCamera } {
  const renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const cam = new PerspectiveCamera(fov, 1, 0.1, 50);
  cam.position.copy(camera);
  cam.lookAt(target);

  const size = () => {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    cam.aspect = w / h;
    cam.updateProjectionMatrix();
  };
  const still = reducedMotion();
  const draw = (ms: number) => {
    frame(ms / 1000, still);
    renderer.render(scene, cam);
  };
  const observer = new ResizeObserver(() => {
    size();
    draw(performance.now());
  });
  observer.observe(canvas);
  size();
  draw(0);

  return {
    camera: cam,
    // Animate only while on screen; with reduced motion, draw single frames instead.
    setActive: (visible) => renderer.setAnimationLoop(visible && !still ? draw : null),
    dispose: () => {
      observer.disconnect();
      renderer.setAnimationLoop(null);
      scene.traverse((o: Object3D) => {
        const m = o as Mesh;
        if (!m.isMesh) return;
        m.geometry.dispose();
        (Array.isArray(m.material) ? m.material : [m.material]).forEach((x) => x.dispose());
      });
      renderer.dispose();
    },
  };
}

const v = (x: number, y: number, z = 0) => new Vector3(x, y, z);

/** A capsule running between two points. */
function limb(a: Vector3, b: Vector3, r: number, mat: MeshStandardMaterial) {
  const dir = b.clone().sub(a);
  const mesh = new Mesh(new CapsuleGeometry(r, dir.length(), 6, 16), mat);
  mesh.position.copy(a).addScaledVector(dir, 0.5);
  mesh.quaternion.setFromUnitVectors(v(0, 1), dir.normalize());
  return mesh;
}

// The figure is fitted to this frame: feet at FLOOR, top of the head at FLOOR + HEIGHT.
const FLOOR = -1.53;
const HEIGHT = 3.26;

// Marker positions in that frame. z is where the mannequin's surface is; on the
// anatomical model it is replaced by a raycast onto the front of the body.
const spots: { domain: Domain; at: Vector3 }[] = [
  { domain: 'sleep-behaviour', at: v(0, 1.5, 0.2) },
  { domain: 'cardiovascular', at: v(0.09, 0.85, 0.17) },
  { domain: 'immune-symptoms', at: v(0, 0.4, 0.17) },
  { domain: 'musculoskeletal', at: v(-0.17, -0.5, 0.12) },
];

// "Anatomy study 2.0 Basemesh Human Male Body" by zeroran, CC BY 4.0, simplified for size.
// Credited on the Data and sync screen.
const BODY_URL = `${import.meta.env.BASE_URL}models/body.glb`;

/** Loads the anatomical body, recolours it, fits it to the frame and turns it to face the camera. */
async function anatomicalFigure(skin: MeshStandardMaterial) {
  const gltf = await new GLTFLoader().loadAsync(BODY_URL);
  const model = gltf.scene;
  model.traverse((o: Object3D) => {
    const m = o as Mesh;
    if (m.isMesh) m.material = skin;
  });
  const box = new Box3().setFromObject(model);
  const size = box.getSize(v(0, 0));
  model.scale.setScalar(HEIGHT / size.y);
  box.setFromObject(model);
  const centre = box.getCenter(v(0, 0));
  model.position.set(-centre.x, FLOOR - box.min.y, -centre.z);

  const figure = new Group();
  figure.add(model);
  figure.updateMatrixWorld(true);
  // The nose sticks out further than the back of the head, which tells us which way it faces.
  const eye = FLOOR + HEIGHT * 0.93;
  if (surfaceDepth(figure, 0, eye, 1) < surfaceDepth(figure, 0, eye, -1)) {
    figure.rotation.y = Math.PI;
    figure.updateMatrixWorld(true);
  }
  return figure;
}

/** How far the body's surface reaches towards +z (side 1) or -z (side -1) at (x, y); 0 on a miss. */
function surfaceDepth(figure: Object3D, x: number, y: number, side: 1 | -1) {
  const ray = new Raycaster(v(x, y, side * 10), v(0, 0, -side));
  const hit = ray.intersectObject(figure, true)[0];
  return hit ? Math.abs(hit.point.z) : 0;
}

/** Simple capsule figure, used only if the model file can't be loaded. */
function mannequin(skin: MeshStandardMaterial) {
  const body = new Group();
  const head = new Mesh(new SphereGeometry(0.21, 32, 24), skin);
  head.position.set(0, 1.52, 0);
  head.scale.set(0.9, 1.08, 0.95);
  const torso = limb(v(0, 0.98), v(0, 0.42), 0.27, skin);
  torso.scale.set(1.12, 1, 0.68);
  const pelvis = limb(v(-0.1, 0.12), v(0.1, 0.12), 0.2, skin);
  pelvis.scale.z = 0.85;
  body.add(
    head, torso, pelvis,
    limb(v(0, 1.3), v(0, 1.14), 0.085, skin),
    limb(v(-0.31, 1.06), v(0.31, 1.06), 0.1, skin),
    limb(v(0, 0.42), v(0, 0.14), 0.2, skin),
  );
  for (const s of [-1, 1]) {
    body.add(
      limb(v(s * 0.36, 1.05), v(s * 0.46, 0.55, 0.01), 0.075, skin),
      limb(v(s * 0.46, 0.55, 0.01), v(s * 0.52, 0.1, 0.06), 0.06, skin),
      limb(v(s * 0.53, 0.05, 0.07), v(s * 0.54, -0.06, 0.08), 0.055, skin),
      limb(v(s * 0.15, 0.02), v(s * 0.18, -0.68, 0.01), 0.115, skin),
      limb(v(s * 0.18, -0.68, 0.01), v(s * 0.2, -1.36, -0.02), 0.085, skin),
      limb(v(s * 0.2, -1.47, 0), v(s * 0.21, -1.47, 0.16), 0.06, skin),
    );
  }
  return body;
}

export async function mountBody(canvas: HTMLCanvasElement, initial: Statuses): Promise<Mounted> {
  const css = getComputedStyle(document.documentElement);
  const colour: Record<Status, Color> = {
    normal: new Color(css.getPropertyValue('--normal').trim()),
    watch: new Color(css.getPropertyValue('--watch').trim()),
    review: new Color(css.getPropertyValue('--review').trim()),
  };

  const scene = new Scene();
  scene.add(new HemisphereLight(0x9cc6ff, 0x061020, 1.5));
  const key = new DirectionalLight(0xffffff, 2);
  key.position.set(2, 3, 4);
  const rim = new DirectionalLight(0x4f9bff, 3);
  rim.position.set(-3, 1, -3);
  scene.add(key, rim);

  const skin = new MeshStandardMaterial({ color: 0x3f7fd0, roughness: 0.42, metalness: 0.15 });
  const body = new Group();
  let anatomical = true;
  let figure: Object3D;
  try {
    figure = await anatomicalFigure(skin);
  } catch (e) {
    console.warn('Body model file unavailable, using the simple figure', e);
    anatomical = false;
    figure = mannequin(skin);
  }
  body.add(figure);

  // Markers draw over the body so they stay readable as it turns.
  const markers = spots.map(({ domain, at }) => {
    const dot = new Mesh(new SphereGeometry(0.052, 16, 12), new MeshBasicMaterial({ depthTest: false, toneMapped: false }));
    const ring = new Mesh(new RingGeometry(0.075, 0.1, 32), new MeshBasicMaterial({ depthTest: false, transparent: true, side: DoubleSide, toneMapped: false }));
    // Sit each marker just in front of the anatomical body's surface.
    const z = anatomical ? surfaceDepth(figure, at.x, at.y, 1) : 0;
    const pos = z > 0 ? v(at.x, at.y, z + 0.03) : at;
    dot.position.copy(pos);
    ring.position.copy(pos);
    dot.renderOrder = 2;
    ring.renderOrder = 2;
    body.add(dot, ring);
    return { domain, dot, ring };
  });

  const paint = (statuses: Statuses) => {
    for (const m of markers) {
      const st = statuses[m.domain] ?? 'normal';
      (m.dot.material as MeshBasicMaterial).color.copy(colour[st]);
      (m.ring.material as MeshBasicMaterial).color.copy(colour[st]);
      m.ring.visible = st !== 'normal';
    }
  };
  paint(initial);
  scene.add(body);

  const mounted = stage(canvas, 30, v(0, 0.08, 6.5), v(0, 0.03), (t, still) => {
    // A slow sway rather than a spin, so the markers stay on the visible side.
    body.rotation.y = still ? -0.25 : Math.sin(t * 0.45) * 0.3;
    const phase = still ? 0.35 : (t * 0.45) % 1;
    for (const { ring } of markers) {
      ring.scale.setScalar(0.8 + phase * 0.9);
      (ring.material as MeshBasicMaterial).opacity = 0.75 * (1 - phase);
    }
  }, scene);
  const { camera, ...rest } = mounted;
  const markerAt = (x: number, y: number): MarkerHit | null => {
    const reach = 22;
    let best: MarkerHit | null = null;
    let bestDist = reach;
    for (const { domain, dot } of markers) {
      const p = dot.getWorldPosition(v(0, 0)).project(camera);
      const sx = ((p.x + 1) / 2) * canvas.clientWidth;
      const sy = ((1 - p.y) / 2) * canvas.clientHeight;
      const dist = Math.hypot(sx - x, sy - y);
      if (dist < bestDist) {
        bestDist = dist;
        best = { domain, x: sx, y: sy };
      }
    }
    return best;
  };
  return { ...rest, setStatuses: paint, markerAt };
}

export function mountStation(canvas: HTMLCanvasElement): Mounted {
  const scene = new Scene();
  scene.add(new AmbientLight(0x6f8fc0, 1.1));
  const sun = new DirectionalLight(0xffffff, 3.2);
  sun.position.set(3, 3, 4);
  scene.add(sun);

  const hull = new MeshStandardMaterial({ color: 0xd5dde8, roughness: 0.5, metalness: 0.45 });
  const truss = new MeshStandardMaterial({ color: 0x8796ab, roughness: 0.6, metalness: 0.6 });
  const solar = new MeshStandardMaterial({ color: 0x1c4fa3, emissive: 0x0a2558, roughness: 0.25, metalness: 0.75 });
  const station = new Group();
  const part = (m: Mesh, x = 0, y = 0, rotZ = 0) => {
    m.position.set(x, y, 0);
    m.rotation.z = rotZ;
    station.add(m);
  };
  part(new Mesh(new CylinderGeometry(0.17, 0.17, 1.3, 20), hull), 0, 0, Math.PI / 2);
  part(new Mesh(new SphereGeometry(0.2, 20, 14), hull));
  part(new Mesh(new CylinderGeometry(0.13, 0.13, 0.55, 18), hull), 0, 0.36);
  part(new Mesh(new BoxGeometry(0.06, 3.1, 0.06), truss));
  for (const y of [-1, 1]) {
    for (const x of [-1, 1]) {
      for (const d of [0.72, 1.28]) part(new Mesh(new BoxGeometry(0.34, 0.52, 0.015), solar), x * 0.22, y * d);
    }
    part(new Mesh(new BoxGeometry(0.62, 0.025, 0.025), truss), 0, y);
  }
  station.rotation.set(0.45, 0.5, 0.95);
  scene.add(station);

  return stage(canvas, 30, v(0, 0, 8), v(0, 0), (t, still) => {
    station.rotation.y = still ? 0.5 : 0.5 + t * 0.12;
  }, scene);
}
