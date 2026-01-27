/**
 * SquidStats Theme Manager
 * Sistema profesional de gestión de temas claro/oscuro
 * Con transiciones suaves y persistencia en localStorage
 */

class ThemeManager {
    constructor() {
        this.STORAGE_KEY = 'squidstats-theme';
        this.THEME_LIGHT = 'light';
        this.THEME_DARK = 'dark';
        this.currentTheme = this.getStoredTheme() || this.getSystemTheme();
        
        // Inicializar el tema inmediatamente para evitar flash
        this.initTheme();
        
        // Escuchar cambios en las preferencias del sistema
        this.watchSystemTheme();
    }

    /**
     * Inicializa el tema sin transiciones
     */
    initTheme() {
        // Aplicar tema sin transición
        document.documentElement.classList.add('theme-transition-disabled');
        this.applyTheme(this.currentTheme, false);
        
        // Habilitar transiciones después de cargar
        requestAnimationFrame(() => {
            document.documentElement.classList.remove('theme-transition-disabled');
        });
    }

    /**
     * Obtiene el tema almacenado en localStorage
     */
    getStoredTheme() {
        return localStorage.getItem(this.STORAGE_KEY);
    }

    /**
     * Detecta la preferencia de tema del sistema
     */
    getSystemTheme() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return this.THEME_DARK;
        }
        return this.THEME_LIGHT;
    }

    /**
     * Observa cambios en las preferencias del sistema
     */
    watchSystemTheme() {
        if (!window.matchMedia) return;
        
        const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        mediaQuery.addEventListener('change', (e) => {
            // Solo actualizar si el usuario no ha establecido una preferencia
            if (!this.getStoredTheme()) {
                this.setTheme(e.matches ? this.THEME_DARK : this.THEME_LIGHT);
            }
        });
    }

    /**
     * Aplica el tema al documento
     */
    applyTheme(theme, withTransition = true) {
        const html = document.documentElement;
        const isDark = theme === this.THEME_DARK;
        
        if (!withTransition) {
            html.classList.add('theme-transition-disabled');
        }
        
        if (isDark) {
            html.classList.add('dark');
            html.setAttribute('data-theme', 'dark');
        } else {
            html.classList.remove('dark');
            html.setAttribute('data-theme', 'light');
        }
        
        // Actualizar el icono del toggle
        this.updateThemeIcon(theme);
        
        // Emitir evento personalizado
        window.dispatchEvent(new CustomEvent('themeChanged', { detail: { theme } }));
        
        // Aplicar cambios a gráficos si existen
        this.updateChartThemes(theme);
        
        if (!withTransition) {
            requestAnimationFrame(() => {
                html.classList.remove('theme-transition-disabled');
            });
        }
    }

    /**
     * Actualiza el icono del botón de tema
     */
    updateThemeIcon(theme) {
        const themeIcons = document.querySelectorAll('.theme-toggle-icon');
        themeIcons.forEach(icon => {
            if (theme === this.THEME_DARK) {
                icon.classList.remove('fa-moon');
                icon.classList.add('fa-sun');
            } else {
                icon.classList.remove('fa-sun');
                icon.classList.add('fa-moon');
            }
        });
        
        // Actualizar tooltips
        const themeButtons = document.querySelectorAll('[data-theme-toggle]');
        themeButtons.forEach(btn => {
            const tooltip = theme === this.THEME_DARK ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
            btn.setAttribute('title', tooltip);
            btn.setAttribute('data-tooltip', tooltip);
        });
    }

    /**
     * Establece un nuevo tema
     */
    setTheme(theme) {
        this.currentTheme = theme;
        localStorage.setItem(this.STORAGE_KEY, theme);
        this.applyTheme(theme);
    }

    /**
     * Alterna entre modo claro y oscuro
     */
    toggleTheme() {
        const newTheme = this.currentTheme === this.THEME_DARK ? this.THEME_LIGHT : this.THEME_DARK;
        this.setTheme(newTheme);
    }

    /**
     * Obtiene el tema actual
     */
    getCurrentTheme() {
        return this.currentTheme;
    }

    /**
     * Verifica si está en modo oscuro
     */
    isDarkMode() {
        return this.currentTheme === this.THEME_DARK;
    }

    /**
     * Actualiza los temas de los gráficos Chart.js
     */
    updateChartThemes(theme) {
        const isDark = theme === this.THEME_DARK;
        
        // Si Chart.js está disponible, actualizar colores globales
        if (window.Chart) {
            const textColor = isDark ? '#e2e8f0' : '#1e293b';
            const gridColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
            
            Chart.defaults.color = textColor;
            Chart.defaults.borderColor = gridColor;
            
            // Actualizar todos los gráficos existentes
            Object.values(Chart.instances).forEach(chart => {
                if (chart.options.scales) {
                    Object.values(chart.options.scales).forEach(scale => {
                        if (scale.ticks) scale.ticks.color = textColor;
                        if (scale.grid) scale.grid.color = gridColor;
                    });
                }
                if (chart.options.plugins?.legend?.labels) {
                    chart.options.plugins.legend.labels.color = textColor;
                }
                chart.update('none'); // Actualizar sin animación
            });
        }
    }

    /**
     * Obtiene los colores del tema actual para usar en JavaScript
     */
    getThemeColors() {
        const isDark = this.isDarkMode();
        return {
            background: isDark ? '#0f172a' : '#ffffff',
            backgroundAlt: isDark ? '#1e293b' : '#f8fafc',
            text: isDark ? '#e2e8f0' : '#1e293b',
            textSecondary: isDark ? '#94a3b8' : '#64748b',
            border: isDark ? '#334155' : '#e2e8f0',
            primary: isDark ? '#3b82f6' : '#2563eb',
            success: isDark ? '#22c55e' : '#10b981',
            warning: isDark ? '#f59e0b' : '#f59e0b',
            error: isDark ? '#ef4444' : '#dc2626',
        };
    }
}

// Inicializar el gestor de temas globalmente
window.themeManager = new ThemeManager();

// Función helper para toggle (compatible con código existente)
function toggleTheme() {
    window.themeManager.toggleTheme();
}

// Inicializar botones de toggle al cargar el DOM
document.addEventListener('DOMContentLoaded', () => {
    // Agregar listener a todos los botones de theme toggle
    document.querySelectorAll('[data-theme-toggle]').forEach(button => {
        button.addEventListener('click', (e) => {
            e.preventDefault();
            window.themeManager.toggleTheme();
        });
    });
});
