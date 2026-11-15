export function mount(el, { send, onState }) {
  el.setAttribute("aria-label", "Petlibro Granary Smart Feeder");
  el.innerHTML = `
    <div class="card-header">
      <div class="card-title-group">
        <h2>Pet Feeder</h2>
        <span class="card-subtitle" id="pl-name">Petlibro · Granary Feeder</span>
      </div>
      <span id="pl-status" class="pill off" role="status">
        <span class="status-dot" aria-hidden="true"></span>
        <span id="pl-status-text">Offline</span>
      </span>
    </div>

    <div id="pl-setup" class="callout" hidden>
      <div class="muted" style="margin-bottom:8px;">
        Sign in with a secondary Petlibro account (shared feeder) or set <code>PETLIBRO_EMAIL</code> / <code>PETLIBRO_PASSWORD</code> in <code>.env</code>:
      </div>
      <div class="input-row" style="margin-bottom:8px;">
        <input id="pl-email" class="text-input" type="email" placeholder="user+remote@domain.com" autocomplete="email">
      </div>
      <div class="input-row">
        <input id="pl-password" class="text-input" type="password" placeholder="Password" autocomplete="current-password">
        <button id="pl-save-creds" class="primary-btn" type="button">Connect</button>
      </div>
    </div>

    <div id="pl-error" class="muted" style="color:var(--danger); margin-bottom:10px;" hidden></div>

    <div class="telemetry-grid">
      <div class="telemetry-tile">
        <div class="telemetry-label">Food tank</div>
        <div class="telemetry-value" id="pl-food">–</div>
        <div class="muted" id="pl-food-sub" style="font-size:11px; margin-top:4px;">–</div>
      </div>
      <div class="telemetry-tile">
        <div class="telemetry-label">Fed today</div>
        <div class="telemetry-value" id="pl-portions">–</div>
        <div class="muted" id="pl-last-fed" style="font-size:11px; margin-top:4px;">–</div>
      </div>
      <div class="telemetry-tile">
        <div class="telemetry-label">Power</div>
        <div class="telemetry-value" id="pl-power">–</div>
        <div class="muted" style="font-size:11px; margin-top:4px;">Granary</div>
      </div>
    </div>

    <div id="pl-pin-row" class="input-row" style="margin-bottom:10px;" hidden>
      <input id="pl-pin" class="text-input" type="password" inputmode="numeric" placeholder="Household PIN required to dispense" autocomplete="off">
    </div>

    <button id="pl-feed" class="hold-btn" type="button" aria-label="Hold to dispense one snack portion">
      <span class="hold-fill" aria-hidden="true"></span>
      <span class="hold-label" id="pl-feed-label">Hold to dispense snack (1s)</span>
    </button>
    <div id="pl-notice" class="lr-notice" role="status" aria-live="polite" hidden></div>
  `;

  const $ = (id) => el.querySelector(id);
  const statusEl = $("#pl-status"), statusText = $("#pl-status-text");
  const setupBox = $("#pl-setup"), errEl = $("#pl-error"), noticeEl = $("#pl-notice");
  const feedBtn = $("#pl-feed"), feedLabel = $("#pl-feed-label");
  const saveBtn = $("#pl-save-creds"), emailInput = $("#pl-email"), passInput = $("#pl-password");
  const pinRow = $("#pl-pin-row"), pinInput = $("#pl-pin");

  let feeder = null;

  const getPin = () => (pinInput ? pinInput.value.trim() : "") || localStorage.getItem("remote-guest-pin") || "";
  if (pinInput) {
    pinInput.value = localStorage.getItem("remote-guest-pin") || "";
    pinInput.addEventListener("input", () => {
      localStorage.setItem("remote-guest-pin", pinInput.value.trim());
    });
  }

  saveBtn.addEventListener("click", () => {
    const email = emailInput.value.trim();
    const password = passInput.value;
    if (!email || !password) return;
    send("petlibro", "set_credentials", { email, password });
    passInput.value = "";
  });

  const HOLD_MS = 1000;
  let holdTimer = null;
  const cancelHold = () => {
    clearTimeout(holdTimer);
    holdTimer = null;
    feedBtn.classList.remove("holding");
    if (!feedBtn.disabled) {
      feedLabel.textContent = "Hold to dispense snack (1s)";
    }
  };

  feedBtn.addEventListener("pointerdown", (e) => {
    if (feedBtn.disabled || (e.button && e.button !== 0)) return;
    feedBtn.classList.add("holding");
    feedLabel.textContent = "Keep holding…";
    if (navigator.vibrate) {
      try { navigator.vibrate(10); } catch (_) {}
    }
    holdTimer = setTimeout(() => {
      cancelHold();
      send("petlibro", "feed", { portions: 1, pin: getPin() });
      feedLabel.textContent = "Snack dispensed! ✓";
      if (navigator.vibrate) {
        try { navigator.vibrate([20, 50, 30]); } catch (_) {}
      }
    }, HOLD_MS);
  });

  ["pointerup", "pointerleave", "pointercancel"].forEach((t) => feedBtn.addEventListener(t, cancelHold));
  feedBtn.addEventListener("contextmenu", (e) => e.preventDefault());
  feedBtn.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !e.repeat && !feedBtn.disabled) {
      e.preventDefault();
      feedBtn.classList.add("holding");
      feedLabel.textContent = "Keep holding…";
      holdTimer = setTimeout(() => {
        cancelHold();
        send("petlibro", "feed", { portions: 1, pin: getPin() });
        feedLabel.textContent = "Snack dispensed! ✓";
      }, HOLD_MS);
    }
  });
  feedBtn.addEventListener("keyup", cancelHold);

  onState("petlibro", (s) => {
    setupBox.hidden = Boolean(s.configured);
    if (pinRow) pinRow.hidden = !s.pin_required;
    if (pinInput && !pinInput.value && localStorage.getItem("remote-guest-pin")) {
      pinInput.value = localStorage.getItem("remote-guest-pin") || "";
    }
    errEl.hidden = !s.error;
    errEl.textContent = s.error || "";
    noticeEl.hidden = !s.notice;
    noticeEl.textContent = s.notice || "";
    feeder = s.feeder;

    if (!feeder) {
      statusText.textContent = s.configured ? "Connecting…" : "Setup needed";
      statusEl.className = "pill off";
      feedBtn.disabled = true;
      return;
    }

    $("#pl-name").textContent = feeder.name ? `Petlibro · ${feeder.name}` : "Petlibro · Granary Feeder";

    if (!feeder.online) {
      statusEl.className = "pill off";
      statusText.textContent = "Offline";
    } else if (!feeder.food_ok) {
      statusEl.className = "pill off";
      statusText.textContent = `Food ${feeder.food_status}`;
    } else {
      statusEl.className = "pill";
      statusText.textContent = "Ready";
    }

    $("#pl-food").textContent = feeder.food_status || "–";
    $("#pl-food-sub").textContent = feeder.food_ok ? "Tank OK" : "Refill soon";
    $("#pl-portions").textContent = typeof feeder.today_portions === "number" ? `${feeder.today_portions}` : "–";
    $("#pl-last-fed").textContent = feeder.last_fed ? `Last ${feeder.last_fed}` : "Portions today";
    $("#pl-power").textContent = feeder.power_mode || "AC Power";

    feedBtn.disabled = !feeder.online;
    if (!feeder.online) {
      feedLabel.textContent = "Feeder offline";
    } else if (!feedBtn.classList.contains("holding")) {
      feedLabel.textContent = "Hold to dispense snack (1s)";
    }
  });
}
