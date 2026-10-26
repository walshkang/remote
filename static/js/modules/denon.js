export function mount(el, { send, onState, lockedSlider, bindStepRepeat }) {
  el.setAttribute("aria-label", "Denon Home Theater Receiver");
  el.innerHTML = `
    <div class="card-header">
      <div class="card-title-group">
        <h2>Living Room Audio</h2>
        <span class="card-subtitle">Denon AVR-X1200W</span>
      </div>
      <div class="room-actions">
        <span id="denon-status" class="pill off" role="status">
          <span class="status-dot" aria-hidden="true"></span>
          <span id="denon-status-text">Offline</span>
        </span>
        <button id="denon-power" class="power-btn" type="button" aria-label="Receiver power" aria-pressed="false" title="Toggle power">
          ⏻
        </button>
      </div>
    </div>

    <!-- IP Setup if not configured -->
    <div id="denon-config-box" class="callout" hidden>
      <label for="denon-ip-input" class="muted">Enter Denon Receiver IP address:</label>
      <div class="input-row">
        <input type="text" id="denon-ip-input" class="text-input" placeholder="e.g. 192.168.1.226" inputmode="url" autocomplete="off">
        <button id="denon-save-ip" class="primary-btn" type="button">Connect</button>
      </div>
    </div>

    <!-- Now Playing Display -->
    <div id="denon-np" class="now-playing" hidden aria-live="polite">
      <div class="np-meta">
        <div class="np-badge">Now Playing</div>
        <div id="denon-np-track" class="np-track"></div>
        <div id="denon-np-artist" class="np-artist"></div>
      </div>
    </div>

    <!-- Human-Centered Volume Controls -->
    <div style="margin-bottom: 18px;">
      <div class="vol-header">
        <span class="section-label" style="margin:0;">Master Volume</span>
        <div class="vol-readout" aria-live="polite">
          <span class="vol-primary" id="denon-vol-text">-30.0 dB</span>
          <span class="vol-secondary" id="denon-vol-sub">Level 50.0</span>
        </div>
      </div>

      <div class="fill-slider" id="denon-slider-wrap">
        <div class="fill-slider-bar"></div>
        <div class="fill-slider-meta">
          <span class="fill-slider-label">
            <span id="denon-vol-icon" aria-hidden="true">🔊</span>
            <span id="denon-vol-zone">Comfort range</span>
          </span>
          <span class="fill-slider-value">50.0 / 80</span>
        </div>
        <input
          type="range"
          min="0"
          max="80"
          step="0.5"
          value="50"
          id="denon-slider"
          aria-label="Master Volume"
        >
      </div>

      <div class="vol-stepper" role="group" aria-label="Volume fine adjustment">
        <button id="denon-vol-down" class="step-btn" type="button" aria-label="Decrease volume by 1 decibel">
          − 1.0 dB
        </button>
        <button id="denon-mute" class="mute-btn" type="button" aria-pressed="false" aria-label="Mute audio">
          <span id="denon-mute-icon" aria-hidden="true">🔇</span>
          <span id="denon-mute-label">Mute</span>
        </button>
        <button id="denon-vol-up" class="step-btn" type="button" aria-label="Increase volume by 1 decibel">
          + 1.0 dB
        </button>
      </div>
    </div>

    <!-- Source Selector -->
    <div>
      <div class="section-label">Input Source</div>
      <div class="source-grid" id="denon-sources" role="group" aria-label="Input Source">
        <button class="source-btn" type="button" data-src="MPLAY" aria-pressed="false">Apple TV</button>
        <button class="source-btn" type="button" data-src="TV" aria-pressed="false">TV Audio</button>
        <button class="source-btn" type="button" data-src="GAME" aria-pressed="false">Game / PS5</button>
        <button class="source-btn" type="button" data-src="SAT/CBL" aria-pressed="false">CBL / SAT</button>
        <button class="source-btn" type="button" data-src="BD" aria-pressed="false">Blu-ray</button>
        <button class="source-btn" type="button" data-src="BT" aria-pressed="false">Bluetooth</button>
      </div>
    </div>
  `;

  const statusEl = el.querySelector("#denon-status");
  const statusTextEl = el.querySelector("#denon-status-text");
  const powerBtn = el.querySelector("#denon-power");
  const muteBtn = el.querySelector("#denon-mute");
  const muteLabel = el.querySelector("#denon-mute-label");
  const volText = el.querySelector("#denon-vol-text");
  const volSub = el.querySelector("#denon-vol-sub");
  const volIcon = el.querySelector("#denon-vol-icon");
  const volZone = el.querySelector("#denon-vol-zone");
  const sliderWrap = el.querySelector("#denon-slider-wrap");
  const npBox = el.querySelector("#denon-np");
  const npTrack = el.querySelector("#denon-np-track");
  const npArtist = el.querySelector("#denon-np-artist");
  const configBox = el.querySelector("#denon-config-box");
  const ipInput = el.querySelector("#denon-ip-input");
  const saveIpBtn = el.querySelector("#denon-save-ip");

  function formatDb(val) {
    const rel = val - 80.0;
    const sign = rel > 0 ? "+" : "";
    return `${sign}${rel.toFixed(1)} dB`;
  }

  function describeZone(val, muted) {
    if (muted) return "Audio muted";
    if (val < 30) return "Quiet";
    if (val <= 58) return "Comfort range";
    return "Loud / Cinema";
  }

  let isMuted = false;

  const updateVolumeReadout = (v) => {
    const db = formatDb(v);
    volText.textContent = isMuted ? "Muted" : db;
    volSub.textContent = isMuted ? `${db} (${v.toFixed(1)})` : `Level ${v.toFixed(1)}`;
    volZone.textContent = describeZone(v, isMuted);
    volIcon.textContent = isMuted ? "🔇" : v < 25 ? "🔈" : v < 55 ? "🔉" : "🔊";
  };

  const slider = lockedSlider(el.querySelector("#denon-slider"), {
    formatValue: (v) => `${v.toFixed(1)} (${formatDb(v)})`,
    onInput: (v) => {
      updateVolumeReadout(v);
      send("denon", "volume_set", { value: v });
    },
  });

  const stepDownBtn = el.querySelector("#denon-vol-down");
  const stepUpBtn = el.querySelector("#denon-vol-up");
  if (bindStepRepeat) {
    bindStepRepeat(stepDownBtn, () => send("denon", "volume_delta", { delta: -1.0 }));
    bindStepRepeat(stepUpBtn, () => send("denon", "volume_delta", { delta: 1.0 }));
  } else {
    stepDownBtn.addEventListener("click", () => send("denon", "volume_delta", { delta: -1.0 }));
    stepUpBtn.addEventListener("click", () => send("denon", "volume_delta", { delta: 1.0 }));
  }

  powerBtn.addEventListener("click", () => send("denon", "power_toggle"));
  muteBtn.addEventListener("click", () => send("denon", "mute_toggle"));

  el.querySelectorAll("#denon-sources button").forEach((b) => {
    b.addEventListener("click", () => send("denon", "set_source", { source: b.dataset.src }));
  });

  saveIpBtn.addEventListener("click", () => {
    const val = ipInput.value.trim();
    if (val) send("denon", "set_host", { host: val });
  });

  onState("denon", (s) => {
    configBox.hidden = Boolean(s.configured);

    const isOn = s.power === "ON";
    if (s.connected) {
      statusTextEl.textContent = isOn ? "On" : "Standby";
      statusEl.className = isOn ? "pill" : "pill neutral";
    } else {
      statusTextEl.textContent = s.configured ? "Connecting…" : "Setup needed";
      statusEl.className = "pill off";
    }

    powerBtn.setAttribute("aria-pressed", String(isOn));

    isMuted = Boolean(s.mute);
    muteBtn.setAttribute("aria-pressed", String(isMuted));
    muteLabel.textContent = isMuted ? "Muted" : "Mute";
    sliderWrap.classList.toggle("is-muted", isMuted);

    const val = typeof s.volume === "number" ? s.volume : 50.0;
    slider.set(val);
    volText.textContent = isMuted ? "Muted" : s.volume_db || formatDb(val);
    volSub.textContent = isMuted
      ? `${s.volume_db || formatDb(val)} (${val.toFixed(1)})`
      : `Level ${val.toFixed(1)}`;
    volZone.textContent = describeZone(val, isMuted);
    volIcon.textContent = isMuted ? "🔇" : val < 25 ? "🔈" : val < 55 ? "🔉" : "🔊";

    if (s.now_playing && (s.now_playing.track || s.now_playing.artist)) {
      npBox.hidden = false;
      npTrack.textContent = s.now_playing.track || "Playing";
      npArtist.textContent = s.now_playing.artist || s.now_playing.album || "";
    } else {
      npBox.hidden = true;
    }

    el.querySelectorAll("#denon-sources button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.src === s.source));
    });
  });
}
