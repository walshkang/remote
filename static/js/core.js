// Core: websocket client, state store, theme controller, touch-locked sliders & repeaters.

const listeners = new Map(); // module -> [fn(state, patch)]
const state = {};
let ws, clientId, backoff = 500;

const connEl = document.getElementById("conn");
const connTextEl = document.getElementById("conn-text") || connEl;
const cardsEl = document.getElementById("cards");

/* ==========================================================================
   Theme Controller (Auto / Light / Dark + OS Media Query Sync)
   ========================================================================== */
const THEMES = ["auto", "light", "dark"];
const THEME_META = {
  auto: { icon: "◐", label: "Auto" },
  light: { icon: "☀", label: "Light" },
  dark: { icon: "☾", label: "Dark" },
};

function initTheme() {
  const root = document.documentElement;
  const btn = document.getElementById("theme-toggle");
  const iconEl = document.getElementById("theme-icon");
  const labelEl = document.getElementById("theme-label");
  const metaTheme = document.getElementById("meta-theme-color");
  const mq = window.matchMedia("(prefers-color-scheme: light)");

  let current = localStorage.getItem("remote-theme") || "auto";
  if (!THEMES.includes(current)) current = "auto";

  function applyTheme(mode) {
    current = mode;
    root.setAttribute("data-theme", mode);
    localStorage.setItem("remote-theme", mode);

    const isLight = mode === "light" || (mode === "auto" && mq.matches);
    if (metaTheme) metaTheme.setAttribute("content", isLight ? "#f5f4f0" : "#0b0d11");

    const info = THEME_META[mode];
    if (iconEl) iconEl.textContent = info.icon;
    if (labelEl) labelEl.textContent = info.label;
    if (btn) btn.setAttribute("aria-label", `Theme: ${info.label}. Activate to switch theme.`);
  }

  if (btn) {
    btn.addEventListener("click", () => {
      const next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
      applyTheme(next);
    });
  }
  mq.addEventListener("change", () => {
    if (current === "auto") applyTheme("auto");
  });

  applyTheme(current);
}

initTheme();

/* ==========================================================================
   WebSocket & State Bus
   ========================================================================== */
export function send(module, action, payload = {}) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ module, action, payload }));
  }
}

export function onState(module, fn) {
  if (!listeners.has(module)) listeners.set(module, []);
  listeners.get(module).push(fn);
  if (state[module]) fn(state[module], state[module]);
}

/* ==========================================================================
   Human-Centered Tactile Primitives
   ========================================================================== */

/**
 * Slider that ignores server echoes while the user's finger is on it
 * (and 150ms after), so it never fights the user's thumb.
 * Also syncs `.fill-slider` progress bar and accessible `aria-valuetext`.
 */
export function lockedSlider(input, { onInput, throttleMs = 50, formatValue } = {}) {
  let dragging = false, releaseTimer, throttleTimer, last = 0;
  const wrap = input.closest(".fill-slider");
  const valueEl = wrap ? wrap.querySelector(".fill-slider-value") : null;

  const updateVisualFill = (val) => {
    const min = Number(input.min || 0);
    const max = Number(input.max || 100);
    const clamped = Math.max(min, Math.min(max, Number(val)));
    const pct = max > min ? ((clamped - min) / (max - min)) * 100 : 0;
    if (wrap) wrap.style.setProperty("--fill", `${pct.toFixed(1)}%`);
    if (formatValue) {
      const text = formatValue(clamped);
      input.setAttribute("aria-valuetext", text);
      if (valueEl) valueEl.textContent = text;
    }
  };

  const lock = () => {
    dragging = true;
    clearTimeout(releaseTimer);
  };

  const unlock = () => {
    clearTimeout(releaseTimer);
    releaseTimer = setTimeout(() => { dragging = false; }, 250);
  };

  const emit = (val) => {
    clearTimeout(throttleTimer);
    throttleTimer = null;
    last = performance.now();
    if (onInput) onInput(val);
  };

  input.addEventListener("pointerdown", lock);
  input.addEventListener("pointerup", unlock);
  input.addEventListener("pointercancel", unlock);

  input.addEventListener("touchstart", lock, { passive: true });
  input.addEventListener("touchend", unlock, { passive: true });
  input.addEventListener("touchcancel", unlock, { passive: true });

  input.addEventListener("input", () => {
    lock();
    const v = Number(input.value);
    updateVisualFill(v);

    const now = performance.now();
    const remaining = throttleMs - (now - last);

    if (remaining <= 0) {
      emit(v);
    } else {
      // Trailing edge: guarantees that when you reverse and hold without letting go,
      // the upward/final position is ALWAYS sent!
      clearTimeout(throttleTimer);
      throttleTimer = setTimeout(() => {
        emit(Number(input.value));
      }, remaining);
    }
  });

  input.addEventListener("change", () => {
    clearTimeout(throttleTimer);
    const v = Number(input.value);
    updateVisualFill(v);
    emit(v);
    unlock();
  });

  updateVisualFill(input.value);

  return {
    set(v) {
      if (!dragging && v !== undefined && v !== null) {
        input.value = v;
        updateVisualFill(v);
      }
    },
    get dragging() { return dragging; },
  };
}

/**
 * Press-and-hold repeater for volume/step buttons:
 * Single tap triggers once; holding repeats smoothly after `delay` ms.
 */
export function bindStepRepeat(btn, onStep, { delay = 380, interval = 110 } = {}) {
  let holdTimer = null, repeatTimer = null, pointerActive = false;

  const stop = () => {
    clearTimeout(holdTimer);
    clearInterval(repeatTimer);
    holdTimer = null;
    repeatTimer = null;
  };

  btn.addEventListener("pointerdown", (e) => {
    if (e.button && e.button !== 0) return;
    pointerActive = true;
    onStep();
    stop();
    holdTimer = setTimeout(() => {
      repeatTimer = setInterval(onStep, interval);
    }, delay);
  });

  btn.addEventListener("pointerup", stop);
  btn.addEventListener("pointercancel", stop);
  btn.addEventListener("pointerleave", stop);

  // Keyboard support (Enter / Space) when not triggered by pointer
  btn.addEventListener("click", (e) => {
    if (pointerActive) {
      pointerActive = false;
      return;
    }
    if (e.detail === 0) onStep();
  });
}

function apply(module, patch) {
  state[module] = { ...(state[module] || {}), ...patch };
  const card = document.getElementById(`card-${module}`);
  if (card) card.hidden = false;
  (listeners.get(module) || []).forEach((fn) => fn(state[module], patch));
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => {
    backoff = 500;
    connTextEl.textContent = "Live";
    connEl.classList.remove("off");
  };
  ws.onclose = () => {
    connTextEl.textContent = "Reconnecting…";
    connEl.classList.add("off");
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 5000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") {
      clientId = msg.client_id;
      const activeModules = new Set(Object.keys(msg.state || {}));
      for (const name of MODULE_CARDS) {
        const card = document.getElementById(`card-${name}`);
        if (card) card.hidden = !activeModules.has(name);
      }
      Object.entries(msg.state).forEach(([m, s]) => apply(m, s));
    } else if (msg.type === "state") {
      apply(msg.module, msg.patch);
    } else if (msg.type === "error") {
      console.warn("server error", msg);
    }
  };
}

// Module cards are loaded on demand; add a module by adding a file + name here.
const MODULE_CARDS = ["denon", "hue", "litter_robot", "demo"];
for (const name of MODULE_CARDS) {
  const el = document.createElement("section");
  el.className = "card";
  el.id = `card-${name}`;
  cardsEl.appendChild(el);
  import(`/static/js/modules/${name}.js`).then((m) =>
    m.mount(el, { send, onState, lockedSlider, bindStepRepeat })
  );
}

connect();
