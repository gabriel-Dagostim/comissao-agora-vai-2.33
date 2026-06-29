(function () {
  function digitsOnly(el) {
    if (!el) return;
    el.addEventListener("input", function () {
      var cleaned = el.value.replace(/\D+/g, "");
      if (cleaned !== el.value) el.value = cleaned;
    });
  }

  digitsOnly(document.getElementById("eanInput"));
  digitsOnly(document.getElementById("codInput"));

  var globalBtn = document.getElementById("comissaoInfoGlobal");
  var globalPanel = document.getElementById("comissaoInfoPanel");

  if (globalBtn && globalPanel) {
    globalBtn.addEventListener("click", function () {
      var open = globalPanel.hasAttribute("hidden");
      if (open) {
        globalPanel.removeAttribute("hidden");
        globalBtn.setAttribute("aria-expanded", "true");
      } else {
        globalPanel.setAttribute("hidden", "");
        globalBtn.setAttribute("aria-expanded", "false");
      }
    });
  }

  document.querySelectorAll("[data-info-trigger]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      var card = btn.closest(".comissao-card");
      if (!card) return;
      var pop = card.querySelector(".info-popover");
      if (!pop) return;

      document.querySelectorAll(".info-popover").forEach(function (p) {
        if (p !== pop) p.setAttribute("hidden", "");
      });

      if (pop.hasAttribute("hidden")) {
        pop.removeAttribute("hidden");
      } else {
        pop.setAttribute("hidden", "");
      }
    });
  });

  document.addEventListener("click", function () {
    document.querySelectorAll(".info-popover").forEach(function (p) {
      p.setAttribute("hidden", "");
    });
  });

  var ean = document.getElementById("eanInput");
  var cod = document.getElementById("codInput");
  if (ean && cod) {
    ean.addEventListener("input", function () {
      if (ean.value) cod.value = "";
    });
    cod.addEventListener("input", function () {
      if (cod.value) ean.value = "";
    });
  }
})();
