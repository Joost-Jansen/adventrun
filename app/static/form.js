// Progressive enhancement for the pledge form. Without JavaScript all fields stay visible and work as plain inputs.
(() => {
  const form = document.getElementById("pledge-form");
  if (form) {
    const km = Number(form.dataset.km);
    const money = new Intl.NumberFormat(form.dataset.locale, { style: "currency", currency: "EUR" });
    const summary = document.getElementById("summary");
    const chosen = () => form.querySelector('input[name="type"]:checked')?.value;
    const parse = (text) => {
      let t = (text || "").replace(/[€\s ]/g, "");
      if (t.includes(",")) t = t.replace(/\./g, "").replace(",", ".");
      const n = Number(t);
      return t && Number.isFinite(n) && n > 0 ? n : null;
    };
    const fill = (tpl, values) => tpl.replace(/\{(\w+)\}/g, (_, k) => values[k] ?? "");

    const update = () => {
      const type = chosen();
      form.querySelectorAll(".group[data-for]").forEach((g) => (g.hidden = g.dataset.for !== type));
      let text = form.dataset.tplEmpty;
      if (type === "per_km") {
        const perKm = parse(form.per_km_amount.value);
        const max = parse(form.max_amount.value);
        if (perKm) {
          const total = perKm * km;
          text = max && max < total
            ? fill(form.dataset.tplCapped, { km, total: money.format(max) })
            : fill(form.dataset.tplPerKm, { km, total: money.format(total) });
        }
      } else if (type === "fixed") {
        const fixed = parse(form.fixed_amount.value);
        if (fixed) text = fill(form.dataset.tplFixed, { km, total: money.format(fixed), per_km: money.format(fixed / km) });
      }
      summary.textContent = text;
      summary.hidden = text === form.dataset.tplEmpty;
      form.querySelectorAll(".chip").forEach((chip) => {
        const input = form.elements[chip.dataset.fill];
        chip.setAttribute("aria-pressed", String(parse(input.value) === parse(chip.dataset.value)));
      });
    };

    form.querySelectorAll(".chip").forEach((chip) =>
      chip.addEventListener("click", () => {
        form.elements[chip.dataset.fill].value = chip.dataset.value;
        update();
      }),
    );
    form.addEventListener("input", update);
    form.addEventListener("change", update);
    update();
  }

  // Share: the full address of this page, copied or handed to the phone's share sheet.
  const url = document.getElementById("share-url");
  const button = document.getElementById("share-btn");
  if (url && button) {
    url.value = location.origin + location.pathname;
    button.addEventListener("click", async () => {
      try {
        if (navigator.share && matchMedia("(pointer: coarse)").matches) {
          await navigator.share({ title: document.title, url: url.value });
          return;
        }
        await navigator.clipboard.writeText(url.value);
        const label = button.textContent;
        button.textContent = button.dataset.copied;
        setTimeout(() => (button.textContent = label), 2000);
      } catch {
        url.select();
      }
    });
  }
})();
