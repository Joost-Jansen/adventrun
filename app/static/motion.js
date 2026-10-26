// Entrances for the parts of each section, once, as they come into view. Content is visible without JavaScript
// (the hiding only applies under html.js) and with reduced motion (the CSS only animates under no-preference).
(() => {
  const items = [...document.querySelectorAll("[data-reveal]")];
  if (!("IntersectionObserver" in window)) {
    items.forEach((el) => el.classList.add("is-in"));
    return;
  }
  // Stagger the parts of one section: heading, then text, then picture.
  const bySection = new Map();
  for (const el of items) {
    const section = el.closest("section, footer") || document.body;
    const list = bySection.get(section) || [];
    el.style.transitionDelay = `${Math.min(list.length, 4) * 80}ms`;
    list.push(el);
    bySection.set(section, list);
  }
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        e.target.classList.add("is-in");
        io.unobserve(e.target);
      }
    },
    { rootMargin: "0px 0px -10% 0px", threshold: 0.08 },
  );
  items.forEach((el) => io.observe(el));
})();
