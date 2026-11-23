import {
  BufferAttribute, BufferGeometry, Group, Line, LineBasicMaterial,
  PerspectiveCamera, Scene, WebGLRenderer,
} from "three";
import { envelope } from "./envelope.js";

export function mountScope(canvas, frame, audio, reduced) {
  const renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.75));
  const camera = new PerspectiveCamera(42, 1, .1, 50);
  camera.position.set(0, 1.2, 7);
  camera.lookAt(0, 0, 0);

  const scene = new Scene();
  const traces = new Group();
  scene.add(traces);
  const samples = 128;
  for (let index = 0; index < 17; index++) {
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new BufferAttribute(new Float32Array(samples * 3), 3));
    const material = new LineBasicMaterial({
      color: index === 8 ? 0xffede1 : 0xd69a77,
      opacity: index === 8 ? 1 : .36 - Math.abs(index - 8) * .025,
      transparent: true,
    });
    const line = new Line(geometry, material);
    line.frustumCulled = false;
    traces.add(line);
  }

  let visible = false;
  let lost = false;
  let animating = false;
  function draw() {
    const time = audio.currentTime;
    const strength = (envelope[Math.floor(time * 24)] ?? 0) / 100;
    traces.rotation.z = Math.sin(time * .55) * .09;

    for (const [lineIndex, line] of traces.children.entries()) {
      const positions = line.geometry.attributes.position;
      const offset = lineIndex - 8;
      for (let index = 0; index < samples; index++) {
        const x = index / (samples - 1) * 2 - 1;
        const taper = (1 - x * x) ** 2;
        const wave = Math.sin(x * 16 - time * 11 + offset * .34)
          + .32 * Math.cos(x * 31 + time * 8 - offset * .31);
        positions.setXYZ(index, x * 3.5, taper * wave * (.09 + strength * .60), offset * .107);
      }
      positions.needsUpdate = true;
    }
    renderer.render(scene, camera);
  }

  function syncSize() {
    renderer.setSize(frame.clientWidth, frame.clientHeight, false);
    camera.aspect = frame.clientWidth / Math.max(frame.clientHeight, 1);
    camera.updateProjectionMatrix();
  }

  function update() {
    const active = !audio.paused && !audio.ended && visible && !document.hidden && !reduced.matches && !lost;
    if (active === animating) return;
    animating = active;
    canvas.hidden = !active;
    frame.classList.toggle("is-live", active);
    if (active) syncSize();
    renderer.setAnimationLoop(active ? draw : null);
  }

  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    update();
  }).observe(frame);
  new ResizeObserver(() => { if (animating) syncSize(); }).observe(frame);
  for (const event of ["playing", "play", "pause", "ended"]) audio.addEventListener(event, update);
  document.addEventListener("visibilitychange", update);
  reduced.addEventListener("change", update);
  canvas.addEventListener("webglcontextlost", (event) => { event.preventDefault(); lost = true; update(); });
  canvas.addEventListener("webglcontextrestored", () => { lost = false; update(); });
  return update;
}
