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
            const select = $(this).data('select2').$element;
            if (select) {
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
}

// Initialize when document is ready
$(document).ready(function() {
    // Initialize dark mode handlers
    initDarkModeHandlers();
});
