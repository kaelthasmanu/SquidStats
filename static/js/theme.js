/**
 * theme.js
 * Dark/light mode toggle with localStorage persistence and system preference fallback.
 * Must be loaded BEFORE the body renders to prevent flash of wrong theme.
 */

(function () {
  const STORAGE_KEY = 'squidstats-theme';
  const DARK_CLASS = 'dark';

  function getPreference() {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'dark' || stored === 'light') return stored;
    // Fall back to system preference
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    if (theme === 'dark') {
      document.documentElement.classList.add(DARK_CLASS);
    } else {
      document.documentElement.classList.remove(DARK_CLASS);
    }
  }

  function toggleTheme() {
    const current = document.documentElement.classList.contains(DARK_CLASS) ? 'dark' : 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    localStorage.setItem(STORAGE_KEY, next);
    applyTheme(next);
    updateToggleButtons(next);
  }

  function updateToggleButtons(theme) {
    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      const iconEl = btn.querySelector('[data-theme-icon]');
      const labelEl = btn.querySelector('[data-theme-label]');
      if (theme === 'dark') {
        if (iconEl) { iconEl.classList.remove('fa-moon'); iconEl.classList.add('fa-sun'); }
        if (labelEl) labelEl.textContent = labelEl.dataset.lightLabel || 'Light';
        btn.title = labelEl ? labelEl.dataset.lightLabel : 'Switch to light mode';
      } else {
        if (iconEl) { iconEl.classList.remove('fa-sun'); iconEl.classList.add('fa-moon'); }
        if (labelEl) labelEl.textContent = labelEl.dataset.darkLabel || 'Dark';
        btn.title = labelEl ? labelEl.dataset.darkLabel : 'Switch to dark mode';
      }
    });
  }

  // Apply immediately to avoid flash
  const initialTheme = getPreference();
  applyTheme(initialTheme);

  // Expose globally
  window.ThemeManager = {
    toggle: toggleTheme,
    current: function () {
      return document.documentElement.classList.contains(DARK_CLASS) ? 'dark' : 'light';
    },
    apply: applyTheme,
    updateButtons: updateToggleButtons,
  };

  // Initialize buttons once DOM is ready
  document.addEventListener('DOMContentLoaded', function () {
    updateToggleButtons(initialTheme);

    document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        toggleTheme();
      });
    });
  });
})();
