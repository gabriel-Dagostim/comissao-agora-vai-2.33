(function () {
  var COOLDOWN_MS = 4000;
  var STORAGE_KEY = "comissaoLastConsultAt";

  function getRemainingMs() {
    var last = parseInt(sessionStorage.getItem(STORAGE_KEY) || "0", 10);
    if (!last) return 0;
    return Math.max(0, COOLDOWN_MS - (Date.now() - last));
  }

  function markConsultNow() {
    sessionStorage.setItem(STORAGE_KEY, String(Date.now()));
  }

  function hasActiveQueryInputs() {
    var ean = document.getElementById("eanInput");
    var cod = document.getElementById("codInput");
    return Boolean((ean && ean.value.trim()) || (cod && cod.value.trim()));
  }

  function setupConsultCooldown() {
    var form = document.querySelector(".consulta-form");
    var btn = document.getElementById("btnConsultar");
    if (!form || !btn || form.dataset.dbReady !== "1") return;

    var progress = btn.querySelector(".btn-consultar__progress");
    var label = btn.querySelector(".btn-consultar__label");
    var rafId = null;

    function stopAnimation() {
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
    }

    function resetButton() {
      stopAnimation();
      btn.disabled = false;
      btn.classList.remove("is-cooling");
      if (progress) progress.style.width = "0%";
      if (label) label.textContent = "Consultar";
    }

    function runCooldown() {
      var remaining = getRemainingMs();
      if (remaining <= 0) {
        resetButton();
        return;
      }

      btn.disabled = true;
      btn.classList.add("is-cooling");

      function tick() {
        remaining = getRemainingMs();
        if (remaining <= 0) {
          resetButton();
          return;
        }

        var pct = ((COOLDOWN_MS - remaining) / COOLDOWN_MS) * 100;
        if (progress) progress.style.width = pct + "%";
        if (label) label.textContent = "Aguarde " + Math.ceil(remaining / 1000) + "s";
        rafId = requestAnimationFrame(tick);
      }

      tick();
    }

    if (hasActiveQueryInputs() && getRemainingMs() === 0) {
      markConsultNow();
    }

    form.addEventListener("submit", function (e) {
      if (getRemainingMs() > 0) {
        e.preventDefault();
        runCooldown();
        return;
      }
      markConsultNow();
    });

    runCooldown();
  }

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

  setupConsultCooldown();
})();
