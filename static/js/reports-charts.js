/**
 * reports-charts.js
 * Chart initialization and PDF export logic for the reports view.
 * Reads chart data from the #chart-data JSON script tag injected by the template.
 */

document.addEventListener("DOMContentLoaded", function () {
  const chartDataEl = document.getElementById("chart-data");
  if (!chartDataEl) return;

  const chartData = JSON.parse(chartDataEl.textContent);

  const CHART_COLORS = [
    "#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
    "#EC4899", "#14B8A6", "#F97316", "#64748B", "#84CC16",
    "#06B6D4", "#D946EF", "#F43F5E", "#0EA5E9", "#22C55E",
    "#EAB308", "#F43F5E", "#8B5CF6", "#EC4899", "#14B8A6",
  ];

  function getTextColor() {
    return document.documentElement.classList.contains("dark")
      ? "#d1d5db"
      : "#374151";
  }

  function getBorderColor() {
    return document.documentElement.classList.contains("dark")
      ? "#374151"
      : "#fff";
  }

  // ─── Bar chart helper ─────────────────────────────────────────────────────

  function buildBarChart(canvasId, payload, label, valueSuffix) {
    const el = document.getElementById(canvasId);
    if (!el || !payload) return;

    new Chart(el.getContext("2d"), {
      type: "bar",
      data: {
        labels: payload.labels,
        datasets: [
          {
            label: label,
            data: payload.data,
            backgroundColor: CHART_COLORS.slice(0, payload.data.length),
            borderColor: CHART_COLORS.slice(0, payload.data.length).map(
              (c) => c + "DD"
            ),
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            mode: "index",
            intersect: false,
            callbacks: {
              label: function (context) {
                return `${context.dataset.label}: ${context.raw.toFixed(2)} ${valueSuffix}`;
              },
            },
          },
          datalabels: { display: false },
        },
        scales: {
          y: {
            beginAtZero: true,
            title: { display: true, text: label },
            ticks: { color: getTextColor() },
          },
          x: {
            ticks: { autoSkip: false, color: getTextColor() },
          },
        },
      },
    });
  }

  // ─── Pie chart helper ─────────────────────────────────────────────────────

  function buildPieChart(canvasId, payload) {
    const el = document.getElementById(canvasId);
    if (!el || !payload) return;

    new Chart(el.getContext("2d"), {
      type: "pie",
      data: {
        labels: payload.labels,
        datasets: [
          {
            data: payload.data,
            backgroundColor: payload.colors,
            borderColor: getBorderColor(),
            borderWidth: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "right",
            labels: { font: { size: 12 }, color: getTextColor() },
          },
          tooltip: {
            callbacks: {
              label: function (context) {
                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                const pct = ((context.raw / total) * 100).toFixed(1);
                return `${context.label}: ${context.raw} (${pct}%)`;
              },
            },
          },
          datalabels: {
            formatter: function (value, ctx) {
              const total = ctx.chart.data.datasets[0].data.reduce(
                (a, b) => a + b,
                0
              );
              const pct = ((value / total) * 100).toFixed(1);
              return pct > 3 ? `${pct}%` : "";
            },
            color: "#fff",
            font: { weight: "bold", size: 12 },
          },
        },
      },
      plugins: [ChartDataLabels],
    });
  }

  // ─── Initialize charts ────────────────────────────────────────────────────

  buildBarChart(
    "usersActivityChart",
    chartData.usersActivity,
    "Número de Visitas",
    ""
  );
  buildBarChart("usersDataChart", chartData.usersData, "Datos (MB)", "MB");
  buildPieChart("httpCodesChart", chartData.httpCodes);

  // ─── PDF export ───────────────────────────────────────────────────────────

  const pdfButton = document.getElementById("reports-export-pdf");
  const dateInput = document.getElementById("reports-date");

  if (pdfButton) {
    pdfButton.addEventListener("click", function () {
      let isoDate = null;

      // Prefer the datepicker's Date object to avoid display-format issues (MM/DD/YYYY vs YYYY-MM-DD)
      try {
        const dpDate = dateInput && dateInput.datepicker?.getDate?.();
        if (dpDate instanceof Date && !isNaN(dpDate)) {
          isoDate = dpDate.toISOString().slice(0, 10);
        }
      } catch (_) {
        // datepicker API unavailable — fall through
      }

      // Fallback: raw input value already in YYYY-MM-DD (e.g. set programmatically)
      if (!isoDate && dateInput && /^\d{4}-\d{2}-\d{2}$/.test(dateInput.value)) {
        isoDate = dateInput.value;
      }

      // Fallback: parse MM/DD/YYYY display format produced by Flowbite datepicker
      if (!isoDate && dateInput && dateInput.value) {
        const parts = dateInput.value.split("/");
        if (parts.length === 3) {
          const [month, day, year] = parts;
          isoDate = `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
        }
      }

      // Last resort: today
      if (!isoDate) {
        isoDate = new Date().toISOString().slice(0, 10);
      }

      window.location.href = `/reports/download/pdf?date=${encodeURIComponent(isoDate)}`;
    });
  }

  // ─── Dark mode observer ───────────────────────────────────────────────────

  const observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      if (
        mutation.type === "attributes" &&
        mutation.attributeName === "class"
      ) {
        setTimeout(function () {
          Chart.helpers.each(Chart.instances, function (instance) {
            const opts = instance.config.options;
            if (opts && opts.scales) {
              const textColor = getTextColor();
              if (opts.scales.y && opts.scales.y.ticks) {
                opts.scales.y.ticks.color = textColor;
              }
              if (opts.scales.x && opts.scales.x.ticks) {
                opts.scales.x.ticks.color = textColor;
              }
            }
            if (opts && opts.plugins && opts.plugins.legend && opts.plugins.legend.labels) {
              opts.plugins.legend.labels.color = getTextColor();
            }
            instance.update();
          });
        }, 100);
      }
    });
  });

  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
});
