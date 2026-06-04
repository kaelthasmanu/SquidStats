/**
 * theme-toggle.js
 * Global dark mode controller for SquidStats.
 * - Toggles the `.dark` class on <html> (documentElement).
 * - Persists the user choice in localStorage ("squidstats-theme").
 * - Defaults to the OS preference (prefers-color-scheme) until the user chooses.
 * - Keeps every [data-theme-toggle] button in sync (sun/moon icon).
 * - Emits a "themechange" event so charts/components can re-render.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "squidstats-theme";

  function getStoredTheme() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function storeTheme(theme) {
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      /* ignore (private mode / disabled storage) */
    }
  }

  function systemPrefersDark() {
    return (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    );
  }

  function currentTheme() {
    return document.documentElement.classList.contains("dark")
      ? "dark"
      : "light";
  }

  function updateToggleButtons(theme) {
    var buttons = document.querySelectorAll("[data-theme-toggle]");
    buttons.forEach(function (btn) {
      var icon = btn.querySelector("i");
      if (icon) {
        icon.classList.remove("fa-moon", "fa-sun");
        icon.classList.add(theme === "dark" ? "fa-sun" : "fa-moon");
      }
      btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
    });
  }

  function applyTheme(theme) {
    var root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    updateToggleButtons(theme);
    document.dispatchEvent(
      new CustomEvent("themechange", { detail: { theme: theme } })
    );
  }

  function setTheme(theme) {
    storeTheme(theme);
    applyTheme(theme);
  }

  function toggleTheme() {
    setTheme(currentTheme() === "dark" ? "light" : "dark");
  }

  // Public API
  window.SquidTheme = {
    toggle: toggleTheme,
    set: setTheme,
    current: currentTheme,
  };

  function bindButtons() {
    updateToggleButtons(currentTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      if (btn.dataset.themeBound) return;
      btn.dataset.themeBound = "1";
      btn.addEventListener("click", function (e) {
        e.preventDefault();
        toggleTheme();
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindButtons);
  } else {
    bindButtons();
  }

  // Follow OS changes only while the user has not made a manual choice.
  if (window.matchMedia) {
    var mql = window.matchMedia("(prefers-color-scheme: dark)");
    var handler = function (e) {
      if (!getStoredTheme()) {
        applyTheme(e.matches ? "dark" : "light");
      }
    };
    if (mql.addEventListener) {
      mql.addEventListener("change", handler);
    } else if (mql.addListener) {
      mql.addListener(handler);
    }
  }
})();
