export function mount(el, { send, onState }) {
  el.setAttribute("aria-label", "Pets & Litter-Robot 4");
  el.innerHTML = `
    <div class="card-header">
      <div class="card-title-group">
        <h2>Pets & Litter</h2>
        <span class="card-subtitle" id="lr-name">Whisker · Litter-Robot 4</span>
      </div>
      <span id="lr-status" class="pill off" role="status">
        <span class="status-dot" aria-hidden="true"></span>
        <span id="lr-status-text">Offline</span>
      </span>
    </div>

    <div id="lr-setup" class="callout" hidden>
      Add <code>LITTER_ROBOT_EMAIL</code> and <code>LITTER_ROBOT_PASSWORD</code>
      (your Whisker app login) to <code>.env</code> and restart the server.
    </div>
    <div id="lr-error" class="muted" style="color:var(--danger); margin-bottom:10px;" hidden></div>

    <div class="telemetry-grid">
      <div class="telemetry-tile">
        <div class="telemetry-label">Waste drawer</div>
        <div class="telemetry-value" id="lr-waste">–</div>
        <div class="lr-meter"><div class="lr-meter-fill" id="lr-waste-bar"></div></div>
      </div>
      <div class="telemetry-tile">
        <div class="telemetry-label">Litter level</div>
        <div class="telemetry-value" id="lr-litter">–</div>
        <div class="lr-meter"><div class="lr-meter-fill ok" id="lr-litter-bar"></div></div>
      </div>
      <div class="telemetry-tile">
        <div class="telemetry-label">Last visitor</div>
        <div class="telemetry-value" id="lr-weight">–</div>
        <div class="muted" id="lr-visitor-time" style="font-size:11px; margin-top:8px;">–</div>
      </div>
    </div>

    <button id="lr-clean" class="hold-btn" type="button" aria-label="Hold to start a clean cycle">
      <span class="hold-fill" aria-hidden="true"></span>
      <span class="hold-label" id="lr-clean-label">Hold to clean (1s)</span>
    </button>
    <div id="lr-notice" class="lr-notice" role="status" aria-live="polite" hidden></div>

    <div class="chip-row" style="margin-top:12px;">
      <button id="lr-night" class="chip-btn" type="button" aria-pressed="false">💡 Night light</button>
      <button id="lr-lock" class="chip-btn" type="button" aria-pressed="false">🔒 Panel lock</button>
    </div>`;

  const $ = (id) => el.querySelector(id);
  const statusEl = $("#lr-status"), statusText = $("#lr-status-text");
  const cleanBtn = $("#lr-clean"), cleanLabel = $("#lr-clean-label");
  const noticeEl = $("#lr-notice"), errEl = $("#lr-error");
  const nightBtn = $("#lr-night"), lockBtn = $("#lr-lock");
  let robot = null;

  // Press-and-hold (1s) so a pocket tap or scroll can never trigger a cycle accidentally.
  const HOLD_MS = 1000;
  let holdTimer = null;
  const cancelHold = () => {
    clearTimeout(holdTimer);
    holdTimer = null;
    cleanBtn.classList.remove("holding");
    if (!cleanBtn.disabled) {
      cleanLabel.textContent = "Hold to clean (1s)";
    }
  };

  cleanBtn.addEventListener("pointerdown", (e) => {
    if (cleanBtn.disabled || (e.button && e.button !== 0)) return;
    cleanBtn.classList.add("holding");
    cleanLabel.textContent = "Keep holding…";
    if (navigator.vibrate) {
      try { navigator.vibrate(10); } catch (_) {}
    }
    holdTimer = setTimeout(() => {
      cancelHold();
      send("litter_robot", "clean");
      cleanLabel.textContent = "Clean cycle started! ✓";
      if (navigator.vibrate) {
        try { navigator.vibrate([20, 50, 30]); } catch (_) {}
      }
    }, HOLD_MS);
  });

  ["pointerup", "pointerleave", "pointercancel"].forEach((t) => cleanBtn.addEventListener(t, cancelHold));
  cleanBtn.addEventListener("contextmenu", (e) => e.preventDefault());
  cleanBtn.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !e.repeat && !cleanBtn.disabled) {
      e.preventDefault();
      cleanBtn.classList.add("holding");
      cleanLabel.textContent = "Keep holding…";
      holdTimer = setTimeout(() => {
        cancelHold();
        send("litter_robot", "clean");
        cleanLabel.textContent = "Clean cycle started! ✓";
      }, HOLD_MS);
    }
  });
  cleanBtn.addEventListener("keyup", cancelHold);

  nightBtn.addEventListener("click", () =>
    robot && send("litter_robot", "night_light", { on: !robot.night_light }));
  lockBtn.addEventListener("click", () =>
    robot && send("litter_robot", "panel_lock", { on: !robot.panel_lock }));

  onState("litter_robot", (s) => {
    $("#lr-setup").hidden = Boolean(s.configured);
    errEl.hidden = !s.error;
    errEl.textContent = s.error || "";
    noticeEl.hidden = !s.notice;
    noticeEl.textContent = s.notice || "";
    robot = s.robot;

    if (!robot) {
      statusText.textContent = s.configured ? "Connecting…" : "Setup needed";
      statusEl.className = "pill off";
      cleanBtn.disabled = true;
      return;
    }

    $("#lr-name").textContent = robot.name ? `Whisker · ${robot.name}` : "Whisker · Litter-Robot 4";

    // Obvious status indicators
    statusEl.style.background = "";
    statusEl.style.color = "";
    const isFault = !robot.online || robot.drawer_full || /FAULT|PINCH|REMOVED/.test(robot.status);

    if (isFault) {
      statusEl.className = "pill off";
      statusText.textContent = robot.drawer_full ? "Drawer full" : (robot.status_text || "Attention needed");
    } else if (robot.cycling) {
      statusEl.className = "pill neutral";
      statusText.textContent = "Cycling…";
    } else if (robot.cat_detected) {
      statusEl.className = "pill";
      statusEl.style.background = "var(--accent-soft)";
      statusEl.style.color = "var(--accent)";
      statusText.textContent = "Cat inside";
    } else {
      statusEl.className = "pill";
      statusText.textContent = "Ready";
    }

    // Telemetry: Waste Drawer
    const wastePct = Math.round(robot.waste_level);
    $("#lr-waste").textContent = `${wastePct}%`;
    const wbar = $("#lr-waste-bar");
    wbar.style.width = `${Math.min(100, wastePct)}%`;
    wbar.className = "lr-meter-fill " + (wastePct >= 85 ? "bad" : wastePct >= 70 ? "warn" : "ok");

    // Telemetry: Litter Level
    const litterPct = Math.round(robot.litter_level);
    $("#lr-litter").textContent = `${litterPct}%`;
    const lbar = $("#lr-litter-bar");
    lbar.style.width = `${Math.min(100, litterPct)}%`;
    lbar.className = "lr-meter-fill " + (litterPct < 30 ? "warn" : "ok");

    // Telemetry: Last Visitor
    $("#lr-weight").textContent = robot.pet_weight ? `${robot.pet_weight} lb` : "–";
    $("#lr-visitor-time").textContent = robot.last_seen ? `Visited ${robot.last_seen}` : "Weight sensor active";

    const blocked = !robot.online || !robot.power_on || robot.cycling || robot.cat_detected;
    cleanBtn.disabled = blocked;
    if (blocked) {
      cleanLabel.textContent = robot.cycling ? "Cleaning…" : robot.cat_detected ? "Cat inside" : "Offline";
    } else if (!cleanBtn.classList.contains("holding")) {
      cleanLabel.textContent = "Hold to clean (1s)";
    }

    nightBtn.setAttribute("aria-pressed", String(robot.night_light));
    lockBtn.setAttribute("aria-pressed", String(robot.panel_lock));
  });
}
