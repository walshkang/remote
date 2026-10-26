// Core: websocket client, state store, module card loader, touch-locked sliders.

const listeners = new Map(); // module -> [fn(state, patch)]
const state = {};
let ws, clientId, backoff = 500;

const connEl = document.getElementById("conn");
const cardsEl = document.getElementById("cards");

export function send(module, action, payload = {}) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ module, action, payload }));
}

export function onState(module, fn) {
  if (!listeners.has(module)) listeners.set(module, []);
  listeners.get(module).push(fn);
  if (state[module]) fn(state[module], state[module]);
}

/** Slider that ignores server echoes while the user's finger is on it
 *  (and 300ms after release), so it never fights the user's thumb. */
export function lockedSlider(input, { onInput, throttleMs = 50 }) {
  let dragging = false, releaseTimer, last = 0;
  const lock = () => { dragging = true; clearTimeout(releaseTimer); };
  const unlock = () => {
    clearTimeout(releaseTimer);
    releaseTimer = setTimeout(() => (dragging = false), 300);
  };

  input.addEventListener("pointerdown", lock);
  input.addEventListener("pointerup", unlock);
  input.addEventListener("pointercancel", unlock);

  // Mobile touch listeners for iOS Safari and Android
  input.addEventListener("touchstart", lock, { passive: true });
  input.addEventListener("touchend", unlock, { passive: true });
  input.addEventListener("touchcancel", unlock, { passive: true });

  input.addEventListener("input", () => {
    lock(); // Keep locked while actively receiving input; do NOT unlock here!
    const now = performance.now();
    if (now - last >= throttleMs) {
      last = now;
      onInput(Number(input.value));
    }
  });

  input.addEventListener("change", () => {
    onInput(Number(input.value));
    unlock();
  });

  return {
    set(v) { if (!dragging) input.value = v; },
    get dragging() { return dragging; }
  };
}

function apply(module, patch) {
  state[module] = { ...(state[module] || {}), ...patch };
  (listeners.get(module) || []).forEach((fn) => fn(state[module], patch));
}

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { backoff = 500; connEl.textContent = "live"; connEl.classList.remove("off"); };
  ws.onclose = () => {
    connEl.textContent = "reconnecting…"; connEl.classList.add("off");
    setTimeout(connect, backoff); backoff = Math.min(backoff * 2, 5000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "snapshot") {
      clientId = msg.client_id;
      Object.entries(msg.state).forEach(([m, s]) => apply(m, s));
    } else if (msg.type === "state") {
      apply(msg.module, msg.patch);
    } else if (msg.type === "error") {
      console.warn("server error", msg);
    }
  };
}

// Module cards are loaded on demand; add a module by adding a file + name here.
const MODULE_CARDS = ["denon", "hue", "demo"];
for (const name of MODULE_CARDS) {
  const el = document.createElement("section");
  el.className = "card";
  el.id = `card-${name}`;
  cardsEl.appendChild(el);
  import(`/static/js/modules/${name}.js`).then((m) => m.mount(el, { send, onState, lockedSlider }));
}

connect();
