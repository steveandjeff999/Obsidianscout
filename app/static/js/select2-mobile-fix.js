/**
 * Select2 Mobile Fix
 * Comprehensive solution for Select2 dropdown issues on mobile devices
 */

(function($) {
    'use strict';
    
    // Check if we're on a mobile device
    function isMobile() {
        return window.innerWidth <= 900 || /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    }
    
    // Store original scroll position
    let originalScrollPosition = 0;
    let isSelect2Open = false;
    
    // Prevent body scroll when dropdown is open
    function preventBodyScroll() {
        if (!isMobile()) return;
        
        originalScrollPosition = window.pageYOffset || document.documentElement.scrollTop;
        document.body.classList.add('select2-dropdown-open');
        document.body.style.top = `-${originalScrollPosition}px`;
    }
    
    // Restore body scroll when dropdown closes
    function restoreBodyScroll() {
        if (!isMobile()) return;
        
        document.body.classList.remove('select2-dropdown-open');
        document.body.style.top = '';
        window.scrollTo(0, originalScrollPosition);
    }
    
    // Default mobile-friendly Select2 configuration
    function getMobileSelect2Config(customConfig) {
        const baseConfig = {
            theme: 'bootstrap-5',
            width: '100%',
            dropdownAutoWidth: false,
            // Improved positioning for mobile
            dropdownParent: isMobile() ? $(document.body) : null,
        };
        
        // Mobile-specific configurations
        if (isMobile()) {
            // CRITICAL: Disable search on mobile to prevent keyboard from opening
            baseConfig.minimumResultsForSearch = Infinity; // This disables the search input entirely
            baseConfig.closeOnSelect = true; // Close on select for mobile
            baseConfig.selectOnClose = false;
            baseConfig.dropdownCssClass = (customConfig?.dropdownCssClass || '') + ' select2-mobile-dropdown';
            baseConfig.selectionCssClass = (customConfig?.selectionCssClass || '') + ' select2-mobile-selection';
            
            // Prevent automatic focus that triggers keyboard
            baseConfig.focus = function() { return false; };
        }
        
        // Merge with custom config
        return $.extend(true, baseConfig, customConfig || {});
    }
    
    // Enhanced Select2 initialization function
    window.initSelect2Mobile = function(selector, customConfig) {
        const $element = $(selector);
        if (!$element.length) return null;
        
        // Destroy existing instance
        if ($element.hasClass('select2-hidden-accessible')) {
            $element.select2('destroy');
        }
        
        const config = getMobileSelect2Config(customConfig);
        
        // Initialize Select2
        const select2Instance = $element.select2(config);
        
        // Add mobile-specific event handlers
        if (isMobile()) {
            // Prevent dropdown from closing immediately
            $element.on('select2:opening', function(e) {
                isSelect2Open = true;
                preventBodyScroll();
                
                // CRITICAL: Prevent focus events that trigger keyboard
                setTimeout(() => {
                    const $dropdown = $('.select2-dropdown');
                    if ($dropdown.length) {
                        $dropdown.css({
                            'position': 'fixed',
                            'z-index': '9999',
                            'transform': 'translateZ(0)',
                            'will-change': 'transform'
                        });
                        
                        // Remove focus from any input elements to prevent keyboard
                        $dropdown.find('input, textarea').blur();
                        $dropdown.find('.select2-search__field').remove(); // Remove search field entirely on mobile
                    }
                }, 10);
            });
            
            $element.on('select2:closing select2:close', function(e) {
                isSelect2Open = false;
                setTimeout(restoreBodyScroll, 100);
            });
            
            // Handle touch events properly - SIMPLIFIED for mobile
            $element.on('select2:open', function() {
                const $dropdown = $('.select2-dropdown');
                
                // Remove any search inputs that might trigger keyboard
                $dropdown.find('.select2-search').remove();
                $dropdown.find('.select2-search__field').remove();
                
                // Handle option selection properly
                // Improve touch handling: trigger a sequence of events that Select2
                // will respond to on mobile devices. Avoid preventing the default
                // action (which can interfere with selection in some browsers),
                // but stop propagation so outer handlers don't interfere.
                $dropdown.find('.select2-results__option').off('touchend.select2Mobile click.select2Mobile touchstart.select2Mobile')
                    .on('touchstart.select2Mobile touchend.select2Mobile click.select2Mobile', function(e) {
                        // Allow default behavior for touch events in most browsers,
                        // but stop propagation so other listeners don't cancel the action.
                        try { e.stopPropagation(); } catch (err) {}

                        // Trigger selection by emulating the pointer events Select2
                        // expects. This sequence is more robust across browsers.
                        const $option = $(this);
                        if ($option.hasClass('select2-results__option--disabled')) return;

                        try {
                            $option.trigger('mousedown');
                            $option.trigger('mouseup');
                            $option.trigger('click');
                        } catch (err) {
                            // Fallback: attempt the original mouseup trigger
                            try { $option.trigger('mouseup'); } catch (ignored) {}
                        }
                    });
            });
            
            // Prevent keyboard-related closures
            $element.on('select2:unselecting', function(e) {
                if (isSelect2Open) {
                    e.preventDefault();
                    return false;
                }
            });
            
            // Handle viewport changes without closing dropdown
            let resizeTimeout;
            $(window).off('resize.select2Mobile').on('resize.select2Mobile', function() {
                if (isSelect2Open) {
                    clearTimeout(resizeTimeout);
                    resizeTimeout = setTimeout(() => {
                        // Keep dropdown open despite viewport changes
                        if ($element.select2('isOpen')) {
                            const $dropdown = $('.select2-dropdown');
                            if ($dropdown.length) {
                                $dropdown.css({
                                    'position': 'fixed',
                                    'z-index': '9999',
                                    'max-height': Math.min(window.innerHeight * 0.6, 400) + 'px'
                                });
                            }
                        }
                    }, 100);
                }
            });
        }
        
        return select2Instance;
    };

    // Additional global helper: ensure tapping the visible Select2 selection
    // container opens the dropdown on devices that block the native event.
    // This is non-invasive and only attaches when running on mobile.
    function bindTouchOpenFallback($element) {
        try {
            if (!isMobile()) return;
            // Find the rendered container
            const $container = $element.next('.select2-container');
            if (!$container || $container.length === 0) return;
            // Avoid binding multiple times
            if ($container.data('mobile-open-handler')) return;
            $container.data('mobile-open-handler', true);

            // Use touchend so the tap completes; also listen for click as a fallback
            $container.on('touchend.select2MobileOpen click.select2MobileOpen', function(e) {
                try {
                    // If Select2 is already open, let it handle closing
                    if ($element.select2('isOpen')) return;

                    // Stop propagation so outside handlers don't interfere
                    e.stopPropagation();

                    // Open after a tiny delay to allow native focus to settle
                    setTimeout(function() {
                        try { $element.select2('open'); } catch (err) { /* ignore */ }
                    }, 10);
                } catch (err) {
                    // swallow errors to avoid breaking pages
                }
            });
        } catch (err) {
            // noop
        }
    }

    // Auto-bind fallback for any Select2 elements already on the page
    $(document).ready(function() {
        try {
            $('.select2-hidden-accessible').each(function() {
                try {
                    bindTouchOpenFallback($(this));
                } catch(e) {}
            });
        } catch(e) {}
    });
    
    // Global event handlers for mobile
    if (isMobile()) {
        // Prevent document click from closing Select2 dropdowns inappropriately
        $(document).on('touchend', function(e) {
            if (isSelect2Open) {
                const $target = $(e.target);
                const $dropdown = $('.select2-dropdown');
                const $container = $('.select2-container');
                
                // Allow clicks within Select2 components
                if ($target.closest('.select2-dropdown, .select2-container').length > 0) {
                    e.stopPropagation();
                    return;
                }
                
                // Close dropdown if clicked outside
                if ($dropdown.length && !$target.closest($dropdown).length && !$target.closest($container).length) {
                    $('.select2-hidden-accessible').select2('close');
                }
            }
        });
        
        // Handle orientation change
        $(window).on('orientationchange', function() {
            setTimeout(function() {
                $('.select2-hidden-accessible').each(function() {
                    if ($(this).hasClass('select2-hidden-accessible')) {
                        $(this).select2('close');
                    }
                });
            }, 500);
        });
        
        // Handle viewport changes (like keyboard showing/hiding)
        let viewportHeight = window.innerHeight;
        $(window).on('resize', function() {
            const newHeight = window.innerHeight;
            const heightDifference = Math.abs(viewportHeight - newHeight);
            
            // If viewport height changed significantly (likely keyboard)
            if (heightDifference > 150) {
                if (isSelect2Open) {
                    // DON'T close dropdown - just reposition it
                    setTimeout(() => {
                        const $dropdown = $('.select2-dropdown');
                        if ($dropdown.length && $('.select2-hidden-accessible:first').select2('isOpen')) {
                            $dropdown.css({
                                'position': 'fixed',
                                'z-index': '9999',
                                'max-height': Math.min(newHeight * 0.6, 400) + 'px'
                            });
                        }
                    }, 50);
                }
            }
            
            viewportHeight = newHeight;
        });
        
        // Additional protection: Override Select2's built-in resize handler
        $(window).off('resize.select2');
    }
    
    // Automatically enhance existing Select2 instances
    $(document).ready(function() {
        // Wait for other scripts to initialize
        setTimeout(() => {
            $('.select2-hidden-accessible').each(function() {
                const $this = $(this);
                const existingConfig = $this.data('select2') || {};
                
                // Reinitialize with mobile fixes
                if (isMobile()) {
                    const config = getMobileSelect2Config(existingConfig.options || {});
                    $this.select2('destroy').select2(config);
                }
            });
        }, 100);
    });
    
})(jQuery);

// CSS injection for additional mobile fixes
if (typeof window !== 'undefined' && window.innerWidth <= 900) {
    const style = document.createElement('style');
    style.textContent = `
        /* Additional runtime mobile fixes */
        .select2-container--bootstrap-5 .select2-dropdown {
            border: 2px solid var(--bs-primary) !important;
        }
        
        .select2-mobile-dropdown {
            animation: select2MobileFadeIn 0.2s ease-out;
        }
        
        @keyframes select2MobileFadeIn {
            from {
                opacity: 0;
                transform: translateY(-10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .select2-mobile-selection {
            transition: all 0.2s ease;
        }
        
        .select2-mobile-selection:focus-within {
            transform: scale(1.02);
            box-shadow: 0 0 0 0.2rem rgba(var(--bs-primary-rgb), 0.25) !important;
        }
    `;
    document.head.appendChild(style);
}