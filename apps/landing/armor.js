import {
  Mesh, OrthographicCamera, PlaneGeometry, Scene, ShaderMaterial, Texture,
  Vector2, WebGLRenderer,
} from "three";

// Silhouette profile in image coordinates. The face projects from the visor
// while the plates sweep back at the ears and taper into the collar.
const profile = [
  [0.08, 0, 0],
  [0.13, .12, .25],
  [0.22, .24, .48],
  [0.34, .30, .56],
  [0.43, .35, .54],
  [0.52, .34, .45],
  [0.62, .27, .40],
  [0.69, .20, .22],
  [0.77, .29, .18],
  [0.87, .46, .10],
  [0.98, .49, 0],
];

function surfaceDepth(u, v) {
  const index = profile.findIndex(([height]) => height > v);
  if (index < 1) return 0;
  const [top, topWidth, topDepth] = profile[index - 1];
  const [bottom, bottomWidth, bottomDepth] = profile[index];
  const blend = (v - top) / (bottom - top);
  const width = topWidth + (bottomWidth - topWidth) * blend;
  const radius = Math.abs(u - .5) / width;
  if (radius >= 1) return 0;
  return (topDepth + (bottomDepth - topDepth) * blend) * (1 - radius * radius) ** 1.35;
}

export async function mountArmor(art, image, canvas, preference) {
  await image.decode();
  const frame = image.parentElement;
  const renderer = new WebGLRenderer({
    canvas, alpha: true, antialias: true, powerPreference: "low-power",
    failIfMajorPerformanceCaveat: true,
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.65));
  const scene = new Scene();
  const camera = new OrthographicCamera(-.75, .75, 1, -1, .1, 20);
  camera.position.z = 4;

  const texture = new Texture(image);
  texture.needsUpdate = true;
  const geometry = new PlaneGeometry(1.5, 2, 120, 160);
  const { position, uv } = geometry.attributes;
  for (let index = 0; index < position.count; index++) {
    position.setZ(index, surfaceDepth(uv.getX(index), 1 - uv.getY(index)));
  }
  const light = new Vector2();
  const material = new ShaderMaterial({
    uniforms: { image: { value: texture }, light: { value: light } },
    vertexShader: `
      varying vec2 imageUv;
      varying float relief;
      void main() {
        imageUv = uv;
        relief = position.z;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform sampler2D image;
      uniform vec2 light;
      varying vec2 imageUv;
      varying float relief;
      void main() {
        vec3 metal = texture2D(image, imageUv).rgb;
        vec2 offset = (imageUv - vec2(0.5, 0.65)) + light * 0.6;
        float sweep = exp(-dot(offset, offset) * 7.0) * length(light);
        float shine = sweep * relief * smoothstep(0.17, 0.7, metal.r);
        gl_FragColor = vec4(metal + shine * vec3(0.20, 0.15, 0.10), 1.0);
      }
    `,
  });
  const helmet = new Mesh(geometry, material);
  scene.add(helmet);

  const target = new Vector2();
  let request = 0;
  let available = true;

  function showArt() {
    const live = available && preference.matches;
    canvas.hidden = !live;
    art.classList.toggle("is-rendered", live);
    art.querySelector("figcaption").hidden = !live;
  }

  function render() {
    request = 0;
    if (!available || !preference.matches || document.hidden) return;
    light.lerp(target, .144);
    helmet.rotation.y = light.x * .37;
    helmet.rotation.x = -light.y * .24;
    helmet.position.x = -light.x * .07;
    renderer.render(scene, camera);
    if (light.distanceToSquared(target) > .00003) schedule();
  }

  function schedule() {
    if (!request) request = requestAnimationFrame(render);
  }

  function resize() {
    renderer.setSize(frame.clientWidth, frame.clientHeight, false);
    schedule();
  }

  function steer(event) {
    if (event.pointerType === "touch") return;
    const { left, top, width, height } = frame.getBoundingClientRect();
    target.set(
      Math.max(-1, Math.min(1, (event.clientX - left) / width * 2 - 1)),
      Math.max(-1, Math.min(1, (event.clientY - top) / height * 2 - 1)),
    );
    schedule();
  }

  function reset() {
    target.set(0, 0);
    schedule();
  }

  frame.addEventListener("pointermove", steer, { passive: true });
  frame.addEventListener("pointerleave", reset);
  preference.addEventListener("change", () => { reset(); showArt(); });
  document.addEventListener("visibilitychange", reset);
  new ResizeObserver(resize).observe(frame);
  canvas.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    available = false;
    showArt();
  });
  canvas.addEventListener("webglcontextrestored", () => {
    available = true;
    resize();
    showArt();
  });
  resize();
  renderer.render(scene, camera);
  showArt();
}
