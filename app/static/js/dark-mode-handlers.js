/**
 * Dark mode handlers for the FRC Scouting Platform
 */

// Function to update Select2 theme based on dark mode
function updateSelect2DarkMode() {
    // Check if dark mode is active
    const isDarkMode = document.body.classList.contains('dark-mode');
    
    // Apply appropriate theme to all Select2 instances
    if ($.fn.select2) {
        $('.select2-container--bootstrap-5').each(function() {
            const select2Data = $(this).data('select2');
            if (select2Data && select2Data.$element) {
                const select = select2Data.$element;
                // Store current selection
                const selectedData = select.select2('data');
                // Destroy and reinitialize with updated theme
                select.select2('destroy');
                // Get existing options
                const existingOptions = select.data('select2-options') || {};
                // Create merged options with updated theme
                const options = {
                    ...existingOptions,
                    theme: 'bootstrap-5',
                    // Additional styling for dark mode
                    dropdownParent: existingOptions.dropdownParent || $('body')
                };
                // Store the options for future reference
                select.data('select2-options', options);
                // Reinitialize with updated options
                select.select2(options);
                // Restore selection
                if (selectedData && selectedData.length) {
                    select.val(selectedData.map(item => item.id)).trigger('change');
                }
            }
        });
    }
}

// Apply Select2 dark mode when the page theme changes
function initDarkModeHandlers() {
    // Set up observer for dark mode changes
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'attributes' && 
                mutation.attributeName === 'class' && 
                mutation.target === document.body) {
                // Update Select2 theme when dark mode changes
                updateSelect2DarkMode();
                // Update demo preview helper class so scoped CSS works on dynamically rendered content
                try { applyDemoPreviewDarkMode(); } catch(e) { }
            }
        });
    });
    
    // Start observing the body for class changes
    observer.observe(document.body, { 
        attributes: true,
        attributeFilter: ['class']
    });
    
    // Initial application of dark mode styles
    updateSelect2DarkMode();
    // Ensure demo previews get a dark-mode helper class so scoped CSS can apply
    function applyDemoPreviewDarkMode() {
        const isDark = document.body.classList.contains('dark-mode');
        document.querySelectorAll('.demo-preview, .demo-frame').forEach(el => {
            try { if (isDark) el.classList.add('dark-mode'); else el.classList.remove('dark-mode'); } catch(e) {}
        });
    }
    try { applyDemoPreviewDarkMode(); } catch(e) {}

    // Retheme any already-rendered Plotly charts to match initial theme
    try { if (window.rethemePlotlyCharts) window.rethemePlotlyCharts(); } catch(e) { console.warn('Initial Plotly retheme failed', e); }
}

// Initialize when document is ready
$(document).ready(function() {
    // Initialize dark mode handlers
    initDarkModeHandlers();
});

// Also ensure we retheme charts whenever the body's class attribute changes
const __plotlyRethemeObserver = new MutationObserver(function(muts){
    muts.forEach(m => {
        if (m.type === 'attributes' && m.attributeName === 'class' && m.target === document.body) {
            try { if (window.rethemePlotlyCharts) window.rethemePlotlyCharts(); } catch(e) { console.warn('Plotly retheme on class change failed', e); }
        }
    });
});
__plotlyRethemeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });

// Apply Chart.js theme updates to match dark mode when available
function updateChartJsTheme() {
    if (typeof Chart === 'undefined') return;
    try {
        const isDark = document.body.classList.contains('dark-mode');
        const textColor = isDark ? '#e6e6e6' : '#222';
        const gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
        const tooltipBg = isDark ? 'rgba(17,17,18,0.95)' : '#ffffff';
        const tooltipTitle = isDark ? '#ffffff' : '#000000';
        const tooltipBody = isDark ? '#e6e6e6' : '#000000';

        // Global defaults
        Chart.defaults.color = textColor;
        Chart.defaults.borderColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
        Chart.defaults.backgroundColor = isDark ? 'rgba(255,255,255,0.03)' : '#ffffff';
        Chart.defaults.plugins = Chart.defaults.plugins || {};
        Chart.defaults.plugins.tooltip = Chart.defaults.plugins.tooltip || {};
        Chart.defaults.plugins.tooltip.backgroundColor = tooltipBg;
        Chart.defaults.plugins.tooltip.titleColor = tooltipTitle;
        Chart.defaults.plugins.tooltip.bodyColor = tooltipBody;
        Chart.defaults.plugins.legend = Chart.defaults.plugins.legend || {};
        Chart.defaults.plugins.legend.labels = Chart.defaults.plugins.legend.labels || {};
        Chart.defaults.plugins.legend.labels.color = textColor;

        // Set sensible defaults for all known scales
        if (Chart.defaults.scales) {
            Object.keys(Chart.defaults.scales).forEach(scaleName => {
                try {
                    const sc = Chart.defaults.scales[scaleName];
                    sc.grid = sc.grid || {};
                    sc.ticks = sc.ticks || {};
                    sc.grid.color = gridColor;
                    sc.ticks.color = textColor;
                } catch (e) { /* non fatal */ }
            });
        }

        // Update existing charts on the page
        document.querySelectorAll('canvas').forEach(c => {
            try {
                const chart = Chart.getChart(c);
                if (chart) chart.update();
            } catch (e) { /* ignore */ }
        });
    } catch (e) { console.warn('Failed to apply Chart.js theme', e); }
}

// Ensure Chart.js theme is applied when body class changes
const __chartJsRethemeObserver = new MutationObserver(function(muts){
    muts.forEach(m => {
        if (m.type === 'attributes' && m.attributeName === 'class' && m.target === document.body) {
            try { updateChartJsTheme(); } catch(e) { console.warn('Chart.js retheme failed', e); }
        }
    });
});
__chartJsRethemeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });

// Apply initially (in case charts were created before handlers ran)
try { updateChartJsTheme(); } catch(e) { console.warn('Initial Chart.js theme apply failed', e); }
// Make accessible for callers from other scripts
try { window.updateChartJsTheme = updateChartJsTheme; } catch(e) {}
