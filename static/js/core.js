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
/**
 * Slider that ignores server echoes while the user's finger is on it
 * (and 150ms after), so it never fights the user's thumb.
 * Also syncs `.fill-slider` progress bar, accessible `aria-valuetext`,
 * and a floating thumb bubble so the finger never obscures the value.
 */
export function lockedSlider(input, { onInput, throttleMs = 50, formatValue } = {}) {
  let dragging = false, releaseTimer, throttleTimer, last = 0;
  const wrap = input.closest(".fill-slider");
  const valueEl = wrap ? wrap.querySelector(".fill-slider-value") : null;

  // Create floating thumb bubble if not already present
  let bubbleEl = wrap ? wrap.querySelector(".fill-slider-bubble") : null;
  if (wrap && !bubbleEl) {
    bubbleEl = document.createElement("div");
    bubbleEl.className = "fill-slider-bubble";
    bubbleEl.setAttribute("aria-hidden", "true");
    wrap.appendChild(bubbleEl);
  }

  const updateVisualFill = (val) => {
    const min = Number(input.min || 0);
    const max = Number(input.max || 100);
    const clamped = Math.max(min, Math.min(max, Number(val)));
    const pct = max > min ? ((clamped - min) / (max - min)) * 100 : 0;
    if (wrap) wrap.style.setProperty("--fill", `${pct.toFixed(1)}%`);
    const text = formatValue ? formatValue(clamped) : `${Math.round(clamped)}`;
    input.setAttribute("aria-valuetext", text);
    if (valueEl) valueEl.textContent = text;
    if (bubbleEl) bubbleEl.textContent = text;
  };

  const lock = () => {
    if (!dragging && navigator.vibrate) {
      try { navigator.vibrate(6); } catch (_) {}
    }
    dragging = true;
    if (wrap) wrap.classList.add("is-dragging");
    clearTimeout(releaseTimer);
  };

  const unlock = () => {
    clearTimeout(releaseTimer);
    releaseTimer = setTimeout(() => {
      dragging = false;
      if (wrap) wrap.classList.remove("is-dragging");
    }, 250);
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
      // Trailing edge: guarantees upward/final position is ALWAYS sent!
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
 * Adds tactile haptic vibration where supported.
 */
export function bindStepRepeat(btn, onStep, { delay = 380, interval = 110 } = {}) {
  let holdTimer = null, repeatTimer = null, pointerActive = false;

  const triggerStep = () => {
    if (navigator.vibrate) {
      try { navigator.vibrate(8); } catch (_) {}
    }
    onStep();
  };

  const stop = () => {
    clearTimeout(holdTimer);
    clearInterval(repeatTimer);
    holdTimer = null;
    repeatTimer = null;
  };

  btn.addEventListener("pointerdown", (e) => {
    if (e.button && e.button !== 0) return;
    pointerActive = true;
    triggerStep();
    stop();
    holdTimer = setTimeout(() => {
      repeatTimer = setInterval(triggerStep, interval);
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
    if (e.detail === 0) triggerStep();
  });
}

function updateHeaderPackagePill(blState) {
  const pill = document.getElementById("header-pkg-pill");
  const text = document.getElementById("header-pkg-text");
  if (!pill) return;
  const count = typeof blState.packages_count === "number" ? blState.packages_count : (blState.packages || []).length;
  if (count > 0) {
    pill.style.display = "inline-flex";
    if (text) text.textContent = count === 1 ? "1 pkg" : `${count} pkgs`;
  } else {
    pill.style.display = "none";
  }
}

function apply(module, patch) {
  state[module] = { ...(state[module] || {}), ...patch };
  const card = document.getElementById(`card-${module}`);
  if (card) card.hidden = false;
  if (module === "buildinglink") {
    updateHeaderPackagePill(state[module]);
  }
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

// Module cards: Deliveries at top, then Lights, then Audio, then Pets at bottom!
const MODULE_CARDS = ["buildinglink", "hue", "denon", "litter_robot", "demo"];
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

