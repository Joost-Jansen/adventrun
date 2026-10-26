// A readout per group of marks. Pointing at, focusing or tapping a mark shows its details; a tap keeps them until the
// next tap. Calendar doors fill the slots of the panel below the calendar (data-head, data-a, data-k, data-c); chart
// bars set one line of text (data-detail). Everything shown here is also in the marks' aria-labels or the chart table.
(() => {
  document.querySelectorAll("[data-detail-target]").forEach((group) => {
    const out = document.getElementById(group.dataset.detailTarget);
    if (!out) return;
    const slots = [...out.querySelectorAll("[data-slot]")];
    const initial = slots.length ? slots.map((s) => s.textContent) : [out.textContent];
    const marks = [...group.querySelectorAll(slots.length ? "[data-head]" : "[data-detail]")];
    let pinned = null;
    const show = (el) => {
      if (!el) {
        if (slots.length) slots.forEach((s, i) => (s.textContent = initial[i]));
        else out.textContent = initial[0];
      } else if (slots.length) {
        slots.forEach((s) => (s.textContent = el.dataset[s.dataset.slot]));
      } else {
        out.textContent = el.dataset.detail;
      }
    };
    const reset = () => show(pinned);
    marks.forEach((el) => {
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
