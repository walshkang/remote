// Philips Hue module UI: familiar Hue-app room cards, fill brightness bars,
// 1-tap white/color swatches, intuitive Warm <-> Cool & Hue/Sat sliders, and bulb drawers.

const WHITE_PRESETS = [
  { name: "Candle", mirek: 454, css: "#ff9e44" },
  { name: "Warm", mirek: 370, css: "#ffc982" },
  { name: "Read", mirek: 285, css: "#fff1db" },
  { name: "Daylight", mirek: 175, css: "#d6ecff" },
];

const COLOR_PRESETS = [
  { name: "Sunset", h: 18, s: 92, css: "hsl(18, 92%, 56%)" },
  { name: "Coral", h: 346, s: 84, css: "hsl(346, 84%, 60%)" },
  { name: "Lavender", h: 268, s: 78, css: "hsl(268, 78%, 66%)" },
  { name: "Ocean", h: 198, s: 90, css: "hsl(198, 90%, 54%)" },
  { name: "Emerald", h: 145, s: 82, css: "hsl(145, 82%, 46%)" },
  { name: "Gold", h: 42, s: 95, css: "hsl(42, 95%, 54%)" },
];

/** Convert mirek (153..500) to approximate Kelvin and human label. */
function formatMirek(mirek) {
  if (!mirek) return "Warm White";
  const k = Math.round(1000000 / mirek / 100) * 100;
  const label =
    mirek >= 410 ? "Candlelight" :
    mirek >= 330 ? "Warm White" :
    mirek >= 240 ? "Neutral" : "Cool Daylight";
  return `${label} (${k}K)`;
}

/** Convert mirek (153..500) to a warm/cool CSS rgb string for UI tinting. */
function mirekToRgb(mirek) {
  const t = Math.max(0, Math.min(1, (mirek - 153) / (500 - 153))); // 0 = cool, 1 = warm
  const r = Math.round(214 + t * (255 - 214));
  const g = Math.round(236 + t * (172 - 236));
  const b = Math.round(255 + t * (92 - 255));
  return [r, g, b];
}

/** Convert CIE xy to approximate sRGB [r, g, b] (0..255) for UI preview. */
function xyToRgb(xy) {
  if (!xy || xy.length < 2) return [245, 176, 78];
  const [x, y] = xy;
  if (y <= 0.0001) return [245, 176, 78];
  const Y = 1.0;
  const X = (Y / y) * x;
  const Z = (Y / y) * (1.0 - x - y);
  let r = X * 1.656492 - Y * 0.354851 - Z * 0.255038;
  let g = -X * 0.707196 + Y * 1.655397 + Z * 0.036152;
  let b = X * 0.051713 - Y * 0.121364 + Z * 1.011530;

  const max = Math.max(r, g, b, 1e-4);
  r = Math.max(0, r / max);
  g = Math.max(0, g / max);
  b = Math.max(0, b / max);

  const gamma = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
  return [
    Math.round(Math.min(1, gamma(r)) * 255),
    Math.round(Math.min(1, gamma(g)) * 255),
    Math.round(Math.min(1, gamma(b)) * 255),
  ];
}

function lightRgb(light) {
  if (!light) return [245, 176, 78];
  if (light.xy && Array.isArray(light.xy)) return xyToRgb(light.xy);
  if (light.mirek) return mirekToRgb(light.mirek);
  return [245, 176, 78];
}

export function mount(el, { send, onState, lockedSlider }) {
  el.setAttribute("aria-label", "Philips Hue Lighting");
  el.innerHTML = `
    <div class="card-header">
      <div class="card-title-group">
        <h2>Hue Lights</h2>
        <span class="card-subtitle" id="hue-summary">Rooms & Scenes</span>
      </div>
      <span id="hue-status" class="pill off" role="status">
        <span class="status-dot" aria-hidden="true"></span>
        <span id="hue-status-text">Offline</span>
      </span>
    </div>

    <div id="hue-pair" class="callout" hidden>
      <div class="muted" style="margin-bottom:10px;">
        Press the physical link button on top of your Philips Hue Bridge, then tap <strong>Pair Bridge</strong> within 30 seconds.
      </div>
      <button id="hue-pair-btn" class="primary-btn" type="button">Pair Bridge</button>
      <div id="hue-error" class="muted" style="margin-top:8px; color:var(--danger);" role="alert"></div>
    </div>

    <div id="hue-rooms" class="room-list"></div>
  `;

  const statusEl = el.querySelector("#hue-status");
  const statusTextEl = el.querySelector("#hue-status-text");
  const summaryEl = el.querySelector("#hue-summary");
  const pairBox = el.querySelector("#hue-pair");
  const errEl = el.querySelector("#hue-error");
  const roomsEl = el.querySelector("#hue-rooms");

  el.querySelector("#hue-pair-btn").addEventListener("click", () => send("hue", "pair"));

  let signature = "";
  const refs = { rooms: {}, lights: {} };

  /**
   * Build a reusable White + Color picker block for either a Room or an individual Bulb.
   */
  function buildColorStudio(container, { hasCt, hasColor, mirekMin = 153, mirekMax = 500, onTemp, onColor, labelPrefix }) {
    const presets = [
      ...(hasCt ? WHITE_PRESETS.map((p) => ({ ...p, kind: "ct" })) : []),
      ...(hasColor ? COLOR_PRESETS.map((p) => ({ ...p, kind: "color" })) : []),
    ];

    container.innerHTML = `
      ${presets.length ? `
        <div class="control-group">
          <div class="control-header"><span>Quick Ambiance</span></div>
          <div class="swatch-row" role="group" aria-label="${labelPrefix} quick presets">
            ${presets.map((p, idx) => `
              <button
                type="button"
                class="swatch"
                data-idx="${idx}"
                style="background:${p.css};"
                aria-label="${p.name}"
                aria-pressed="false"
                title="${p.name}"
              ></button>
            `).join("")}
          </div>
        </div>
      ` : ""}

      ${hasCt ? `
        <div class="control-group">
          <div class="control-header">
            <span>Warm ↔ Cool White</span>
            <span class="ct-readout">Warm White</span>
          </div>
          <input
            type="range"
            class="track-slider temp-track ct-input"
            min="0"
            max="100"
            value="30"
            aria-label="${labelPrefix} color temperature (Warm to Cool)"
          >
        </div>
      ` : ""}

      ${hasColor ? `
        <div class="control-group">
          <div class="control-header">
            <span>Color Spectrum & Saturation</span>
            <span class="color-readout">Hue 30° · 100%</span>
          </div>
          <input
            type="range"
            class="track-slider hue-track hue-input"
            min="0"
            max="360"
            value="30"
            aria-label="${labelPrefix} color hue angle"
          >
          <input
            type="range"
            class="track-slider sat-track sat-input"
            min="0"
            max="100"
            value="90"
            style="--sat-hue: 30;"
            aria-label="${labelPrefix} color saturation"
          >
        </div>
      ` : ""}
    `;

    // Swatch clicks
    const swatchBtns = container.querySelectorAll(".swatch");
    swatchBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        swatchBtns.forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
        const preset = presets[Number(btn.dataset.idx)];
        if (preset.kind === "ct" && onTemp) {
          const clamped = Math.max(mirekMin, Math.min(mirekMax, preset.mirek));
          onTemp(clamped);
          if (ctController) ctController.setMirek(clamped);
        } else if (preset.kind === "color" && onColor) {
          onColor(preset.h, preset.s);
          if (hueInput && satInput) {
            hueInput.value = preset.h;
            satInput.value = preset.s;
            updateColorPreview(preset.h, preset.s);
          }
        }
      });
    });

    // Warm <-> Cool slider: 0% on left = Warmest (mirekMax), 100% on right = Coolest (mirekMin)
    let ctController = null;
    const ctInput = container.querySelector(".ct-input");
    const ctReadout = container.querySelector(".ct-readout");
    if (ctInput && onTemp) {
      const posToMirek = (pos) => Math.round(mirekMax - (pos / 100) * (mirekMax - mirekMin));
      const mirekToPos = (m) => Math.round(((mirekMax - m) / Math.max(1, mirekMax - mirekMin)) * 100);

      const slider = lockedSlider(ctInput, {
        throttleMs: 120,
        formatValue: (pos) => formatMirek(posToMirek(pos)),
        onInput: (pos) => {
          const m = posToMirek(pos);
          if (ctReadout) ctReadout.textContent = formatMirek(m);
          const [r, g, b] = mirekToRgb(m);
          ctInput.style.setProperty("--thumb-color", `rgb(${r},${g},${b})`);
          onTemp(m);
        },
      });

      ctController = {
        setMirek(m) {
          if (!m) return;
          const pos = Math.max(0, Math.min(100, mirekToPos(m)));
          slider.set(pos);
          if (ctReadout) ctReadout.textContent = formatMirek(m);
          const [r, g, b] = mirekToRgb(m);
          ctInput.style.setProperty("--thumb-color", `rgb(${r},${g},${b})`);
        },
      };
    }

    // Hue + Saturation sliders
    const hueInput = container.querySelector(".hue-input");
    const satInput = container.querySelector(".sat-input");
    const colorReadout = container.querySelector(".color-readout");

    function updateColorPreview(h, s) {
      if (satInput) satInput.style.setProperty("--sat-hue", String(h));
      const hsl = `hsl(${h}, ${s}%, 55%)`;
      if (hueInput) hueInput.style.setProperty("--thumb-color", `hsl(${h}, 100%, 55%)`);
      if (satInput) satInput.style.setProperty("--thumb-color", hsl);
      if (colorReadout) colorReadout.textContent = `Hue ${Math.round(h)}° · ${Math.round(s)}%`;
    }

    if (hueInput && satInput && onColor) {
      const fireColor = () => {
        const h = Number(hueInput.value);
        const s = Number(satInput.value);
        updateColorPreview(h, s);
        onColor(h, s);
      };
      lockedSlider(hueInput, { throttleMs: 120, onInput: fireColor });
      lockedSlider(satInput, { throttleMs: 120, onInput: fireColor });
      updateColorPreview(Number(hueInput.value), Number(satInput.value));
    }

    return { ctController };
  }

  function build(s) {
    roomsEl.innerHTML = "";
    refs.rooms = {};
    refs.lights = {};

    for (const room of s.rooms) {
      const roomLights = room.light_ids.map((id) => s.lights[id]).filter(Boolean);
      const roomHasCt = roomLights.some((l) => l.has_ct);
      const roomHasColor = roomLights.some((l) => l.has_color);
      const minMirek = Math.min(...roomLights.filter((l) => l.has_ct).map((l) => l.mirek_min || 153), 153);
      const maxMirek = Math.max(...roomLights.filter((l) => l.has_ct).map((l) => l.mirek_max || 500), 500);

      const card = document.createElement("article");
      card.className = "room-card";
      card.innerHTML = `
        <div class="room-top">
          <div class="room-info">
            <span class="room-orb" aria-hidden="true"></span>
            <div>
              <div class="room-name">${room.name}</div>
              <div class="room-state-text">Off</div>
            </div>
          </div>
          <div class="room-actions">
            <button type="button" class="chip-btn expand-btn" aria-expanded="false" aria-label="Customize ${room.name} color and bulbs">
              Tune ▾
            </button>
            <button
              type="button"
              class="switch room-toggle"
              role="switch"
              aria-checked="false"
              aria-label="${room.name} lights"
            >
              <span class="switch-thumb"></span>
            </button>
          </div>
        </div>

        <div class="fill-slider room-bri-wrap">
          <div class="fill-slider-bar"></div>
          <div class="fill-slider-meta">
            <span class="fill-slider-label">
              <span aria-hidden="true">☀</span>
              <span>Brightness</span>
            </span>
            <span class="fill-slider-value">0%</span>
          </div>
          <input
            type="range"
            class="room-bri"
            min="1"
            max="100"
            value="50"
            aria-label="${room.name} brightness"
          >
        </div>

        <div class="chip-row scenes-row" role="group" aria-label="${room.name} scenes" ${room.scenes.length ? "" : "hidden"}></div>

        <div class="studio-drawer" hidden>
          <div class="room-studio"></div>
          <div class="control-group">
            <div class="control-header"><span>Individual Bulbs (${room.light_ids.length})</span></div>
            <div class="bulb-list"></div>
          </div>
        </div>
      `;
      roomsEl.appendChild(card);

      const orbEl = card.querySelector(".room-orb");
      const stateTextEl = card.querySelector(".room-state-text");
      const toggleBtn = card.querySelector(".room-toggle");
      const briWrap = card.querySelector(".room-bri-wrap");
      const expandBtn = card.querySelector(".expand-btn");
      const drawerEl = card.querySelector(".studio-drawer");

      let roomOn = false;
      toggleBtn.addEventListener("click", () =>
        send("hue", "room_toggle", { room: room.id, on: !roomOn })
      );

      const briSlider = lockedSlider(card.querySelector(".room-bri"), {
        throttleMs: 220,
        formatValue: (v) => `${Math.round(v)}%`,
        onInput: (v) => send("hue", "room_brightness", { room: room.id, value: v }),
      });

      // Scenes
      const scenesRow = card.querySelector(".scenes-row");
      let activeSceneId = null;
      for (const sc of room.scenes) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "chip-btn";
        b.textContent = sc.name;
        b.setAttribute("aria-pressed", "false");
        b.addEventListener("click", () => {
          activeSceneId = sc.id;
          scenesRow.querySelectorAll(".chip-btn").forEach((btn) =>
            btn.setAttribute("aria-pressed", String(btn === b))
          );
          send("hue", "scene_recall", { scene: sc.id });
        });
        scenesRow.appendChild(b);
      }

      // Expandable drawer
      expandBtn.addEventListener("click", () => {
        const willOpen = drawerEl.hidden;
        drawerEl.hidden = !willOpen;
        expandBtn.setAttribute("aria-expanded", String(willOpen));
        expandBtn.textContent = willOpen ? "Done ▴" : "Tune ▾";
      });

      // Room-level Color & White Studio
      const roomStudioEl = card.querySelector(".room-studio");
      let roomStudio = null;
      if (roomHasCt || roomHasColor) {
        roomStudio = buildColorStudio(roomStudioEl, {
          hasCt: roomHasCt,
          hasColor: roomHasColor,
          mirekMin: minMirek,
          mirekMax: maxMirek,
          labelPrefix: room.name,
          onTemp: (mirek) => send("hue", "room_temp", { room: room.id, mirek }),
          onColor: (h, sVal) => send("hue", "room_color", { room: room.id, h, s: sVal }),
        });
      } else {
        roomStudioEl.hidden = true;
      }

      // Individual Bulbs
      const bulbsEl = card.querySelector(".bulb-list");
      for (const lid of room.light_ids) {
        const light = s.lights[lid];
        if (!light) continue;
        const canTune = light.has_ct || light.has_color || (light.effects && light.effects.length > 0);

        const item = document.createElement("div");
        item.className = "bulb-item";
        item.innerHTML = `
          <div class="bulb-top">
            <div class="bulb-title">
              <span class="room-orb bulb-orb" aria-hidden="true"></span>
              <span>${light.name}</span>
            </div>
            <div class="room-actions">
              ${canTune ? `<button type="button" class="chip-btn bulb-tune-btn" aria-expanded="false">Color ▾</button>` : ""}
              <button
                type="button"
                class="switch bulb-toggle"
                role="switch"
                aria-checked="false"
                aria-label="${light.name} power"
              >
                <span class="switch-thumb"></span>
              </button>
            </div>
          </div>

          ${light.dimmable ? `
            <div class="fill-slider compact bulb-bri-wrap">
              <div class="fill-slider-bar"></div>
              <div class="fill-slider-meta">
                <span class="fill-slider-label">Brightness</span>
                <span class="fill-slider-value">0%</span>
              </div>
              <input
                type="range"
                class="bulb-bri"
                min="1"
                max="100"
                value="50"
                aria-label="${light.name} brightness"
              >
            </div>
          ` : ""}

          <div class="studio-drawer bulb-drawer" hidden>
            <div class="bulb-studio"></div>
            ${light.effects && light.effects.length ? `
              <div class="control-group">
                <label class="control-header" for="fx-${lid}"><span>Dynamic Effect</span></label>
                <select id="fx-${lid}" class="text-input bulb-effect" aria-label="${light.name} dynamic effect">
                  <option value="">Select effect…</option>
                  ${light.effects.map((e) => `<option value="${e}">${e}</option>`).join("")}
                  <option value="no_effect">Off (No effect)</option>
                </select>
              </div>
            ` : ""}
          </div>
        `;
        bulbsEl.appendChild(item);

        const bOrb = item.querySelector(".bulb-orb");
        const bToggle = item.querySelector(".bulb-toggle");
        const bBriWrap = item.querySelector(".bulb-bri-wrap");
        const bBriInput = item.querySelector(".bulb-bri");
        const bTuneBtn = item.querySelector(".bulb-tune-btn");
        const bDrawer = item.querySelector(".bulb-drawer");
        const bStudioEl = item.querySelector(".bulb-studio");
        const bFx = item.querySelector(".bulb-effect");

        let lOn = false;
        bToggle.addEventListener("click", () =>
          send("hue", "light_toggle", { light: lid, on: !lOn })
        );

        const bBriSlider = bBriInput && lockedSlider(bBriInput, {
          throttleMs: 100,
          formatValue: (v) => `${Math.round(v)}%`,
          onInput: (v) => send("hue", "light_brightness", { light: lid, value: v }),
        });

        let bStudio = null;
        if (bTuneBtn && bDrawer) {
          bTuneBtn.addEventListener("click", () => {
            const open = bDrawer.hidden;
            bDrawer.hidden = !open;
            bTuneBtn.setAttribute("aria-expanded", String(open));
            bTuneBtn.textContent = open ? "Close ▴" : "Color ▾";
          });
          if (light.has_ct || light.has_color) {
            bStudio = buildColorStudio(bStudioEl, {
              hasCt: light.has_ct,
              hasColor: light.has_color,
              mirekMin: light.mirek_min || 153,
              mirekMax: light.mirek_max || 500,
              labelPrefix: light.name,
              onTemp: (mirek) => send("hue", "light_temp", { light: lid, mirek }),
              onColor: (h, sVal) => send("hue", "light_color", { light: lid, h, s: sVal }),
            });
          }
        }

        if (bFx) {
          bFx.addEventListener("change", () => {
            if (bFx.value) send("hue", "light_effect", { light: lid, effect: bFx.value });
          });
        }

        refs.lights[lid] = (l) => {
          lOn = Boolean(l.on);
          bToggle.setAttribute("aria-checked", String(lOn));
          const [r, g, b] = lightRgb(l);
          const rgbCss = `rgb(${r}, ${g}, ${b})`;
          bToggle.style.setProperty("--switch-color", lOn ? rgbCss : "");
          bOrb.style.setProperty("--orb-color", lOn ? rgbCss : "var(--fg-subtle)");
          bOrb.style.setProperty("--orb-glow", lOn ? `rgba(${r}, ${g}, ${b}, 0.55)` : "transparent");
          if (bBriWrap) {
            bBriWrap.classList.toggle("is-off", !lOn);
            bBriWrap.style.setProperty("--fill-color", `rgba(${r}, ${g}, ${b}, 0.42)`);
          }
          if (bBriSlider) bBriSlider.set(lOn ? l.brightness : 0);
          if (bStudio && bStudio.ctController && l.mirek) {
            bStudio.ctController.setMirek(l.mirek);
          }
        };
      }

      refs.rooms[room.id] = (r, fullState) => {
        roomOn = Boolean(r.on);
        card.classList.toggle("is-on", roomOn);
        toggleBtn.setAttribute("aria-checked", String(roomOn));
        briWrap.classList.toggle("is-off", !roomOn);
        briSlider.set(roomOn ? r.brightness : 0);

        const activeLights = r.light_ids
          .map((id) => fullState.lights[id])
          .filter((l) => l && l.on);
        const onCount = activeLights.length;
        const totalCount = r.light_ids.length;

        // Compute average room tint from active lights
        let avgRgb = [245, 166, 65];
        if (activeLights.length > 0) {
          const sum = activeLights.reduce(
            (acc, l) => {
              const c = lightRgb(l);
              return [acc[0] + c[0], acc[1] + c[1], acc[2] + c[2]];
            },
            [0, 0, 0]
          );
          avgRgb = sum.map((v) => Math.round(v / activeLights.length));
        }

        const [cr, cg, cb] = avgRgb;
        const rgbCss = `rgb(${cr}, ${cg}, ${cb})`;
        orbEl.style.setProperty("--orb-color", roomOn ? rgbCss : "var(--fg-subtle)");
        orbEl.style.setProperty("--orb-glow", roomOn ? `rgba(${cr}, ${cg}, ${cb}, 0.6)` : "transparent");
        toggleBtn.style.setProperty("--switch-color", roomOn ? rgbCss : "");
        briWrap.style.setProperty("--fill-color", `rgba(${cr}, ${cg}, ${cb}, 0.42)`);
        card.style.setProperty("--room-border", `rgba(${cr}, ${cg}, ${cb}, 0.35)`);

        if (roomOn) {
          stateTextEl.textContent = `${onCount} of ${totalCount} on · ${Math.round(r.brightness)}%`;
        } else {
          stateTextEl.textContent = "All off";
        }

        const firstMirek = activeLights.find((l) => l.mirek)?.mirek;
        if (roomStudio && roomStudio.ctController && firstMirek) {
          roomStudio.ctController.setMirek(firstMirek);
        }
      };
    }
  }

  onState("hue", (s) => {
    pairBox.hidden = Boolean(s.paired);
    errEl.textContent = s.error || "";

    if (s.connected) {
      statusTextEl.textContent = "Connected";
      statusEl.className = "pill";
    } else if (s.paired) {
      statusTextEl.textContent = "Connecting…";
      statusEl.className = "pill neutral";
    } else {
      statusTextEl.textContent = "Not paired";
      statusEl.className = "pill off";
    }

    if (!s.rooms || !s.rooms.length) return;

    const sig = JSON.stringify([
      s.rooms.map((r) => [r.id, r.light_ids, r.scenes.map((x) => x.id)]),
      Object.values(s.lights).map((l) => [l.id, l.dimmable, l.has_ct, l.has_color, l.effects]),
    ]);
    if (sig !== signature) {
      signature = sig;
      build(s);
    }

    const roomsOn = s.rooms.filter((r) => r.on).length;
    summaryEl.textContent =
      roomsOn > 0 ? `${roomsOn} of ${s.rooms.length} rooms lit` : "All rooms off";

    s.rooms.forEach((r) => refs.rooms[r.id] && refs.rooms[r.id](r, s));
    Object.values(s.lights).forEach((l) => refs.lights[l.id] && refs.lights[l.id](l));
  });
}
