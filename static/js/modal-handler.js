// ======================================================================
// FICHERO: modal-handler.js (CORREGIDO)
//
// CAMBIOS REALIZADOS:
// 1.  NUEVO: Se añadió la función `getResponseCategory` para clasificar códigos HTTP.
// 2.  MODIFICADO: `groupLogsByUrl` ahora agrupa por URL Y por categoría de respuesta.
//     Esto soluciona la discrepancia en los contadores del modal. Una misma URL puede
//     aparecer ahora en varias filas si tuvo respuestas de distintas categorías (ej. 2xx y 5xx).
// 3.  CORREGIDO: En `openLogsModal`, el conteo inicial de respuestas ahora usa rangos
//     estrictos y correctos (ej. 500-599) para mayor precisión.
// 4.  CORREGIDO: En `renderLogEntries`, el filtrado ahora usa la nueva función
//     `getResponseCategory` para asegurar la consistencia.
// ======================================================================


// NUEVO: Función auxiliar para obtener la categoría de una respuesta HTTP.
function getResponseCategory(code) {
    if (code >= 100 && code < 200) return 'informational';
    if (code >= 200 && code < 300) return 'successful';
    if (code >= 300 && code < 400) return 'redirection';
    if (code >= 400 && code < 500) return 'clientError';
    if (code >= 500 && code < 600) return 'serverError';
    return 'unknown';
}

/**
 * MODIFICADO: Agrupa los logs por URL y por CATEGORÍA de respuesta.
 * Esta es la corrección principal para que los contadores del modal coincidan con las filas mostradas.
 * @param {Array} logs - Array de logs brutos del usuario.
 * @returns {Array} Logs agrupados.
 */
function groupLogsByUrl(logs) {
    const groups = {};
    logs.forEach(log => {
        // La clave de agrupación ahora incluye la URL y la categoría de la respuesta.
        const category = getResponseCategory(log.response);
        const key = `${log.url}|${category}`;

        if (!groups[key]) {
            groups[key] = {
                url: log.url,
                responses: {}, // Para contar frecuencia de códigos de respuesta dentro del grupo
                total_requests: 0,
                total_data: 0,
                entryCount: 0
            };
        }
        const group = groups[key];
        group.total_requests += log.request_count;
        group.total_data += log.data_transmitted;
        group.entryCount += 1;

        if (group.responses[log.response]) {
            group.responses[log.response] += log.request_count;
        } else {
            group.responses[log.response] = log.request_count;
        }
    });

    return Object.values(groups).map(group => {
        // Determinar el código de respuesta dominante DENTRO del grupo
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
            response: dominantResponse, // El código más común dentro de esa URL y categoría
            request_count: group.total_requests,
            data_transmitted: group.total_data,
            isGrouped: group.entryCount > 1
        };
    });
}

/**
 * Inicializa la barra de búsqueda animada dentro del modal.
 */
function initializeModalSearchBar() {
    const toggleBtn = document.getElementById('modal-toggle-btn');
    const inputWrapper = document.getElementById('modal-input-wrapper');
    const searchInput = document.getElementById('modal-search-input');
    const clearBtn = document.getElementById('modal-clear-btn');
    const modal = document.getElementById('generic-user-modal');

    if (!toggleBtn) return;

    toggleBtn.addEventListener("click", () => {
        const isExpanding = !inputWrapper.classList.contains("w-[180px]");
        if (isExpanding) {
            inputWrapper.classList.add("w-[180px]");
            searchInput.classList.remove("opacity-0");
            clearBtn.classList.remove("opacity-0");
            setTimeout(() => searchInput.focus(), 300);
        } else {
            inputWrapper.classList.remove("w-[180px]");
            searchInput.classList.add("opacity-0");
            clearBtn.classList.add("opacity-0");
            if (searchInput.value !== '') {
                searchInput.value = "";
                const userIndex = modal.dataset.currentUserIndex;
                if (userIndex !== undefined) renderLogEntries(userIndex);
            }
        }
    });

    clearBtn.addEventListener("click", () => {
        searchInput.value = "";
        const userIndex = modal.dataset.currentUserIndex;
        if (userIndex !== undefined) renderLogEntries(userIndex);
        searchInput.focus();
    });

    searchInput.addEventListener("input", () => {
        const userIndex = modal.dataset.currentUserIndex;
        if (userIndex !== undefined) renderLogEntries(userIndex);
    });
}


function renderLogEntries(userIndex) {
    const user = window.allUsersData[userIndex];
    if (!user) return;

    const logsList = document.getElementById('modal-logs-list');
    const searchInput = document.getElementById('modal-search-input');
    const noResults = document.getElementById('modal-no-results');
    const summaryContainer = document.getElementById('modal-response-summary');
    const query = searchInput.value.toLowerCase().trim();
    
    const activeFilters = {};
    summaryContainer.querySelectorAll('.filter-icon').forEach(btn => {
        activeFilters[btn.dataset.filterType] = btn.dataset.active === "true";
    });
    
    const allLogs = groupLogsByUrl(user.logs);
    const filteredLogs = allLogs.filter(log => {
        const urlText = log.url.toLowerCase();
        const passesSearchFilter = query === "" || urlText.includes(query);
        if (!passesSearchFilter) return false;

        // CORREGIDO: Usar la función getResponseCategory para consistencia
        const type = getResponseCategory(log.response);
        return activeFilters[type];
    });
    
    noResults.style.display = filteredLogs.length === 0 ? 'block' : 'none';
    logsList.style.display = filteredLogs.length > 0 ? 'grid' : 'none';
    
    logsList.innerHTML = filteredLogs.map(log => {
        const truncatedUrl = truncate(log.url, 55);
        const isHttps = /:(443|8443)$/.test(log.url);
        const protocol = isHttps ? 'https://' : 'http://';
        const fullUrl = log.url.startsWith('http') ? log.url : protocol + log.url;
        
        let badgeClass = 'bg-gray-400';
        if (log.response >= 100 && log.response <= 199) badgeClass = 'bg-blue-400';
        else if (log.response >= 200 && log.response <= 299) badgeClass = 'bg-green-500';
        else if (log.response >= 300 && log.response <= 399) badgeClass = 'bg-yellow-400';
        else if (log.response >= 400 && log.response <= 499) badgeClass = 'bg-red-500';
        else if (log.response >= 500 && log.response <= 599) badgeClass = 'bg-orange-400';

        const groupIcon = log.isGrouped ? '<i class="fas fa-layer-group text-blue-500 ml-2 text-xs" title="Solicitudes agrupadas"></i>' : '';

        return `
          <div class="log-entry relative group p-3 bg-white rounded-lg transition-all duration-300 ease-out shadow-md hover:shadow-2xl hover:-translate-y-1 hover:z-10" data-response-code="${log.response}">
            <div class="wave-container absolute inset-0 overflow-hidden rounded-lg">
              <div class="wave absolute w-full h-full"></div>
            </div>
            <div class="relative z-10 grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
              <div class="log-details-grid min-w-0">
                <div class="flex items-baseline gap-3">
                    <span class="log-url text-sm font-medium text-gray-800 truncate" title="${log.url}">
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
                <a href="${fullUrl}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-800 cursor-pointer text-lg" title="Abrir enlace en nueva pestaña">
                    <i class="fa-solid fa-up-right-from-square"></i>
                </a>
              </div>
            </div>
          </div>`;
    }).join('');
}


window.toggleResponseFilter = function(el) {
    const isActive = el.dataset.active === "true";
    el.dataset.active = isActive ? "false" : "true";
    
    if (isActive) {
        el.style.color = "#9CA3AF"; 
        el.classList.add('opacity-75');
    } else {
        el.style.color = getComputedTailwindColor(el.dataset.color);
        el.classList.remove('opacity-75');
    }

    const modal = document.getElementById('generic-user-modal');
    const userIndex = modal.dataset.currentUserIndex;
    renderLogEntries(userIndex);
}


window.openLogsModal = function(userIndex) {
    const user = window.allUsersData[userIndex];
    if (!user) return;

    const modal = document.getElementById('generic-user-modal');
    const overlay = document.getElementById('overlay');
    const usernameEl = document.getElementById('modal-username');
    const searchInput = document.getElementById('modal-search-input');
    const summaryContainer = document.getElementById('modal-response-summary');

    usernameEl.textContent = user.username;
    modal.dataset.currentUserIndex = userIndex;

    const responseCounts = { informational: 0, successful: 0, redirection: 0, clientError: 0, serverError: 0, unknown: 0 };
    
    // CORREGIDO: Se usan rangos exactos para cada categoría, asegurando un conteo preciso.
    user.logs.forEach(log => {
        const code = log.response;
        if (code >= 100 && code <= 199) responseCounts.informational++;
        else if (code >= 200 && code <= 299) responseCounts.successful++;
        else if (code >= 300 && code <= 399) responseCounts.redirection++;
        else if (code >= 400 && code <= 499) responseCounts.clientError++;
        else if (code >= 500 && code <= 599) responseCounts.serverError++;
        else responseCounts.unknown++;
    });

    const responseGroups = {
        informational: { icon: 'fa-info-circle', color: 'text-blue-500', label: 'Respuestas informativas (100–199)' },
        successful: { icon: 'fa-circle-check', color: 'text-green-500', label: 'Respuestas exitosas (200–299)' },
        redirection: { icon: 'fa-arrow-right', color: 'text-yellow-500', label: 'Mensajes de redirección (300–399)' },
        clientError: { icon: 'fa-circle-xmark', color: 'text-red-500', label: 'Respuestas de error del cliente (400–499)' },
        serverError: { icon: 'fa-triangle-exclamation', color: 'text-orange-400', label: 'Respuestas de error del servidor (500–599)' },
        unknown: { icon: 'fa-question', color: 'text-gray-500', label: 'Otros' }
    };
    
    summaryContainer.innerHTML = Object.entries(responseCounts).map(([key, count]) => {
        if (count === 0) return '';
        const { icon, color, label } = responseGroups[key];
        return `
          <div class="filter-icon flex items-center gap-1 text-sm cursor-pointer transition-colors"
               data-filter-type="${key}" data-active="true" data-color="${color}"
               style="color: ${getComputedTailwindColor(color)}"
               title="${label}" onclick="window.toggleResponseFilter(this)">
            <i class="fa-solid ${icon}"></i>
            <span>${count}</span>
          </div>`;
    }).join('');
    
    renderLogEntries(userIndex);

    searchInput.value = '';
    
    overlay.classList.remove('hidden');
    modal.classList.remove('hidden');
    setTimeout(() => {
        overlay.classList.remove('opacity-0');
        modal.classList.remove('opacity-0');
    }, 10);
}


window.closeLogsModal = function() {
    const modal = document.getElementById('generic-user-modal');
    const overlay = document.getElementById('overlay');
    overlay.classList.add('opacity-0');
    modal.classList.add('opacity-0');
    setTimeout(() => {
        overlay.classList.add('hidden');
        modal.classList.add('hidden');
    }, 300);
}