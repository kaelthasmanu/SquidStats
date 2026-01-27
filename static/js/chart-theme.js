/**
 * Chart.js Theme Integration for SquidStats
 * Adapts charts automatically to light/dark theme changes
 */

(function() {
    'use strict';

    // Function to get current theme colors
    function getChartThemeColors() {
        if (!window.themeManager) {
            return getDefaultChartColors();
        }
        return window.themeManager.getThemeColors();
    }

    // Default colors if theme manager is not available
    function getDefaultChartColors() {
        const isDark = document.documentElement.classList.contains('dark');
        return {
            text: isDark ? '#e2e8f0' : '#1e293b',
            grid: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)',
            tooltipBg: isDark ? '#1e293b' : '#ffffff',
            tooltipBorder: isDark ? '#475569' : '#e2e8f0',
        };
    }

    // Configure Chart.js defaults
    function configureChartDefaults() {
        if (typeof Chart === 'undefined') return;

        const colors = getChartThemeColors();

        // Global chart defaults
        Chart.defaults.color = colors.text;
        Chart.defaults.borderColor = colors.grid;
        
        // Font settings
        Chart.defaults.font.family = "'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif";
        Chart.defaults.font.size = 12;
        
        // Tooltip settings
        Chart.defaults.plugins.tooltip.backgroundColor = colors.tooltipBg;
        Chart.defaults.plugins.tooltip.titleColor = colors.text;
        Chart.defaults.plugins.tooltip.bodyColor = colors.text;
        Chart.defaults.plugins.tooltip.borderColor = colors.tooltipBorder;
        Chart.defaults.plugins.tooltip.borderWidth = 1;
        Chart.defaults.plugins.tooltip.cornerRadius = 8;
        Chart.defaults.plugins.tooltip.padding = 12;
        
        // Legend settings
        Chart.defaults.plugins.legend.labels.color = colors.text;
        Chart.defaults.plugins.legend.labels.padding = 15;
        Chart.defaults.plugins.legend.labels.usePointStyle = true;
        Chart.defaults.plugins.legend.labels.pointStyle = 'circle';
    }

    // Update existing charts
    function updateAllCharts() {
        if (typeof Chart === 'undefined' || !Chart.instances) return;

        const colors = getChartThemeColors();

        Object.values(Chart.instances).forEach(chart => {
            if (!chart || !chart.config) return;

            // Update scales
            if (chart.options.scales) {
                Object.keys(chart.options.scales).forEach(scaleKey => {
                    const scale = chart.options.scales[scaleKey];
                    if (scale.ticks) {
                        scale.ticks.color = colors.text;
                    }
                    if (scale.grid) {
                        scale.grid.color = colors.grid;
                    }
                    if (scale.title) {
                        scale.title.color = colors.text;
                    }
                });
            }

            // Update legend
            if (chart.options.plugins?.legend?.labels) {
                chart.options.plugins.legend.labels.color = colors.text;
            }

            // Update title
            if (chart.options.plugins?.title) {
                chart.options.plugins.title.color = colors.text;
            }

            // Update without animation for smooth transition
            chart.update('none');
        });
    }

    // Helper function to get color palette for different chart types
    window.getChartColorPalette = function(type = 'default') {
        const isDark = document.documentElement.classList.contains('dark');
        
        const palettes = {
            default: isDark ? [
                'rgba(59, 130, 246, 0.8)',  // blue
                'rgba(34, 197, 94, 0.8)',   // green
                'rgba(245, 158, 11, 0.8)',  // amber
                'rgba(239, 68, 68, 0.8)',   // red
                'rgba(168, 85, 247, 0.8)',  // purple
                'rgba(236, 72, 153, 0.8)',  // pink
                'rgba(6, 182, 212, 0.8)',   // cyan
                'rgba(251, 146, 60, 0.8)',  // orange
            ] : [
                'rgba(37, 99, 235, 0.8)',   // blue
                'rgba(16, 185, 129, 0.8)',  // green
                'rgba(245, 158, 11, 0.8)',  // amber
                'rgba(220, 38, 38, 0.8)',   // red
                'rgba(147, 51, 234, 0.8)',  // purple
                'rgba(219, 39, 119, 0.8)',  // pink
                'rgba(8, 145, 178, 0.8)',   // cyan
                'rgba(234, 88, 12, 0.8)',   // orange
            ],
            
            gradient: isDark ? [
                'rgba(99, 102, 241, 0.8)',  // indigo
                'rgba(139, 92, 246, 0.8)',  // violet
                'rgba(217, 70, 239, 0.8)',  // fuchsia
                'rgba(236, 72, 153, 0.8)',  // pink
            ] : [
                'rgba(79, 70, 229, 0.8)',   // indigo
                'rgba(124, 58, 237, 0.8)',  // violet
                'rgba(192, 38, 211, 0.8)',  // fuchsia
                'rgba(219, 39, 119, 0.8)',  // pink
            ],
            
            pastel: isDark ? [
                'rgba(147, 197, 253, 0.8)', // light blue
                'rgba(167, 243, 208, 0.8)', // light green
                'rgba(253, 224, 71, 0.8)',  // light yellow
                'rgba(252, 165, 165, 0.8)', // light red
                'rgba(196, 181, 253, 0.8)', // light purple
            ] : [
                'rgba(191, 219, 254, 0.8)', // lighter blue
                'rgba(209, 250, 229, 0.8)', // lighter green
                'rgba(254, 240, 138, 0.8)', // lighter yellow
                'rgba(254, 202, 202, 0.8)', // lighter red
                'rgba(221, 214, 254, 0.8)', // lighter purple
            ]
        };

        return palettes[type] || palettes.default;
    };

    // Helper function to create gradient backgrounds
    window.createChartGradient = function(ctx, color, alpha = 0.2) {
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, color.replace('0.8)', `${alpha})`));
        gradient.addColorStop(1, color.replace('0.8)', '0)'));
        return gradient;
    };

    // Initialize on load
    function init() {
        if (typeof Chart !== 'undefined') {
            configureChartDefaults();
            
            // Listen for theme changes
            window.addEventListener('themeChanged', function() {
                configureChartDefaults();
                updateAllCharts();
            });
        }
    }

    // Run initialization when Chart.js is ready
    if (typeof Chart !== 'undefined') {
        init();
    } else {
        // Wait for Chart.js to load
        window.addEventListener('load', function() {
            setTimeout(init, 100);
        });
    }

    // Also expose update function globally
    window.updateChartThemes = updateAllCharts;

})();
