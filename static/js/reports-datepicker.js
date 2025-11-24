(function initReportsDatepicker() {
  if (window._reportsDatepickerInit) return;
  window._reportsDatepickerInit = true;

  const input = document.getElementById("reports-date");
  const btn = document.getElementById("reports-go");
  if (!input || !btn) return;

  let userSetDate = false;

  // Mark when user types/selects
  input.addEventListener("input", () => (userSetDate = true));
  input.addEventListener("change", () => (userSetDate = true));
  input.addEventListener("changeDate", () => (userSetDate = true));
  input.addEventListener("hide.datepicker", () => {
    if (input.value) userSetDate = true;
  });

  function ensurePickerInBody() {
    const dpEl = document.querySelector(".datepicker.dropdown");
    if (dpEl && dpEl.parentNode !== document.body) {
      document.body.appendChild(dpEl);
    }
  }

  function navigate() {
    let dateVal = "";
    try {
      const dpDate = input.datepicker?.getDate?.();
      if (dpDate instanceof Date && !isNaN(dpDate)) {
        dateVal = dpDate.toISOString().slice(0, 10);
      } else {
        dateVal = input.value;
      }
    } catch {
      dateVal = input.value;
    }

    if (!dateVal) {
      input.classList.add("ring-2", "ring-red-500", "border-red-500");
      setTimeout(() => input.classList.remove("ring-2", "ring-red-500", "border-red-500"), 1500);
      return;
    }

    btn.disabled = true;
    // Remove any existing children to prepare for spinner+label
    while (btn.firstChild) btn.removeChild(btn.firstChild);

    // Create spinner via DOM API (safe, not using innerHTML)
    const svgns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgns, "svg");
    svg.setAttribute("class", "animate-spin -ml-1 mr-2 h-4 w-4 text-white");
    svg.setAttribute("fill", "none");
    svg.setAttribute("viewBox", "0 0 24 24");

    const circle = document.createElementNS(svgns, "circle");
    circle.setAttribute("class", "opacity-25");
    circle.setAttribute("cx", "12");
    circle.setAttribute("cy", "12");
    circle.setAttribute("r", "10");
    circle.setAttribute("stroke", "currentColor");
    circle.setAttribute("stroke-width", "4");

    const path = document.createElementNS(svgns, "path");
    path.setAttribute("class", "opacity-75");
    path.setAttribute("fill", "currentColor");
    path.setAttribute(
      "d",
      "M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
    );

    svg.appendChild(circle);
    svg.appendChild(path);
    btn.appendChild(svg);
    btn.appendChild(document.createTextNode(" Cargando..."));

    // Validate dateVal format (YYYY-MM-DD) before navigation to avoid unexpected input
    const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
    if (!dateRegex.test(dateVal)) {
      // invalid date format: show visual error and reset button
      btn.disabled = false;
      input.classList.add("ring-2", "ring-red-500", "border-red-500");
      setTimeout(() => input.classList.remove("ring-2", "ring-red-500", "border-red-500"), 1500);
      return;
    }

    // Use encodeURIComponent for safety even if format is validated
    const safeDate = encodeURIComponent(dateVal);
    window.location.href = `/reports/date/${safeDate}`;
  }

  function setup() {
    if (input.datepicker && typeof input.datepicker.setDate === "function") {
      const hasDate = (() => {
        try {
          const dpDate = input.datepicker.getDate?.();
          return dpDate instanceof Date && !isNaN(dpDate);
        } catch {
          return false;
        }
      })();

      if (!input.value && !hasDate && !userSetDate) {
        input.datepicker.setDate(new Date());
      }

      ensurePickerInBody();
      btn.addEventListener("click", navigate);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          navigate();
        }
      });

      // Close on outside click or ESC
      document.addEventListener(
        "click",
        (ev) => {
          const dpEl = document.querySelector(".datepicker.dropdown");
          const target = ev.target;
          const insideInput = target === input || input.contains?.(target);
          const insidePicker = dpEl && (dpEl === target || dpEl.contains?.(target));
          if (!insideInput && !insidePicker) {
            input.datepicker.hide?.();
          }
        },
        true
      );
      document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") input.datepicker.hide?.();
      });
    } else {
      if (!input.value && !userSetDate) {
        input.value = new Date().toISOString().slice(0, 10);
      }
      btn.addEventListener("click", navigate);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          navigate();
        }
      });
    }
  }

  // Wait for Flowbite to attach the picker
  let retries = 0;
  (function waitForPicker() {
    if (input.datepicker || retries > 20) {
      setup();
    } else {
      retries++;
      setTimeout(waitForPicker, 100);
    }
  })();
})();
