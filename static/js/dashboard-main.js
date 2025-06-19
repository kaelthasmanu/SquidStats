// ======================================================================
// FICHERO: dashboard-main.js
// Contiene la lógica principal de la página de actividad:
// - Inicialización al cargar el DOM.
// - Carga de datos por fecha.
// - Renderizado de tarjetas de usuario.
// - Búsqueda y paginación de las tarjetas.
// Depende de utils.js y modal-handler.js
// ======================================================================

// Variables globales para esta página, accesibles por las funciones de este fichero.
let allUsersData = []; 
let userCards = [];
let filteredUsers = [];
let currentPage = 1;
const itemsPerPage = 15;


document.addEventListener("DOMContentLoaded", function() {
  // Referencias a elementos del DOM
  const searchInput = document.getElementById("username-search");
  const usersContainer = document.getElementById("users-container");
  const prevBtn = document.getElementById("prev-page");
  const nextBtn = document.getElementById("next-page");
  const firstBtn = document.getElementById("first-page");
  const lastBtn = document.getElementById("last-page");
  const pageNumbers = document.getElementById("page-numbers");
  const dateFilter = document.getElementById("date-filter");
  const clearSearchBtn = document.getElementById("clear-search");

  /**
   * Renderiza las tarjetas de usuario en el contenedor principal.
   */
  function updateUsersData(usersData) {
    window.allUsersData = usersData; // Asigna a la variable global para que el modal la vea
    
    if (!usersData || usersData.length === 0) {
      usersContainer.innerHTML = '<div class="text-gray-500 text-center p-4 col-span-full">No se encontraron datos</div>';
      return;
    }

    usersContainer.innerHTML = usersData.map((user, index) => `
      <div class="user-card group bg-[#f0f2f5] text-center overflow-hidden relative rounded-lg shadow-md w-full max-w-[320px] mx-auto pt-[25px] pb-[70px]" data-username="${user.username.toLowerCase()}">
        <div class="avatar-wrapper relative inline-block h-[100px] w-[100px] mb-[15px] relative z-[1]">
          <div class="avatar-effect absolute w-full h-0 bottom-[135%] left-0 rounded-full bg-[#1369ce] opacity-90 scale-[3] transition-all duration-300 ease-linear z-0 group-hover:h-full"></div>
          <div class="avatar-background absolute inset-0 rounded-full bg-[#1369ce] z-[1]"></div>
          <div class="avatar w-full h-full rounded-full bg-slate-200 flex items-center justify-center text-[2.5rem] text-slate-500 relative transition-all duration-900 ease-in-out group-hover:shadow-[0_0_0_10px_#f7f5ec] group-hover:scale-[0.7] z-[2]">
            <i class="fas fa-user"></i>
          </div>
        </div>
        <div class="user-info mt-[-15px] mb-4 px-[15px]">
          <h3 class="username font-semibold text-[1.2rem] text-[#1369ce] mb-0">${user.username}</h3>
          <h4 class="ip-address text-[0.9rem] text-gray-500">${user.ip}</h4>
        </div>
        <div class="card-action px-[15px] mt-[2px] relative z-[2]">
          <button class="activity-button w-full bg-[#1369ce] text-white font-bold py-2 rounded-md cursor-pointer transition-all duration-300 text-sm hover:bg-[#0d5bb5] hover:-translate-y-0.5 shadow-md" 
                  onclick="window.openLogsModal(${index});">
            ACTIVIDAD
          </button>
        </div>
        <ul class="card-footer absolute bottom-[-80px] left-0 w-full px-4 py-3 bg-[#1369ce] text-white text-sm flex justify-between transition-all duration-500 ease-in-out group-hover:bottom-0 shadow-[0_-4px_6px_rgba(0,0,0,0.2)] z-[1]">
          <li class="inline-block flex flex-col items-center">
            <span class="label text-xs font-light uppercase tracking-wide">Solicitudes:</span>
            <span class="value font-semib">${user.total_requests}</span>
          </li>
          <li class="inline-block flex flex-col items-center">
            <span class="label text-xs font-light uppercase tracking-wide">Datos:</span>
            <span class="value font-semib">${formatBytes(user.total_data)}</span>
          </li>
        </ul>
      </div>
    `).join('');

    usersContainer.insertAdjacentHTML('beforeend', `
      <div class="no-results-msg hidden col-span-full text-center py-12">
        <i class="fas fa-user-slash text-4xl text-gray-400 mb-4"></i>
        <h3 class="text-xl font-semibold text-gray-600">No se encontraron usuarios</h3>
        <p class="text-gray-500 mt-2">Intenta con otro término de búsqueda</p>
      </div>
    `);

    userCards = Array.from(document.querySelectorAll(".user-card"));
    filteredUsers = [...userCards];
    renderPage(1);
  }

  function filterUsers() {
    const searchValue = searchInput.value.toLowerCase().trim();
    clearSearchBtn.style.display = searchValue ? 'flex' : 'none';
    filteredUsers = userCards.filter(card => card.dataset.username.includes(searchValue));
    const noResultsMsg = document.querySelector('.no-results-msg');
    if (noResultsMsg) {
      noResultsMsg.style.display = filteredUsers.length === 0 ? 'block' : 'none';
    }
    renderPage(1);
  }

  function renderPage(page = 1) {
    const totalPages = Math.ceil(filteredUsers.length / itemsPerPage);
    if (page < 1) page = 1;
    if (page > totalPages) page = totalPages || 1;
    currentPage = page;
    userCards.forEach(card => card.style.display = "none");
    const noResultsMsg = document.querySelector('.no-results-msg');
    if (filteredUsers.length === 0) {
      if(noResultsMsg) noResultsMsg.style.display = 'block';
    } else {
      if(noResultsMsg) noResultsMsg.style.display = 'none';
    }
    const start = (page - 1) * itemsPerPage;
    const end = start + itemsPerPage;
    filteredUsers.slice(start, end).forEach(card => card.style.display = "block");
    
    pageNumbers.innerHTML = "";
    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);
    for (let i = startPage; i <= endPage; i++) {
      const btn = document.createElement("button");
      btn.textContent = i;
      btn.className = `pg-btn text-lg px-3 py-1 rounded-full shadow-md font-medium ${ i === currentPage ? "bg-blue-500 text-white" : "bg-white text-gray-800 hover:bg-gray-300"}`;
      btn.onclick = () => renderPage(i);
      pageNumbers.appendChild(btn);
    }
    
    firstBtn.disabled = currentPage === 1;
    prevBtn.disabled = currentPage === 1;
    nextBtn.disabled = currentPage === totalPages;
    lastBtn.disabled = currentPage === totalPages;
  }

  // Event Listeners
  clearSearchBtn.addEventListener("click", () => { searchInput.value = ""; filterUsers(); });
  searchInput.addEventListener("input", filterUsers);
  prevBtn.addEventListener("click", () => renderPage(currentPage - 1));
  nextBtn.addEventListener("click", () => renderPage(currentPage + 1));
  firstBtn.addEventListener("click", () => renderPage(1));
  lastBtn.addEventListener("click", () => renderPage(Math.ceil(filteredUsers.length / itemsPerPage)));

  const today = new Date().toISOString().split('T')[0];
  dateFilter.value = today;
  console.log("fecha actual: ", today);
  dateFilter.addEventListener("change", async (e) => {
    const selectedDate = e.target.value;
    if (!selectedDate) return;
    usersContainer.innerHTML = `<div class="loading-spinner flex justify-center items-center h-64 w-full col-span-full"><svg class="animate-spin h-12 w-12 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg></div>`;
    try {
      const response = await fetch("/get-logs-by-date", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ date: selectedDate })
      });
      if (!response.ok) throw new Error("Error fetching data");
      const data = await response.json();
      updateUsersData(data);
    } catch (error) {
      console.error("Error:", error);
      usersContainer.innerHTML = '<div class="text-red-500 text-center p-4 col-span-full">Error al cargar los datos. Verifique la conexión con el servidor.</div>';
    }
  });
  
  dateFilter.dispatchEvent(new Event("change"));

  initializeModalSearchBar();
});6