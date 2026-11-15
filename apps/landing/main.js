import "@fontsource-variable/space-grotesk/wght.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import { gsap } from "gsap";
import { initialJob, advanceJob, stages } from "./job.js";

const $ = (selector) => document.querySelector(selector);
const reduced = matchMedia("(prefers-reduced-motion: reduce)");
const primary = $("#job-primary");
const secondary = $("#job-secondary");
let job = initialJob;

function renderJob() {
  const stage = stages[job.stage];
  $("#job-label").textContent = stage.label;
  $("#job-title").textContent = stage.title;
  $("#job-copy").textContent = stage.copy;
  primary.firstChild.nodeValue = stage.primary[1] + " ";
  if (stage.secondary) secondary.textContent = stage.secondary[1];
  if (!stage.secondary && document.activeElement === secondary) primary.focus();
  secondary.hidden = !stage.secondary;
  document.querySelectorAll("[data-step]").forEach((step) => {
    if (stage.step === step.dataset.step) step.setAttribute("aria-current", "step");
    else step.removeAttribute("aria-current");
  });
  $("#job-events").replaceChildren(...job.events.map((event, index) => {
    const li = document.createElement("li");
    const count = document.createElement("span");
    count.textContent = String(index + 1).padStart(2, "0");
    li.append(count, document.createTextNode(event));
    return li;
  }));
  if (!reduced.matches) {
    gsap.fromTo("#job-output", { opacity: .45, y: 7 }, {
      opacity: 1, y: 0, duration: .34, ease: "power2.out", overwrite: true,
      clearProps: "opacity,transform",
    });
  }
}

function handleAction(index) {
  const action = (index === 0 ? stages[job.stage].primary : stages[job.stage].secondary)?.[0];
  if (!action) return;
  job = advanceJob(job, action);
  renderJob();
}

$(".job-actions").hidden = false;
primary.addEventListener("click", () => handleAction(0));
secondary.addEventListener("click", () => handleAction(1));

const motion = gsap.matchMedia();
motion.add("(prefers-reduced-motion: no-preference)", (context) => {
  if (!location.hash && scrollY === 0) {
    gsap.fromTo(".hero-copy > *", { y: 14, opacity: .72 }, {
      y: 0, opacity: 1, duration: .56, stagger: .055, ease: "power3.out", clearProps: "opacity,transform",
    });
  }
  const onEnter = context.add(null, (target) => {
    gsap.fromTo(target, { y: 22, opacity: .6 }, {
      y: 0, opacity: 1, duration: .68, ease: "power3.out", clearProps: "opacity,transform",
    });
  });
  const observer = new IntersectionObserver((entries) => {
    for (const { target, isIntersecting } of entries) {
      if (!isIntersecting) continue;
      observer.unobserve(target);
      onEnter(target);
    }
  }, { rootMargin: "0px 0px -35px", threshold: .02 });
  document.querySelectorAll(".reveal").forEach((item) => observer.observe(item));
  return () => observer.disconnect();
});

motion.add("(prefers-reduced-motion: no-preference) and (hover: hover) and (pointer: fine)", () => {
  const hero = $(".hero");
  const moveX = gsap.quickTo(".hero-picture", "x", { duration: .8, ease: "power3.out" });
  const moveY = gsap.quickTo(".hero-picture", "y", { duration: .8, ease: "power3.out" });
  const steer = ({ clientX, clientY }) => {
    const rect = hero.getBoundingClientRect();
    moveX((clientX - rect.left - rect.width / 2) * .025);
    moveY((clientY - rect.top - rect.height / 2) * .022);
  };
  const rest = () => { moveX(0); moveY(0); };
  hero.addEventListener("pointermove", steer);
  hero.addEventListener("pointerleave", rest);
  return () => {
    hero.removeEventListener("pointermove", steer);
    hero.removeEventListener("pointerleave", rest);
  };
});

const film = $("#concept-film");
const voice = $("#voice-audio");
let loadScope;
let scopeFailed = false;

async function showScope() {
  if (reduced.matches || scopeFailed) return;
  try {
    loadScope ??= import("./scope.js").then(({ mountScope }) =>
      mountScope($("#voice-canvas"), $("#voice-visual"), voice, reduced));
    const update = await loadScope;
    update();
  } catch {
    // Playback and the static waveform also work without WebGL.
    scopeFailed = true;
  }
}

film.addEventListener("play", () => voice.pause());
voice.addEventListener("play", () => {
  film.pause();
  void showScope();
});
reduced.addEventListener("change", () => {
  if (!voice.paused) void showScope();
});
