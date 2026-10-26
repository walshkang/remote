export function mount(el, { send, onState }) {
  el.setAttribute("aria-label", "Litter-Robot 4");
  el.innerHTML = `
    <div class="card-header">
      <div class="card-title-group">
        <h2>Litter Box</h2>
        <span class="card-subtitle" id="lr-name">Litter-Robot 4</span>
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
      </div>
    </div>

    <button id="lr-clean" class="hold-btn" type="button" aria-label="Hold to start a clean cycle">
      <span class="hold-fill" aria-hidden="true"></span>
      <span class="hold-label" id="lr-clean-label">Hold to clean</span>
    </button>
    <div id="lr-notice" class="lr-notice" role="status" aria-live="polite" hidden></div>

    <div class="chip-row" style="margin-top:12px;">
      <button id="lr-night" class="chip-btn" type="button" aria-pressed="false">Night light</button>
      <button id="lr-lock" class="chip-btn" type="button" aria-pressed="false">Panel lock</button>
    </div>`;

  const $ = (id) => el.querySelector(id);
  const statusEl = $("#lr-status"), statusText = $("#lr-status-text");
  const cleanBtn = $("#lr-clean"), cleanLabel = $("#lr-clean-label");
  const noticeEl = $("#lr-notice"), errEl = $("#lr-error");
  const nightBtn = $("#lr-night"), lockBtn = $("#lr-lock");
  let robot = null;

  // Press-and-hold (1s) so a pocket tap or scroll can never start a cycle.
  const HOLD_MS = 1000;
  let holdTimer = null;
  const cancelHold = () => {
    clearTimeout(holdTimer);
    holdTimer = null;
    cleanBtn.classList.remove("holding");
  };
  cleanBtn.addEventListener("pointerdown", (e) => {
    if (cleanBtn.disabled || (e.button && e.button !== 0)) return;
    cleanBtn.classList.add("holding");
    holdTimer = setTimeout(() => {
      cancelHold();
      send("litter_robot", "clean");
      if (navigator.vibrate) navigator.vibrate(30);
    }, HOLD_MS);
  });
  ["pointerup", "pointerleave", "pointercancel"].forEach((t) => cleanBtn.addEventListener(t, cancelHold));
  cleanBtn.addEventListener("contextmenu", (e) => e.preventDefault());
  cleanBtn.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !e.repeat && !cleanBtn.disabled) {
      e.preventDefault();
      cleanBtn.classList.add("holding");
      holdTimer = setTimeout(() => { cancelHold(); send("litter_robot", "clean"); }, HOLD_MS);
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

    $("#lr-name").textContent = robot.name || "Litter-Robot 4";
    statusText.textContent = robot.status_text;
    const bad = !robot.online || robot.drawer_full || /FAULT|PINCH|REMOVED/.test(robot.status);
    statusEl.className = bad ? "pill off" : robot.cycling || robot.cat_detected ? "pill neutral" : "pill";

    $("#lr-waste").textContent = `${Math.round(robot.waste_level)}%`;
    const wbar = $("#lr-waste-bar");
    wbar.style.width = `${Math.min(100, robot.waste_level)}%`;
    wbar.className = "lr-meter-fill" + (robot.waste_level >= 90 ? " bad" : robot.waste_level >= 70 ? " warn" : " ok");
    $("#lr-litter").textContent = `${Math.round(robot.litter_level)}%`;
    $("#lr-litter-bar").style.width = `${Math.min(100, robot.litter_level)}%`;
    $("#lr-weight").textContent = robot.pet_weight ? `${robot.pet_weight} lb` : "–";

    const blocked = !robot.online || !robot.power_on || robot.cycling || robot.cat_detected;
    cleanBtn.disabled = blocked;
    cleanLabel.textContent = robot.cycling ? "Cleaning…" : robot.cat_detected ? "Cat inside" : "Hold to clean";
    nightBtn.setAttribute("aria-pressed", String(robot.night_light));
    lockBtn.setAttribute("aria-pressed", String(robot.panel_lock));
  });
}
