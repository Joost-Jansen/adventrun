// Calendar doors open on hover and focus (CSS); a tap or click keeps one door open until the next tap, Escape or a
// tap elsewhere. Chart bars write their day into the line under the chart. Everything shown is also in aria-labels
// or the chart's table.
(() => {
  const doors = [...document.querySelectorAll(".door")];
  let open = null;
  const close = () => {
    if (open) open.classList.remove("is-open");
    open = null;
  };
  doors.forEach((door) =>
    door.addEventListener("click", (e) => {
      e.stopPropagation();
      const same = open === door;
      close();
      if (!same) {
        door.classList.add("is-open");
        open = door;
      }
    }),
  );
  document.addEventListener("click", close);
  document.addEventListener("keydown", (e) => e.key === "Escape" && close());

  document.querySelectorAll("[data-detail-target]").forEach((group) => {
    const out = document.getElementById(group.dataset.detailTarget);
    if (!out) return;
    const initial = out.textContent;
    group.querySelectorAll("[data-detail]").forEach((el) => {
      el.addEventListener("pointerenter", () => (out.textContent = el.dataset.detail));
      el.addEventListener("pointerleave", () => (out.textContent = initial));
      el.addEventListener("click", () => (out.textContent = el.dataset.detail));
    });
  });
})();

// The goal label sits on the goal line: its height comes from the data, set through the CSSOM (CSP allows no inline style).
document.querySelectorAll(".goal-tag[data-goal-y]").forEach((tag) => {
  const y = Number(tag.dataset.goalY);
  if (!Number.isFinite(y)) return;
  tag.style.top = `calc(1.6rem + (100% - 1.6rem) * ${y / 100})`;
  tag.classList.add("is-placed");
});
