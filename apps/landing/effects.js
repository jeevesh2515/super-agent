const backgroundSource = new URL("./media/armor-loop.mp4", import.meta.url).href;

export function backgroundMotion(section, video, button, reduced) {
  let choice = null;
  let visible = false;
  let playRequest = 0;
  let playing = false;

  function label() {
    button.textContent = playing ? "Pause background motion" : "Play background motion";
  }

  async function sync() {
    const request = ++playRequest;
    const shouldPlay = (choice ?? !reduced.matches) && visible && !document.hidden;
    if (!shouldPlay) {
      video.pause();
      playing = false;
      label();
      return;
    }
    if (!video.hasAttribute("src")) video.src = backgroundSource;
    try {
      await video.play();
      if (request !== playRequest) return;
      playing = true;
      video.dataset.ready = "";
    } catch {
      if (request !== playRequest) return;
      playing = false;
    }
    label();
  }

  new IntersectionObserver(([entry]) => {
    visible = entry.isIntersecting;
    void sync();
  }, { threshold: .1 }).observe(section);
  document.addEventListener("visibilitychange", sync);
  reduced.addEventListener("change", () => {
    choice = null;
    void sync();
  });
  button.addEventListener("click", () => {
    choice = !playing;
    void sync();
  });
  button.hidden = false;
}

export function interfaceSound(button, mediaPlaying) {
  const Audio = window.AudioContext ?? window.webkitAudioContext;
  if (!Audio) return;
  let context;
  let last = -1;

  function tone(hover = false) {
    if (button.getAttribute("aria-pressed") !== "true" || context.state !== "running" || mediaPlaying()) return;
    const time = context.currentTime;
    if (time - last < (hover ? .12 : .03)) return;
    last = time;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const duration = hover ? .045 : .09;
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(hover ? 420 : 620, time);
    oscillator.frequency.exponentialRampToValueAtTime(hover ? 220 : 320, time + duration);
    gain.gain.setValueAtTime(.0003, time);
    gain.gain.exponentialRampToValueAtTime(hover ? .028 : .065, time + .009);
    gain.gain.exponentialRampToValueAtTime(.0003, time + duration);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(time);
    oscillator.stop(time + duration);
  }

  button.addEventListener("click", async () => {
    if (button.getAttribute("aria-pressed") === "true") {
      button.setAttribute("aria-pressed", "false");
      return;
    }
    try {
      context ??= new Audio();
      await context.resume();
      if (context.state !== "running") return;
      button.setAttribute("aria-pressed", "true");
      tone();
    } catch {
      button.setAttribute("aria-pressed", "false");
    }
  });
  document.querySelectorAll("[data-sound], .job-actions button, .questions summary").forEach((control) => {
    control.addEventListener("pointerenter", (event) => { if (event.pointerType === "mouse") tone(true); });
    control.addEventListener("click", () => tone());
  });
  button.hidden = false;
}
