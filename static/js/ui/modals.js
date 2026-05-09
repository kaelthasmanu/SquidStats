// UI interactions for the user activity modals.
import { getComputedTailwindColor } from '../utils/helpers.js';

export function initLogsModalInteractions() {
  document.querySelectorAll('.logs-modal').forEach((modal) => {
    const modalIndex = modal.id?.split('-').pop();
    const toggleBtn = modal.querySelector('.log-search-toggle');
    const inputWrapper = modal.querySelector('.log-search-wrapper');
    const input = modal.querySelector('.log-search-input');
    const clearBtn = modal.querySelector('.log-search-clear');

    toggleBtn?.addEventListener('click', () => {
      if (!inputWrapper || !input || !clearBtn) return;
      const isExpanding = !inputWrapper.classList.contains('w-[180px]');
      if (isExpanding) {
        inputWrapper.classList.add('w-[180px]');
        input.classList.remove('opacity-0');
        clearBtn.classList.remove('opacity-0');
        setTimeout(() => input.focus(), 300);
      } else {
        inputWrapper.classList.remove('w-[180px]');
        input.classList.add('opacity-0');
        clearBtn.classList.add('opacity-0');
        input.value = '';
        applyFiltersToModal(modalIndex);
      }
    });

    clearBtn?.addEventListener('click', () => {
      if (!input) return;
      input.value = '';
      applyFiltersToModal(modalIndex);
      input.focus();
    });

    input?.addEventListener('input', () => applyFiltersToModal(modalIndex));
  });
}

export function openLogsModal(index) {
  const modal = document.getElementById(`logs-modal-${index}`);
  const overlay = document.getElementById('overlay');
  if (modal) {
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    setTimeout(() => {
      modal.classList.remove('opacity-0');
      modal.classList.add('opacity-100');
    }, 10);
  }
  if (overlay) {
    overlay.classList.remove('hidden');
    setTimeout(() => {
      overlay.classList.remove('opacity-0');
      overlay.classList.add('opacity-100');
    }, 10);
  }
}

export function closeLogsModal(index) {
  const modal = document.getElementById(`logs-modal-${index}`);
  const overlay = document.getElementById('overlay');
  if (modal) {
    modal.classList.remove('opacity-100');
    modal.classList.add('opacity-0');
    setTimeout(() => {
      modal.classList.add('hidden');
      modal.classList.remove('flex');
    }, 1000);
  }
  if (overlay) {
    overlay.classList.remove('opacity-100');
    overlay.classList.add('opacity-0');
    setTimeout(() => overlay.classList.add('hidden'), 1000);
  }
}

export function applyFiltersToModal(modalIndex) {
  const modal = document.getElementById(`logs-modal-${modalIndex}`);
  if (!modal) return;
  const entries = modal.querySelectorAll('.log-entry');
  const noResults = modal.querySelector('.no-results');
  const input = document.getElementById(`mysearch-${modalIndex}`);
  const query = (input?.value || '').toLowerCase();

  const filterButtons = modal.querySelectorAll('.response-summary .filter-icon');
  const activeFilters = {};
  filterButtons.forEach((btn) => {
    const type = btn.dataset.filterType;
    activeFilters[type] = btn.dataset.active === 'true';
  });

  let visibleCount = 0;
  entries.forEach((entry) => {
    const code = parseInt(entry.dataset.responseCode, 10);
    let type = 'unknown';
    if (code >= 100 && code <= 199) type = 'informational';
    else if (code >= 200 && code <= 299) type = 'successful';
    else if (code >= 300 && code <= 399) type = 'redirection';
    else if (code >= 400 && code <= 499) type = 'clientError';
    else if (code >= 500 && code <= 599) type = 'serverError';

    const passesResponseFilter = activeFilters[type];
    const urlText = entry.querySelector('.log-url')?.textContent.toLowerCase() || '';
    const passesSearchFilter = query === '' || urlText.includes(query);
    const isVisible = passesResponseFilter && passesSearchFilter;
    entry.style.display = isVisible ? '' : 'none';
    if (isVisible) visibleCount++;
  });

  if (noResults) {
    noResults.style.display =
      visibleCount === 0 && (query !== '' || Object.values(activeFilters).some((active) => !active))
        ? 'block'
        : 'none';
  }
}

export function toggleResponseFilter(el, modalIndex) {
  const isActive = el.dataset.active === 'true';
  el.dataset.active = isActive ? 'false' : 'true';
  if (isActive) {
    el.style.color = '#9CA3AF';
  } else {
    el.style.color = getComputedTailwindColor(el.dataset.color);
  }
  applyFiltersToModal(modalIndex);
}
