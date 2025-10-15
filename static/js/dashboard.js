
import { getLocalDateString } from './utils/fecha.js';
import { truncate, formatBytes } from './utils/helpers.js';
import { fetchUsersPageApi } from './api/logsApi.js';
import { renderUserModals, openLogsModal, closeLogsModal, toggleResponseFilter, applyFiltersToModal } from './ui/modals.js';

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

  async function fetchUsersPage(selectedDate, page, searchTerm = "") {
    try {
      const data = await fetchUsersPageApi(selectedDate, page, searchTerm || undefined);
      updateUsersData(data.users);
      totalPages = data.total_pages;
      totalUsers = data.total;
      currentPage = data.page;
      renderPaginationControls(currentPage, totalPages, selectedDate);
    } catch (error) {
      console.error("Error:", error);
      usersContainer.innerHTML =
        '<div class="text-red-500 text-center p-4 col-span-full">Error al cargar los datos</div>';
    }
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
          fetchUsersPage(selectedDate, i, (searchInput?.value || '').trim());
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
  renderUserModals(modalsContainer, usersData);

  // Actualizar estado de las tarjetas (sin disparar búsqueda de nuevo)
  userCards = Array.from(document.querySelectorAll(".user-card"));
  filteredUsers = [...userCards];
  renderPage(1);
  }

  async function filterUsers() {
    const searchValue = searchInput.value.toLowerCase().trim();
    clearSearchBtn.style.display = searchValue ? "flex" : "none";

    // Fetch server-side para buscar en TODOS los usuarios de la fecha
    const selectedDate = dateFilter.value;
    usersContainer.innerHTML = `
      <div class="loading-spinner flex justify-center items-center h-64 w-full col-span-full">
        <svg class="animate-spin h-12 w-12 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      </div>`;
    await fetchUsersPage(selectedDate, 1, searchValue);

    // Actualiza la paginación con el nuevo total
    renderPage(1);
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

  // Debounce for input search
  let searchDebounceTimeout;
  if (searchInput) {
    searchInput.addEventListener("input", function () {
      if (searchDebounceTimeout) clearTimeout(searchDebounceTimeout);
      searchDebounceTimeout = setTimeout(() => {
        filterUsers();
      }, 2000); // 2 segundos
    });
  }
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
  fetchUsersPage(selectedDate, currentPage - 1, (searchInput?.value || '').trim());
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
          fetchUsersPage(selectedDate, currentPage + 1, (searchInput?.value || '').trim());
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
  fetchUsersPage(dateFilter.value, 1, (searchInput?.value || '').trim());
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
  fetchUsersPage(dateFilter.value, totalPages, (searchInput?.value || '').trim());
    });

  
  const today = getLocalDateString();
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
  await fetchUsersPage(selectedDate, page, (searchInput?.value || '').trim());
    } catch (error) {
      console.error("Error:", error);
      usersContainer.innerHTML =
        '<div class="text-red-500 text-center p-4 col-span-full">Error al cargar los datos</div>';
    }
  });

  // Carga inicial
  dateFilter.dispatchEvent(new Event("change"));
});

// Modal y filtros ahora vienen desde ui/modals.js

  // helpers ahora vienen desde utils/helpers.js

// Hacer funciones disponibles globalmente
window.openLogsModal = openLogsModal;
window.closeLogsModal = closeLogsModal;
window.toggleResponseFilter = toggleResponseFilter;
window.filterLogs = (index) => applyFiltersToModal(index);