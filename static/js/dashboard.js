
import { getLocalDateString } from './utils/fecha.js';

document.addEventListener("DOMContentLoaded", function () {
  // Referencias a elementos del DOM
  const searchInput = document.getElementById("username-search");
  const usersContainer = document.getElementById("users-container");
  const modalsContainer = document.getElementById("modals-container");
  const prevBtn = document.getElementById("prev-page");
  const nextBtn = document.getElementById("next-page");
  const firstBtn = document.getElementById("first-page");
  const lastBtn = document.getElementById("last-page");
  const pageNumbers = document.getElementById("page-numbers");
  const dateFilter = document.getElementById("date-filter");
  const clearSearchBtn = document.getElementById("clear-search");

  // Variables de estado
  let userCards = [];
  let filteredUsers = [];
  let currentPage = 1;
  const itemsPerPage = 15;
  let page = 1;

  // NUEVO: Paginación real usando backend
  let totalPages = 1;
  let totalUsers = 0;

  function fetchUsersPage(selectedDate, page) {
    fetch("/get-logs-by-date", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: selectedDate, page }),
    })
      .then((response) => {
        return response.json().then((data) => {
          return data;
        });
      })
      .then((data) => {
        updateUsersData(data.users);
        totalPages = data.total_pages;
        totalUsers = data.total; // <-- Guarda el total de usuarios
        currentPage = data.page;
        renderPaginationControls(currentPage, totalPages, selectedDate);
      })
      .catch((error) => {
        console.error("Error:", error);
        usersContainer.innerHTML =
          '<div class="text-red-500 text-center p-4 col-span-full">Error al cargar los datos</div>';
      });
  }

  function renderPaginationControls(page, totalPages, selectedDate) {
    // Verifica que los botones existen antes de usarlos
    if (prevBtn) prevBtn.disabled = page <= 1;
    if (firstBtn) firstBtn.disabled = page <= 1;
    if (nextBtn) nextBtn.disabled = page >= totalPages;
    if (lastBtn) lastBtn.disabled = page >= totalPages;
    // Números de página
    if (pageNumbers) {
      pageNumbers.innerHTML = "";
      let start = Math.max(1, page - 2);
      let end = Math.min(totalPages, page + 2);
      if (page <= 3) end = Math.min(5, totalPages);
      if (page > totalPages - 2) start = Math.max(1, totalPages - 4);
      for (let i = start; i <= end; i++) {
        const btn = document.createElement("button");
        btn.textContent = i;
        btn.className =
          "pg-btn px-3 py-1 rounded " +
          (i === page ? "bg-blue-600 text-white" : "bg-white text-blue-600");
        btn.disabled = i === page;
        btn.onclick = () => {
          usersContainer.innerHTML = `
            <div class=\"loading-spinner flex justify-center items-center h-64 w-full col-span-full\">
              <svg class=\"animate-spin h-12 w-12 text-blue-500\" xmlns=\"http://www.w3.org/2000/svg\" fill=\"none\" viewBox=\"0 0 24 24\">
                <circle class=\"opacity-25\" cx=\"12\" cy=\"12\" r=\"10\" stroke=\"currentColor\" stroke-width=\"4\"></circle>
                <path class=\"opacity-75\" fill=\"currentColor\" d=\"M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z\"></path>
              </svg>
            </div>`;
          fetchUsersPage(selectedDate,i);
        };
        pageNumbers.appendChild(btn);
      }
    }
  }

  function updateUsersData(usersData) {
    if (!usersData || usersData.length === 0) {
      usersContainer.innerHTML =
        '<div class="text-gray-500 text-center p-4 col-span-full">No se encontraron datos</div>';
      return;
    }

    // Generar tarjetas de usuario
    usersContainer.innerHTML = usersData
      .map(
        (user, index) => `
      <div class="user-card group bg-[#f0f2f5] text-center overflow-hidden relative rounded-lg shadow-md w-full max-w-[320px] mx-auto pt-[25px] pb-[70px]" data-username="${user.username.toLowerCase()}">
        <div class="avatar-wrapper relative inline-block h-[100px] w-[100px] mb-[15px] z-[1]">
          <div class="avatar-effect absolute w-full h-0 bottom-[135%] left-0 rounded-full bg-[#1369ce] opacity-90 scale-[3] transition-all duration-300 ease-linear z-0 group-hover:h-full"></div>
          <div class="avatar-background absolute inset-0 rounded-full bg-[#1369ce] z-[1]"></div>
          <div class="avatar w-full h-full rounded-full bg-slate-200 flex items-center justify-center text-[2.5rem] text-slate-500 relative transition-all duration-900 ease-in-out group-hover:shadow-[0_0_0_10px_#f7f5ec] group-hover:scale-[0.7] z-[2]">
            <i class="fas fa-user"></i>
          </div>
        </div>
        
        <div class="user-info mt-[-15px] mb-4 px-[15px]">
          <h3 class="username font-semibold text-[1.2rem] text-[#1369ce] mb-0">${
            user.username
          }</h3>
          <h4 class="ip-address text-[0.9rem] text-gray-500">${user.ip}</h4>
        </div>
        
        <div class="card-action px-[15px] mt-[2px] relative z-[2]">
          <button class="activity-button w-full bg-[#1369ce] text-white font-bold py-2 rounded-md cursor-pointer transition-all duration-300 text-sm hover:bg-[#0d5bb5] hover:-translate-y-0.5 shadow-md" 
                  onclick="window.openLogsModal(${index});">
            ACTIVIDAD
          </button>
        </div>
        
        <ul class="card-footer absolute bottom-[-80px] left-0 w-full px-4 py-3 bg-[#1369ce] text-white text-sm flex justify-between transition-all duration-500 ease-in-out group-hover:bottom-0 shadow-[0_-4px_6px_rgba(0,0,0,0.2)] z-[1]">
          <li class="flex flex-col items-center">
            <span class="label text-xs font-light uppercase tracking-wide">Solicitudes:</span>
            <span class="value font-semib">${user.total_requests}</span>
          </li>
          <li class="flex flex-col items-center">
            <span class="label text-xs font-light uppercase tracking-wide">Datos:</span>
            <span class="value font-semib">${formatBytes(
              user.total_data
            )}</span>
          </li>
        </ul>
      </div>
    `
      )
      .join("");

    // Mensaje de no resultados
    usersContainer.insertAdjacentHTML(
      "beforeend",
      `
      <div class="no-results-msg hidden col-span-full text-center py-12">
          <i class="fas fa-user-slash text-4xl text-gray-400 mb-4"></i>
          <h3 class="text-xl font-semibold text-gray-600">
              No se encontraron usuarios
          </h3>
          <p class="text-gray-500 mt-2">
              Intenta con otro término de búsqueda
          </p>
      </div>
    `
    );

    function groupLogsByUrl(logs) {
      const groups = {};
      logs.forEach((log) => {
        if (!groups[log.url]) {
          groups[log.url] = {
            url: log.url,
            responses: {}, // Para contar frecuencia de códigos de respuesta
            total_requests: 0,
            total_data: 0,
            entryCount: 0, // Cuántas entradas originales se agruparon
          };
        }
        const group = groups[log.url];
        group.total_requests += log.request_count;
        group.total_data += log.data_transmitted;
        group.entryCount += 1;

        // Contar frecuencia de códigos de respuesta
        if (group.responses[log.response]) {
          group.responses[log.response] += log.request_count;
        } else {
          group.responses[log.response] = log.request_count;
        }
      });

      return Object.values(groups).map((group) => {
        // Determinar el código de respuesta dominante (el más frecuente)
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
          isGrouped: group.entryCount > 1, // Indica si es un grupo (más de una entrada original)
        };
      });
    }

    // Generar modales para cada usuario
    modalsContainer.innerHTML = usersData
      .map((user, index) => {
        // Contar los tipos de respuestas para los filtros
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

        // Configuración de grupos de respuestas
        const responseGroups = {
          informational: {
            icon: "fa-info-circle",
            color: "text-blue-500",
            label: "Respuestas informativas (100–199)",
          },
          successful: {
            icon: "fa-circle-check",
            color: "text-green-500",
            label: "Respuestas exitosas (200–299)",
          },
          redirection: {
            icon: "fa-arrow-right",
            color: "text-yellow-500",
            label: "Mensajes de redirección (300–399)",
          },
          clientError: {
            icon: "fa-circle-xmark",
            color: "text-red-500",
            label: "Respuestas de error del cliente (400–499)",
          },
          serverError: {
            icon: "fa-triangle-exclamation",
            color: "text-orange-400",
            label: "Respuestas de error del servidor (500–599)",
          },
          unknown: {
            icon: "fa-question",
            color: "text-gray-500",
            label: "Otros",
          },
        };

        // Resumen de respuestas
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

        // Agrupar logs por URL para mostrar en el modal
        const groupedLogs = groupLogsByUrl(user.logs);

        // Generar HTML del modal
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
        <span class="username-highlight font-semibold truncate max-w-[120px] text-[#1369ce]">${
          user.username
        }</span>
        
        <!-- Contenedor de búsqueda al lado del nombre de usuario -->
        <div id="searchBox-${index}" class="relative w-auto h-[38px] bg-white rounded-full transition-all duration-500 ease-in-out shadow-md flex items-center border border-gray-300">
          <div id="toggleBtn-${index}" class="absolute left-0 top-0 w-[38px] h-[38px] flex items-center justify-center cursor-pointer z-10">
            <i class="fas fa-search text-blue-600 text-sm"></i>
          </div>
          <div id="inputWrapper-${index}" class="ml-[38px] w-0 h-[38px] flex items-center transition-[width] duration-500 ease-in-out overflow-hidden">
            <input id="mysearch-${index}" type="text" placeholder="Buscar URL..." class="w-full text-xs px-2 py-1 bg-transparent outline-none opacity-0 transition-opacity duration-300 ease-linear min-w-[150px]"/>
          </div>
          <button id="clearBtn-${index}" 
                class="absolute right-2 h-full flex items-center justify-center opacity-0 transition-opacity duration-300 text-gray-400 hover:text-gray-700 text-sm" 
                title="Limpiar búsqueda">
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
              ${
                groupedLogs.length > 0
                  ? `
                <div class="log-entries-container grid gap-3">
                  ${groupedLogs
                    .map((log) => {
                      const truncatedUrl = truncate(log.url, 55);
                      const isHttps = /:(443|8443)$/.test(log.url);
                      const protocol = isHttps ? "https://" : "http://";
                      const fullUrl = log.url.startsWith("http")
                        ? log.url
                        : protocol + log.url;

                      // Determinar clase de badge según el código de respuesta
                      let badgeClass = "bg-gray-400";
                      if (log.response >= 100 && log.response <= 199)
                        badgeClass = "bg-blue-400";
                      else if (log.response >= 200 && log.response <= 299)
                        badgeClass = "bg-green-500";
                      else if (log.response >= 300 && log.response <= 399)
                        badgeClass = "bg-yellow-400";
                      else if (log.response >= 400 && log.response <= 499)
                        badgeClass = "bg-red-500";
                      else if (log.response >= 500 && log.response <= 599)
                        badgeClass = "bg-orange-400";

                      // Clase CSS adicional para entradas agrupadas
                      const groupClass = log.isGrouped
                        ? "grouped-log-entry"
                        : "";
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
                  : '<div class="no-logs text-gray-500 text-center py-8">No hay actividad registrada</div>'
              }
              <div class="no-results hidden text-center py-8 text-gray-500">
                No se encontraron resultados
              </div>
            </div>
          </div>
        </div>
      `;
      })
      .join("");

    // Configurar eventos de búsqueda en modales
    usersData.forEach((_, index) => {
      const toggleBtn = document.getElementById(`toggleBtn-${index}`);
      const inputWrapper = document.getElementById(`inputWrapper-${index}`);
      const input = document.getElementById(`mysearch-${index}`);
      const clearBtn = document.getElementById(`clearBtn-${index}`);

      toggleBtn.addEventListener("click", () => {
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
          // SOLUCIÓN: Ahora usa la función unificada de filtrado
          applyFiltersToModal(index);
        }
      });

      clearBtn.addEventListener("click", () => {
        input.value = "";
        // SOLUCIÓN: Ahora usa la función unificada de filtrado
        applyFiltersToModal(index);
        input.focus();
      });

      input.addEventListener("input", () => {
        // SOLUCIÓN: Ahora usa la función unificada de filtrado
        applyFiltersToModal(index);
      });
    });

    // Actualizar estado de las tarjetas
    userCards = Array.from(document.querySelectorAll(".user-card"));
    filteredUsers = [...userCards];
    filterUsers();
  }

  function filterUsers() {
    const searchValue = searchInput.value.toLowerCase().trim();
    clearSearchBtn.style.display = searchValue ? "flex" : "none";

    filteredUsers = userCards.filter((card) => {
      return searchValue === "" || card.dataset.username.includes(searchValue);
    });

    const noResultsMsg = document.querySelector(".no-results-msg");
    if (noResultsMsg) {
      noResultsMsg.style.display =
        filteredUsers.length === 0 ? "block" : "none";
    }

    renderPage(page);
  }

  function renderPage(page) {
    if (page < 1 || page === null) page = 1;
    currentPage = page;

    // Ocultar todas las tarjetas
    userCards.forEach((card) => (card.style.display = "none"));

    // Manejar caso sin resultados
    const noResultsMsg = document.querySelector(".no-results-msg");
    if (filteredUsers.length === 0) {
      if (!noResultsMsg) {
        usersContainer.innerHTML = `
          <div class="no-results-msg col-span-full text-center py-12">
              <i class="fas fa-user-slash text-4xl text-gray-400 mb-4"></i>
              <h3 class="text-xl font-semibold text-gray-600">
                  No se encontraron usuarios
              </h3>
              <p class="text-gray-500 mt-2">
                  Intenta con otro término de búsqueda
              </p>
          </div>
        `;
      } else {
        noResultsMsg.style.display = "block";
      }

      // Deshabilitar paginación
      pageNumbers.innerHTML = "";
      firstBtn.disabled = true;
      prevBtn.disabled = true;
      nextBtn.disabled = true;
      lastBtn.disabled = true;
      return;
    } else if (noResultsMsg) {
      noResultsMsg.style.display = "none";
    }

    // Mostrar usuarios de la página actual
    const start = (page - 1) * itemsPerPage;
    const end = start + itemsPerPage;
    const currentUsers = filteredUsers.slice(start, end);
    currentUsers.forEach((card) => (card.style.display = "block"));

    // Actualizar controles de paginación
    pageNumbers.innerHTML = "";
    const startPage = Math.max(1, currentPage - 1);
    const endPage = Math.min(totalPages, startPage + 2);

    for (let i = startPage; i <= endPage; i++) {
      const btn = document.createElement("button");
      btn.textContent = i;
      btn.className = `pg-btn text-lg px-3 py-1 rounded-full shadow-md font-medium ${
        i === currentPage
          ? "bg-blue-500 text-white"
          : "bg-gray-100 text-gray-800 hover:bg-gray-300"
      }`;
      btn.onclick = () => renderPage(i);
      pageNumbers.appendChild(btn);
    }

    // Actualizar estado de botones de navegación
    firstBtn.disabled = currentPage === 1;
    prevBtn.disabled = currentPage === 1;
    nextBtn.disabled = currentPage === totalPages;
    lastBtn.disabled = currentPage === totalPages;
  }

  // Event listeners
  if (clearSearchBtn) {
    clearSearchBtn.addEventListener("click", () => {
      searchInput.value = "";
      clearSearchBtn.style.display = "none";
      filterUsers();
    });
  }

  if (searchInput) searchInput.addEventListener("input", filterUsers);
  if (prevBtn)
    prevBtn.addEventListener("click", () => {
      if (currentPage > 1) {
        const selectedDate = dateFilter.value;
        usersContainer.innerHTML = `
          <div class="loading-spinner flex justify-center items-center h-64 w-full col-span-full">
            <svg class="animate-spin h-12 w-12 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
          </div>`;
        fetchUsersPage(selectedDate, currentPage - 1);
      }
    });
  if (nextBtn)
    nextBtn &&
      nextBtn.addEventListener("click", () => {
        if (currentPage < totalPages) {
          const selectedDate = dateFilter.value;
          usersContainer.innerHTML = `
            <div class="loading-spinner flex justify-center items-center h-64 w-full col-span-full">
              <svg class="animate-spin h-12 w-12 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            </div>`;
          fetchUsersPage(selectedDate, currentPage + 1);
        }
      });
  if (firstBtn)
    firstBtn.addEventListener("click", () => {
      usersContainer.innerHTML = `
        <div class="loading-spinner flex justify-center items-center h-64 w-full col-span-full">
          <svg class="animate-spin h-12 w-12 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
        </div>`;
      fetchUsersPage(dateFilter.value, 1);
    });
  if (lastBtn)
    lastBtn.addEventListener("click", () => {
      usersContainer.innerHTML = `
        <div class="loading-spinner flex justify-center items-center h-64 w-full col-span-full">
          <svg class="animate-spin h-12 w-12 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
        </div>`;
      fetchUsersPage(dateFilter.value, totalPages);
    });

  
  const today = getLocalDateString();
  console.log("Fecha actual:", today);
  if (!dateFilter.value) dateFilter.value = today;

  // Event listener para cambio de fecha
  dateFilter.addEventListener("change", async (e) => {
    const selectedDate = e.target.value;
    if (!selectedDate) return;

    try {
      // Mostrar spinner de carga
      usersContainer.innerHTML = `
        <div class="loading-spinner flex justify-center items-center h-64 w-full col-span-full">
          <svg class="animate-spin h-12 w-12 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
        </div>`;

      // Obtener datos del servidor
      await fetchUsersPage(selectedDate, page);
    } catch (error) {
      console.error("Error:", error);
      usersContainer.innerHTML =
        '<div class="text-red-500 text-center p-4 col-span-full">Error al cargar los datos</div>';
    }
  });

  // Carga inicial
  dateFilter.dispatchEvent(new Event("change"));
});

function openLogsModal(index) {
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

function closeLogsModal(index) {
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
    setTimeout(() => {
      overlay.classList.add("hidden");
    }, 1000);
  }
}

function applyFiltersToModal(modalIndex) {
  const modal = document.getElementById(`logs-modal-${modalIndex}`);
  const entries = modal.querySelectorAll(".log-entry");
  const noResults = modal.querySelector(".no-results");
  const input = document.getElementById(`mysearch-${modalIndex}`);
  const query = input.value.toLowerCase();

  // Obtener estados actuales de todos los filtros de respuesta
  const filterButtons = modal.querySelectorAll(
    ".response-summary .filter-icon"
  );
  const activeFilters = {};
  filterButtons.forEach((btn) => {
    const type = btn.dataset.filterType;
    activeFilters[type] = btn.dataset.active === "true";
  });

  let visibleCount = 0;

  entries.forEach((entry) => {
    const code = parseInt(entry.dataset.responseCode);
    let type = "unknown";

    // Determinar categoría de respuesta basado en el código HTTP
    if (code >= 100 && code <= 199) type = "informational";
    else if (code >= 200 && code <= 299) type = "successful";
    else if (code >= 300 && code <= 399) type = "redirection";
    else if (code >= 400 && code <= 499) type = "clientError";
    else if (code >= 500 && code <= 599) type = "serverError";

    // Verificar ambos filtros: respuesta y búsqueda
    const passesResponseFilter = activeFilters[type];
    const urlText =
      entry.querySelector(".log-url")?.textContent.toLowerCase() || "";
    const passesSearchFilter = query === "" || urlText.includes(query);

    // Mostrar solo si pasa ambos filtros
    const isVisible = passesResponseFilter && passesSearchFilter;
    entry.style.display = isVisible ? "" : "none";

    if (isVisible) visibleCount++;
  });

  // Mostrar mensaje "no resultados" solo cuando hay filtros activos y no hay coincidencias
  noResults.style.display =
    visibleCount === 0 &&
    (query !== "" || Object.values(activeFilters).some((active) => !active))
      ? "block"
      : "none";
}

function toggleResponseFilter(el, modalIndex) {
  // Toggle del estado activo
  const isActive = el.dataset.active === "true";
  el.dataset.active = isActive ? "false" : "true";

  // Actualizar apariencia visual
  if (isActive) {
    el.style.color = "#9CA3AF"; // Color gris para inactivo
  } else {
    el.style.color = getComputedTailwindColor(el.dataset.color); // Color original
  }

  // SOLUCIÓN: Ahora aplica ambos tipos de filtros
  applyFiltersToModal(modalIndex);
}

function filterLogs(index) {
  // SOLUCIÓN: Ahora aplica ambos tipos de filtros
  applyFiltersToModal(index);
}

function getComputedTailwindColor(className) {  
  const colorMap = {
    "text-blue-500": "#3B82F6",
    "text-green-500": "#22C55E",
    "text-yellow-500": "#EAB308",
    "text-red-500": "#EF4444",
    "text-orange-400": "#FB923C",
    "text-gray-500": "#6B7280",
  };
  return colorMap[className] || "#6B7280";
}

function truncate(str, n) {
  return str.length > n ? str.slice(0, n - 1) + "..." : str;
}

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex++;
  }
  return `${value.toFixed(2)} ${units[unitIndex]}`;
}

// Hacer funciones disponibles globalmente
window.openLogsModal = openLogsModal;
window.closeLogsModal = closeLogsModal;
window.toggleResponseFilter = toggleResponseFilter;
window.filterLogs = filterLogs;