// Lógica y renderizado de modales de actividad por usuario
import { getComputedTailwindColor, truncate, formatBytes } from "../utils/helpers.js";

function groupLogsByUrl(logs) {
  const groups = {};
  logs.forEach((log) => {
    if (!groups[log.url]) {
      groups[log.url] = {
        url: log.url,
        responses: {},
        total_requests: 0,
        total_data: 0,
        entryCount: 0,
      };
    }
    const group = groups[log.url];
    group.total_requests += log.request_count;
    group.total_data += log.data_transmitted;
    group.entryCount += 1;
    group.responses[log.response] = (group.responses[log.response] || 0) + log.request_count;
  });

  return Object.values(groups).map((group) => {
    let dominantResponse = 0;
    let maxCount = 0;
    for (const [response, count] of Object.entries(group.responses)) {
      if (count > maxCount) {
        maxCount = count;
        dominantResponse = parseInt(response);
      }
    }
    return {
      url: group.url,
      response: dominantResponse,
      request_count: group.total_requests,
      data_transmitted: group.total_data,
      isGrouped: group.entryCount > 1,
    };
  });
}

function responseBadgeClass(code) {
  if (code >= 100 && code <= 199) return "bg-blue-400";
  if (code >= 200 && code <= 299) return "bg-green-500";
  if (code >= 300 && code <= 399) return "bg-yellow-400";
  if (code >= 400 && code <= 499) return "bg-red-500";
  if (code >= 500 && code <= 599) return "bg-orange-400";
  return "bg-gray-400";
}

export function renderUserModals(modalsContainer, usersData) {
  modalsContainer.innerHTML = usersData
    .map((user, index) => {
      // Calcular resumen de respuestas para filtros
      const responseCounts = {
        informational: 0,
        successful: 0,
        redirection: 0,
        clientError: 0,
        serverError: 0,
        unknown: 0,
      };

      user.logs.forEach((log) => {
        const code = log.response;
        if (code >= 100 && code <= 199) responseCounts.informational++;
        else if (code >= 200 && code <= 299) responseCounts.successful++;
        else if (code >= 300 && code <= 399) responseCounts.redirection++;
        else if (code >= 400 && code <= 499) responseCounts.clientError++;
        else if (code >= 500 && code <= 599) responseCounts.serverError++;
        else responseCounts.unknown++;
      });

      const responseGroups = {
        informational: { icon: "fa-info-circle", color: "text-blue-500", label: "Respuestas informativas (100–199)" },
        successful: { icon: "fa-circle-check", color: "text-green-500", label: "Respuestas exitosas (200–299)" },
        redirection: { icon: "fa-arrow-right", color: "text-yellow-500", label: "Mensajes de redirección (300–399)" },
        clientError: { icon: "fa-circle-xmark", color: "text-red-500", label: "Respuestas de error del cliente (400–499)" },
        serverError: { icon: "fa-triangle-exclamation", color: "text-orange-400", label: "Respuestas de error del servidor (500–599)" },
        unknown: { icon: "fa-question", color: "text-gray-500", label: "Otros" },
      };

      const responseSummary = Object.entries(responseCounts)
        .map(([key, count]) => {
          if (count === 0) return "";
          const { icon, color, label } = responseGroups[key];
          return `
          <div class="filter-icon flex items-center gap-1 text-sm cursor-pointer transition-colors"
               data-filter-type="${key}"
               data-active="true"
               data-color="${color}"
               style="color: ${getComputedTailwindColor(color)}"
               title="${label}"
               onclick="window.toggleResponseFilter(this, ${index})">
            <i class="fa-solid ${icon}"></i>
            <span>${count}</span>
          </div>`;
        })
        .join("");

      const groupedLogs = groupLogsByUrl(user.logs);

      const logsHtml = groupedLogs.length
        ? `
          <div class="log-entries-container grid gap-3">
            ${groupedLogs
              .map((log) => {
                const truncatedUrl = truncate(log.url, 55);
                const isHttps = /:(443|8443)$/.test(log.url);
                const protocol = isHttps ? "https://" : "http://";
                const fullUrl = log.url.startsWith("http") ? log.url : protocol + log.url;
                const badgeClass = responseBadgeClass(log.response);
                const groupClass = log.isGrouped ? "grouped-log-entry" : "";
                const groupIcon = log.isGrouped
                  ? '<i class="fas fa-layer-group text-blue-500 ml-2 text-xs" title="Solicitudes agrupadas"></i>'
                  : "";

                return `
                  <div class="log-entry relative group p-3 bg-white rounded-lg transition-all duration-300 ease-out shadow-md hover:shadow-2xl hover:-translate-y-1 hover:z-10 ${groupClass}"
                       data-response-code="${log.response}">
                    <div class="wave-container absolute inset-0 overflow-hidden rounded-lg">
                      <div class="wave absolute w-full h-full"></div>
                    </div>
                    <div class="relative z-10 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
                      <div class="log-details-grid min-w-0">
                        <div class="flex items-baseline gap-3">
                          <span class="log-url text-sm font-medium text-gray-800 truncate">
                            ${truncatedUrl}
                          </span>
                          ${groupIcon}
                        </div>
                        <div class="mt-1 flex flex-wrap items-center gap-3 text-sm text-gray-600">
                          <span class="response-badge ${badgeClass} inline-block px-2 py-[0.15rem] rounded-md text-[0.65rem] font-medium text-white">
                            ${log.response}
                          </span>
                          <span class="log-meta flex items-center gap-1">
                            <i class="fas fa-hashtag text-gray-400"></i>
                            ${log.request_count} reqs
                          </span>
                          <span class="log-meta flex items-center gap-1">
                            <i class="fas fa-database text-gray-400"></i>
                            ${formatBytes(log.data_transmitted)}
                          </span>
                        </div>
                      </div>
                      <div class="flex items-center gap-2 flex-shrink-0">
                        <i class="fa-solid fa-up-right-from-square text-blue-600 hover:text-blue-800 cursor-pointer text-lg"
                           title="Abrir enlace"
                           onclick="window.open('${fullUrl}', '_blank')"></i>
                      </div>
                    </div>
                  </div>
                `;
              })
              .join("")}
          </div>
        `
        : '<div class="no-logs text-gray-500 text-center py-8">No hay actividad registrada</div>';

      return `
        <div class="logs-modal hidden fixed inset-0 bg-black bg-opacity-50 z-[1000] justify-center items-center transition-all duration-1000 ease-in-out opacity-0" id="logs-modal-${index}">
          <div class="modal-content bg-white p-8 rounded-2xl w-[95%] max-w-[650px] max-h-[85vh] overflow-auto shadow-[0_10px_30px_rgba(0,0,0,0.3)] transition-all duration-1000 ease-in-out relative">
            <button onclick="window.closeLogsModal(${index})" 
                    class="close-btn absolute top-3 right-3 w-8 h-8 flex items-center justify-center bg-red-500 text-white rounded-full z-50 shadow-md transform transition-all duration-300 hover:bg-red-600 hover:scale-110 hover:rotate-90 hover:shadow-lg"
                    title="Cerrar" aria-label="Cerrar">
              <i class="fas fa-times text-base"></i>
            </button>

            <div class="flex flex-col">
              <div class="flex justify-between items-center mb-4">
                <div class="flex items-center gap-2 min-w-0 flex-wrap">
                  <h4 class="logs-title text-base text-gray-500 uppercase tracking-[1px] font-semibold whitespace-nowrap">
                    Actividad reciente - 
                  </h4>
                  <div class="flex items-center gap-2">
                    <span class="username-highlight font-semibold truncate max-w-[120px] text-[#1369ce]">${user.username}</span>
                    <div id="searchBox-${index}" class="relative w-auto h-[38px] bg-white rounded-full transition-all duration-500 ease-in-out shadow-md flex items-center border border-gray-300">
                      <div id="toggleBtn-${index}" class="absolute left-0 top-0 w-[38px] h-[38px] flex items-center justify-center cursor-pointer z-10">
                        <i class="fas fa-search text-blue-600 text-sm"></i>
                      </div>
                      <div id="inputWrapper-${index}" class="ml-[38px] w-0 h-[38px] flex items-center transition-[width] duration-500 ease-in-out overflow-hidden">
                        <input id="mysearch-${index}" type="text" placeholder="Buscar URL..." class="w-full text-xs px-2 py-1 bg-transparent outline-none opacity-0 transition-opacity duration-300 ease-linear min-w-[150px]"/>
                      </div>
                      <button id="clearBtn-${index}" class="absolute right-2 h-full flex items-center justify-center opacity-0 transition-opacity duration-300 text-gray-400 hover:text-gray-700 text-sm" title="Limpiar búsqueda">
                        <i class="fas fa-times text-lg leading-none"></i>
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              <div class="response-summary flex justify-end gap-4 items-center mb-4">
                ${responseSummary}
              </div>
            </div>

            <div class="logs-list mt-2 max-h-[60vh] overflow-y-auto">
              ${logsHtml}
              <div class="no-results hidden text-center py-8 text-gray-500">No se encontraron resultados</div>
            </div>
          </div>
        </div>
      `;
    })
    .join("");

  // Eventos de búsqueda y toggle para cada modal
  usersData.forEach((_, index) => {
    const toggleBtn = document.getElementById(`toggleBtn-${index}`);
    const inputWrapper = document.getElementById(`inputWrapper-${index}`);
    const input = document.getElementById(`mysearch-${index}`);
    const clearBtn = document.getElementById(`clearBtn-${index}`);

    toggleBtn?.addEventListener("click", () => {
      const isExpanding = !inputWrapper.classList.contains("w-[180px]");
      if (isExpanding) {
        inputWrapper.classList.add("w-[180px]");
        input.classList.remove("opacity-0");
        clearBtn.classList.remove("opacity-0");
        setTimeout(() => input.focus(), 300);
      } else {
        inputWrapper.classList.remove("w-[180px]");
        input.classList.add("opacity-0");
        clearBtn.classList.add("opacity-0");
        input.value = "";
        applyFiltersToModal(index);
      }
    });

    clearBtn?.addEventListener("click", () => {
      input.value = "";
      applyFiltersToModal(index);
      input.focus();
    });

    input?.addEventListener("input", () => applyFiltersToModal(index));
  });
}

export function openLogsModal(index) {
  const modal = document.getElementById(`logs-modal-${index}`);
  const overlay = document.getElementById("overlay");
  if (modal) {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    setTimeout(() => {
      modal.classList.remove("opacity-0");
      modal.classList.add("opacity-100");
    }, 10);
  }
  if (overlay) {
    overlay.classList.remove("hidden");
    setTimeout(() => {
      overlay.classList.remove("opacity-0");
      overlay.classList.add("opacity-100");
    }, 10);
  }
}

export function closeLogsModal(index) {
  const modal = document.getElementById(`logs-modal-${index}`);
  const overlay = document.getElementById("overlay");
  if (modal) {
    modal.classList.remove("opacity-100");
    modal.classList.add("opacity-0");
    setTimeout(() => {
      modal.classList.add("hidden");
      modal.classList.remove("flex");
    }, 1000);
  }
  if (overlay) {
    overlay.classList.remove("opacity-100");
    overlay.classList.add("opacity-0");
    setTimeout(() => overlay.classList.add("hidden"), 1000);
  }
}

export function applyFiltersToModal(modalIndex) {
  const modal = document.getElementById(`logs-modal-${modalIndex}`);
  if (!modal) return;
  const entries = modal.querySelectorAll(".log-entry");
  const noResults = modal.querySelector(".no-results");
  const input = document.getElementById(`mysearch-${modalIndex}`);
  const query = (input?.value || "").toLowerCase();

  const filterButtons = modal.querySelectorAll(".response-summary .filter-icon");
  const activeFilters = {};
  filterButtons.forEach((btn) => {
    const type = btn.dataset.filterType;
    activeFilters[type] = btn.dataset.active === "true";
  });

  let visibleCount = 0;
  entries.forEach((entry) => {
    const code = parseInt(entry.dataset.responseCode);
    let type = "unknown";
    if (code >= 100 && code <= 199) type = "informational";
    else if (code >= 200 && code <= 299) type = "successful";
    else if (code >= 300 && code <= 399) type = "redirection";
    else if (code >= 400 && code <= 499) type = "clientError";
    else if (code >= 500 && code <= 599) type = "serverError";

    const passesResponseFilter = activeFilters[type];
    const urlText = entry.querySelector(".log-url")?.textContent.toLowerCase() || "";
    const passesSearchFilter = query === "" || urlText.includes(query);
    const isVisible = passesResponseFilter && passesSearchFilter;
    entry.style.display = isVisible ? "" : "none";
    if (isVisible) visibleCount++;
  });

  if (noResults) {
    noResults.style.display =
      visibleCount === 0 && (query !== "" || Object.values(activeFilters).some((active) => !active))
        ? "block"
        : "none";
  }
}

export function toggleResponseFilter(el, modalIndex) {
  const isActive = el.dataset.active === "true";
  el.dataset.active = isActive ? "false" : "true";
  if (isActive) {
    el.style.color = "#9CA3AF";
  } else {
    el.style.color = getComputedTailwindColor(el.dataset.color);
  }
  applyFiltersToModal(modalIndex);
}
