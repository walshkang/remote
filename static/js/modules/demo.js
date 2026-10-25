export function mount(el, { send, onState, lockedSlider }) {
  el.innerHTML = `
    <h2>Demo (sync test)</h2>
    <div class="row">
      <button data-d="-1">−</button>
      <div class="big" id="demo-level">–</div>
      <button data-d="1">+</button>
    </div>
    <input type="range" min="0" max="80" id="demo-slider">
    <div class="muted">applied to "hardware": <span id="demo-applied">–</span></div>`;
  const level = el.querySelector("#demo-level");
  const applied = el.querySelector("#demo-applied");
  const slider = lockedSlider(el.querySelector("#demo-slider"), {
    onInput: (v) => send("demo", "set", { value: v }),
  });
  el.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => send("demo", "delta", { delta: Number(b.dataset.d) })));
  onState("demo", (s) => {
    level.textContent = s.level;
    applied.textContent = s.applied;
    slider.set(s.level);
  });
}
