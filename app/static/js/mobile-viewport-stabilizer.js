/**
 * Mobile Viewport Stabilizer
 * Prevents unwanted scroll-to-top behavior on mobile devices
 * Specifically addresses issues with input focus and tab navigation
 */

(function() {
    'use strict';
    
    // Mobile detection with multiple methods plus tall-portrait heuristics
    const isMobile = () => {
        const base = window.innerWidth <= 768 || 
               /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
               ('ontouchstart' in window) ||
               (navigator.maxTouchPoints > 0) ||
               (navigator.msMaxTouchPoints > 0);

        // Consider tall portrait screens (height > width and reasonably tall) as mobile-like too
        const isPortraitTall = (window.innerHeight > window.innerWidth) && (window.innerHeight >= 900);

        return base || isPortraitTall;
    };

    // Only apply mobile/tall-portrait-specific fixes
    if (!isMobile()) return;
    
    console.log('Mobile Viewport Stabilizer: Initializing for mobile device');
    
    // Track scroll positions
    let lastStableScrollY = 0;
    let preventScrollRestoration = false;
    
    // Update stable scroll position periodically
    const updateStableScrollPosition = () => {
        if (!preventScrollRestoration) {
            lastStableScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
        }
    };
    
    // Update stable position on user scroll
    let scrollTimeout;
    window.addEventListener('scroll', () => {
        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(updateStableScrollPosition, 150);
    }, { passive: true });
    
    // Initialize stable position
    document.addEventListener('DOMContentLoaded', updateStableScrollPosition);
    
    // Viewport meta tag optimization for iOS
    const optimizeViewportMeta = () => {
        let viewport = document.querySelector('meta[name="viewport"]');
        if (viewport) {
            // Enhance existing viewport meta tag for better mobile stability
            const currentContent = viewport.getAttribute('content') || '';
            if (!currentContent.includes('viewport-fit=cover')) {
                viewport.setAttribute('content', currentContent + ', viewport-fit=cover');
            }
        }
    };
    
    // CSS-based input stabilization
    const stabilizeInputs = () => {
        const style = document.createElement('style');
        style.id = 'mobile-input-stabilizer';
        style.textContent = `
            @media (max-width: 768px) {
                /* Prevent iOS zoom on input focus */
                input, textarea, select {
                    font-size: 16px !important;
                    transform: translateZ(0);
                    -webkit-transform: translateZ(0);
                }
                
                /* Prevent focus outline from causing scroll */
                input:focus, textarea:focus, select:focus {
                    scroll-margin: 0 !important;
                    scroll-behavior: auto !important;
                }
                
                /* Stabilize form containers */
                .form-group, .input-group, .form-floating {
                    contain: layout;
                    transform: translateZ(0);
                    -webkit-transform: translateZ(0);
                }
                
                /* Prevent tab content changes from scrolling */
                .tab-content {
                    contain: layout style;
                }
                
                /* Force hardware acceleration on interactive elements */
                button, .btn, [role="button"] {
                    transform: translateZ(0);
                    -webkit-transform: translateZ(0);
                }
            }
        `;
        
        // Remove existing if present, then add new
        const existing = document.getElementById('mobile-input-stabilizer');
        if (existing) existing.remove();
        
        document.head.appendChild(style);
    };
    
    // Enhanced focus handling
    const setupFocusStabilization = () => {
        let focusScrollY = 0;
        
        // Capture focus events
        document.addEventListener('focusin', (e) => {
            if (e.target.matches('input, textarea, select')) {
                focusScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
                preventScrollRestoration = true;
                
                // Restore scroll position after focus is complete
                setTimeout(() => {
                    const currentScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
                        if (Math.abs(currentScrollY - focusScrollY) > 10) {
                            // Use global safeRestoreScroll if available so suppression flags are coordinated
                            if (window.safeRestoreScroll && typeof window.safeRestoreScroll === 'function') {
                                window.safeRestoreScroll(focusScrollY, { behavior: 'auto', timeout: 300 });
                            } else if (window.__suppressMobileScrollJumps) {
                                // If suppression explicitly set, allow direct native call
                                try { window.scrollTo(0, focusScrollY); } catch(e){}
                            } else {
                                // Fallback to calling scrollTo but avoid 'instant' which some browsers don't support
                                try { window.scrollTo({ top: focusScrollY, behavior: 'auto' }); } catch(e) { try { window.scrollTo(0, focusScrollY); } catch(e2){} }
                            }
                    }
                    preventScrollRestoration = false;
                }, 300);
            }
        }, true);
        
        // Handle blur events
        document.addEventListener('focusout', (e) => {
            if (e.target.matches('input, textarea, select')) {
                preventScrollRestoration = false;
                updateStableScrollPosition();
            }
        }, true);
    };
    
    // Enhanced Bootstrap tab handling
    const setupTabStabilization = () => {
        // Override Bootstrap tab behavior
        document.addEventListener('click', (e) => {
            const tabTrigger = e.target.closest('[data-bs-toggle="tab"]');
            if (tabTrigger) {
                const beforeScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
                
                // Allow tab switch, then restore position
                setTimeout(() => {
                    const afterScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
                        if (Math.abs(afterScrollY - beforeScrollY) > 5) {
                            if (window.safeRestoreScroll && typeof window.safeRestoreScroll === 'function') {
                                window.safeRestoreScroll(beforeScrollY, { behavior: 'auto', timeout: 200 });
                            } else if (window.__suppressMobileScrollJumps) {
                                try { window.scrollTo(0, beforeScrollY); } catch(e){}
                            } else {
                                try { window.scrollTo({ top: beforeScrollY, behavior: 'auto' }); } catch(e) { try { window.scrollTo(0, beforeScrollY); } catch(e2){} }
                            }
                    }
                }, 50);
            }
        }, true);
        
        // Global button and interactive element protection
        document.addEventListener('click', (e) => {
            // Skip if this is a tab trigger (handled above)
            if (e.target.closest('[data-bs-toggle="tab"]')) return;
            
            const beforeScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
            
            // For any button, dropdown, or interactive element
            if (e.target.matches('button, .btn, select, .dropdown-toggle, input[type="submit"], input[type="button"]') ||
                e.target.closest('button, .btn, select, .dropdown-toggle, input[type="submit"], input[type="button"]')) {
                
                // Multiple restoration attempts at different intervals
                const restorePosition = () => {
                    const afterScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
                        if (afterScrollY === 0 || Math.abs(afterScrollY - beforeScrollY) > 10) {
                            if (window.safeRestoreScroll && typeof window.safeRestoreScroll === 'function') {
                                window.safeRestoreScroll(beforeScrollY, { behavior: 'auto', timeout: 300 });
                            } else if (window.__suppressMobileScrollJumps) {
                                try { window.scrollTo(0, beforeScrollY); } catch(e){}
                            } else {
                                try { window.scrollTo({ top: beforeScrollY, behavior: 'auto' }); } catch(e) { try { window.scrollTo(0, beforeScrollY); } catch(e2){} }
                            }
                    }
                };
                
                setTimeout(restorePosition, 10);
                setTimeout(restorePosition, 50);
                setTimeout(restorePosition, 150);
                setTimeout(restorePosition, 300);
                setTimeout(restorePosition, 500);
            }
        }, true);
    };
    
    // Handle orientation changes
    const setupOrientationHandling = () => {
        let orientationScrollY = 0;
        
        window.addEventListener('orientationchange', () => {
            orientationScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
        });
        
        // Restore scroll position after orientation change settles
        window.addEventListener('resize', () => {
                    if (orientationScrollY > 0) {
                setTimeout(() => {
                    try {
                        window.scrollTo({
                            top: orientationScrollY,
                            behavior: 'auto'
                        });
                    } catch(e) {
                        try { window.scrollTo(0, orientationScrollY); } catch(_) {}
                    }
                    orientationScrollY = 0;
                }, 200);
            }
        });
    };
    
    // Prevent unwanted hash changes
    const setupHashStabilization = () => {
        let preventHashChange = false;
        
        // Listen for programmatic hash changes that might scroll to top
        const originalPushState = history.pushState;
        const originalReplaceState = history.replaceState;
        
        history.pushState = function() {
            const beforeScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
            const result = originalPushState.apply(history, arguments);
            
                setTimeout(() => {
                const afterScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
                if (Math.abs(afterScrollY - beforeScrollY) > 10) {
                    try {
                        window.scrollTo({ top: beforeScrollY, behavior: 'auto' });
                    } catch(e) { try { window.scrollTo(0, beforeScrollY); } catch(_) {} }
                }
            }, 50);
            
            return result;
        };
        
        history.replaceState = function() {
            const beforeScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
            const result = originalReplaceState.apply(history, arguments);
            
                setTimeout(() => {
                const afterScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
                if (Math.abs(afterScrollY - beforeScrollY) > 10) {
                    try {
                        window.scrollTo({ top: beforeScrollY, behavior: 'auto' });
                    } catch(e) { try { window.scrollTo(0, beforeScrollY); } catch(_) {} }
                }
            }, 50);
            
            return result;
        };
        
        // Handle hash change events
        window.addEventListener('hashchange', (e) => {
            if (preventHashChange) {
                e.preventDefault();
                return false;
            }
            
            // If hash change would scroll to top, prevent it
            if (!window.location.hash || window.location.hash === '#') {
                preventHashChange = true;
                if (e.oldURL && e.oldURL.includes('#')) {
                    const oldHash = e.oldURL.split('#')[1];
                    if (oldHash) {
                        history.replaceState(null, '', '#' + oldHash);
                    }
                }
                setTimeout(() => { preventHashChange = false; }, 100);
            }
        }, true);
    };
    
    // Initialize all stabilization features
    const initializeStabilizer = () => {
        try {
            optimizeViewportMeta();
            stabilizeInputs();
            setupFocusStabilization();
            setupTabStabilization();
            setupOrientationHandling();
            setupHashStabilization();
            
            // Add global scrollTo protection
            const originalScrollTo = window.scrollTo;
            let lastAllowedScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
            let scrollProtectionActive = false;
            
            window.scrollTo = function(x, y) {
                try {
                    // If another script intentionally sets a suppression flag, allow this call
                    if (window.__suppressMobileScrollJumps) {
                        return originalScrollTo.apply(window, arguments);
                    }
                } catch (e) {}

                // Allow scrollTo calls that are restoring to known positions
                if (typeof x === 'object' && x.top !== undefined) {
                    y = x.top;
                }

                // If trying to scroll to 0 (top) and we're not already near the top, block it unless protection disabled
                if (y === 0 && lastAllowedScrollY > 50 && !scrollProtectionActive) {
                    // If this looks like a forced attempt to jump to top caused by old libraries, gently restore
                    console.log('Mobile Viewport Stabilizer: Intercepted scroll to top, restoring lastAllowedScrollY:', lastAllowedScrollY);
                    return originalScrollTo.call(window, 0, lastAllowedScrollY);
                }

                // Update last allowed position for non-zero scrolls
                if (typeof y === 'number' && y > 0) {
                    lastAllowedScrollY = y;
                }

                return originalScrollTo.apply(window, arguments);
            };
            
            // Update last allowed position on user scroll
            let scrollTimeout;
            window.addEventListener('scroll', () => {
                if (!scrollProtectionActive) {
                    clearTimeout(scrollTimeout);
                    scrollTimeout = setTimeout(() => {
                        const currentY = window.pageYOffset || document.documentElement.scrollTop || 0;
                        if (currentY > 0) {
                            lastAllowedScrollY = currentY;
                        }
                    }, 100);
                }
            }, { passive: true });
            
            // Temporarily disable protection during legitimate operations
            window.allowScrollToTop = (duration = 1000) => {
                scrollProtectionActive = true;
                setTimeout(() => { scrollProtectionActive = false; }, duration);
            };
            
            console.log('Mobile Viewport Stabilizer: All features initialized');
        } catch (error) {
            console.warn('Mobile Viewport Stabilizer: Error during initialization:', error);
        }
    };
    
    // Initialize immediately or on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeStabilizer);
    } else {
        initializeStabilizer();
    }
    
    // Global flag for other scripts to check if stabilizer is active
    window.mobileViewportStabilizerActive = true;
    
})();