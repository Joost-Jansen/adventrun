// Show only the amount fields of the chosen kind. Without JavaScript both groups stay visible and the server ignores the other.
(() => {
  const radios = document.querySelectorAll('input[name="type"]');
  const update = () => {
    const chosen = document.querySelector('input[name="type"]:checked')?.value;
    document.querySelectorAll(".group[data-for]").forEach((g) => (g.hidden = g.dataset.for !== chosen));
  };
  radios.forEach((r) => r.addEventListener("change", update));
  update();
})();
