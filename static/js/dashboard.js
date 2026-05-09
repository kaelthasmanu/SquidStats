import { openLogsModal, closeLogsModal, toggleResponseFilter, applyFiltersToModal, initLogsModalInteractions } from './ui/modals.js';

document.addEventListener('DOMContentLoaded', () => {
  initLogsModalInteractions();
  window.openLogsModal = openLogsModal;
  window.closeLogsModal = closeLogsModal;
  window.toggleResponseFilter = toggleResponseFilter;
  window.applyFiltersToModal = applyFiltersToModal;
});
