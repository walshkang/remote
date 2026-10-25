export function mount(el, { send, onState, lockedSlider }) {
  el.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
      <h2 style="margin:0;">Denon AVR-X1200W</h2>
      <div style="display:flex; gap:8px; align-items:center;">
        <span id="denon-status" class="pill off" style="font-size:11px;">Offline</span>
        <button id="denon-power" style="width:42px; height:42px; font-size:18px; border-radius:10px;">⏻</button>
      </div>
    </div>

    <!-- IP Setup if not configured -->
    <div id="denon-config-box" style="display:none; margin-bottom:16px; background:#1c212a; padding:12px; border-radius:12px;">
      <div style="font-size:13px; margin-bottom:8px; color:var(--muted);">Enter Denon Receiver IP:</div>
      <div style="display:flex; gap:8px;">
        <input type="text" id="denon-ip-input" placeholder="e.g. 192.168.1.184" style="flex:1; background:#101317; border:1px solid #2b323e; color:#fff; padding:8px 12px; border-radius:8px;">
        <button id="denon-save-ip" style="width:auto; height:auto; padding:8px 16px; font-size:14px;">Connect</button>
      </div>
    </div>

    <!-- Now Playing Display -->
    <div id="denon-np" style="display:none; background:#10141b; border-left:3px solid var(--accent); padding:10px 14px; border-radius:8px; margin-bottom:16px;">
      <div style="font-size:11px; text-transform:uppercase; letter-spacing:0.05em; color:var(--accent); margin-bottom:2px;">Now Playing</div>
      <div id="denon-np-track" style="font-size:15px; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"></div>
      <div id="denon-np-artist" style="font-size:13px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"></div>
    </div>

    <!-- Volume Controls -->
    <div style="margin-bottom:16px;">
      <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:8px;">
        <span class="muted">Volume</span>
        <div style="display:flex; gap:8px; align-items:baseline;">
          <button id="denon-mute" style="width:auto; height:auto; padding:4px 10px; font-size:12px; border-radius:6px; background:#252c37;">Mute</button>
          <div class="big" id="denon-vol-text" style="font-size:32px;">-45.0 dB</div>
        </div>
      </div>

      <div class="row" style="margin-bottom:8px;">
        <button id="denon-vol-down" style="flex:1;">−</button>
        <button id="denon-vol-up" style="flex:1;">+</button>
      </div>
      <input type="range" min="0" max="80" step="0.5" id="denon-slider">
    </div>

    <!-- Source Selector -->
    <div>
      <div class="muted" style="margin-bottom:8px;">Input Source</div>
      <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:8px;" id="denon-sources">
        <button data-src="MPLAY" style="width:100%; height:44px; font-size:13px;">Apple TV</button>
        <button data-src="TV" style="width:100%; height:44px; font-size:13px;">TV Audio</button>
        <button data-src="SAT/CBL" style="width:100%; height:44px; font-size:13px;">CBL/SAT</button>
        <button data-src="GAME" style="width:100%; height:44px; font-size:13px;">Game/PS5</button>
        <button data-src="BD" style="width:100%; height:44px; font-size:13px;">Blu-ray</button>
        <button data-src="BT" style="width:100%; height:44px; font-size:13px;">Bluetooth</button>
      </div>
    </div>
  `;

  const statusEl = el.querySelector("#denon-status");
  const powerBtn = el.querySelector("#denon-power");
  const muteBtn = el.querySelector("#denon-mute");
  const volText = el.querySelector("#denon-vol-text");
  const npBox = el.querySelector("#denon-np");
  const npTrack = el.querySelector("#denon-np-track");
  const npArtist = el.querySelector("#denon-np-artist");
  const configBox = el.querySelector("#denon-config-box");
  const ipInput = el.querySelector("#denon-ip-input");
  const saveIpBtn = el.querySelector("#denon-save-ip");

  const slider = lockedSlider(el.querySelector("#denon-slider"), {
    onInput: (v) => send("denon", "volume_set", { value: v }),
  });

  el.querySelector("#denon-vol-down").addEventListener("click", () =>
    send("denon", "volume_delta", { delta: -1.0 })
  );
  el.querySelector("#denon-vol-up").addEventListener("click", () =>
    send("denon", "volume_delta", { delta: 1.0 })
  );

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
    // Config box display
    if (!s.configured) {
      configBox.style.display = "block";
    } else {
      configBox.style.display = "none";
    }

    // Status Pill
    if (s.connected) {
      statusEl.textContent = s.power === "ON" ? "On" : "Standby";
      statusEl.className = "pill";
      statusEl.style.background = s.power === "ON" ? "#1f6f43" : "#3b4554";
    } else {
      statusEl.textContent = s.configured ? "Connecting…" : "Not Configured";
      statusEl.className = "pill off";
    }

    // Power Button
    powerBtn.style.background = s.power === "ON" ? "#267a4a" : "#232932";
    powerBtn.style.color = s.power === "ON" ? "#8affbe" : "var(--fg)";

    // Mute Button
    if (s.mute) {
      muteBtn.style.background = "#842029";
      muteBtn.style.color = "#ffb3b8";
      muteBtn.textContent = "MUTED";
    } else {
      muteBtn.style.background = "#252c37";
      muteBtn.style.color = "var(--fg)";
      muteBtn.textContent = "Mute";
    }

    // Volume
    volText.textContent = s.volume_db || `${s.volume} dB`;
    slider.set(s.volume || 35);

    // Now Playing
    if (s.now_playing && (s.now_playing.track || s.now_playing.artist)) {
      npBox.style.display = "block";
      npTrack.textContent = s.now_playing.track || "Playing";
      npArtist.textContent = s.now_playing.artist || s.now_playing.album || "";
    } else {
      npBox.style.display = "none";
    }

    // Active Source Highlight
    el.querySelectorAll("#denon-sources button").forEach((b) => {
      if (b.dataset.src === s.source) {
        b.style.background = "var(--accent)";
        b.style.color = "#fff";
      } else {
        b.style.background = "#232932";
        b.style.color = "var(--fg)";
      }
    });
  });
}
