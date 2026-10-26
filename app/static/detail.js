// One readout line per group of marks (the calendar doors, the chart bars): pointing at, focusing or tapping a mark
// shows its details there. Every detail is also in the mark's aria-label or the chart's table, so nothing depends on it.
(() => {
  document.querySelectorAll("[data-detail-target]").forEach((group) => {
    const out = document.getElementById(group.dataset.detailTarget);
    if (!out) return;
    let pinned = null;
    const show = (el) => (out.textContent = el.dataset.detail);
    const reset = () => (out.textContent = pinned ? pinned.dataset.detail : out.dataset.default);
    group.querySelectorAll("[data-detail]").forEach((el) => {
      el.addEventListener("pointerenter", () => show(el));
      el.addEventListener("pointerleave", reset);
      el.addEventListener("focus", () => show(el));
      el.addEventListener("blur", reset);
      el.addEventListener("click", () => {
        if (pinned) pinned.classList.remove("is-open");
        pinned = pinned === el ? null : el;
        if (pinned) pinned.classList.add("is-open");
        reset();
      });
    });
  });
})();
