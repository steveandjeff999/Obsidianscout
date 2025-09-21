/**
 * Simplified Mobile Viewport Stabilizer
 * Fixes mobile scroll glitches with a cleaner, less intrusive approach
 */

(function() {
    'use strict';
    
    // Mobile detection with multiple methods
    const isMobile = () => {
        return window.innerWidth <= 768 || 
               /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
               ('ontouchstart' in window) ||
               (navigator.maxTouchPoints > 0) ||
               (navigator.msMaxTouchPoints > 0);
    };
    
    // Only apply mobile-specific fixes
    if (!isMobile()) {
        console.log('Mobile Viewport Stabilizer: Desktop detected, skipping mobile fixes');
        return;
    }
    
    console.log('Mobile Viewport Stabilizer: Initializing simplified version');
    
    // Simple scroll position tracking
    let lastKnownScroll = 0;
    let isRestoring = false;
    
    
    // Update scroll position tracking (debounced)
    let scrollTimeout;
    function updateScrollPosition() {
        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(() => {
            if (!isRestoring) {
                lastKnownScroll = window.pageYOffset || document.documentElement.scrollTop || 0;
            }
        }, 100);
    }
    
    // Basic scroll tracking
    window.addEventListener('scroll', updateScrollPosition, { passive: true });
    
    // Initialize on page load
    document.addEventListener('DOMContentLoaded', () => {
        updateScrollPosition();
        addMobileCSS();
    });
    
    // Add essential mobile CSS fixes
    function addMobileCSS() {
        const style = document.createElement('style');
        style.id = 'mobile-scroll-fixes';
        style.textContent = `
            @media (max-width: 768px) {
                /* Prevent iOS zoom on input focus */
                input, textarea, select {
                    font-size: 16px !important;
                }
                
                /* Improve touch scrolling */
                body {
                    -webkit-overflow-scrolling: touch;
                    touch-action: pan-y;
                }
                
                /* Prevent focus-induced scroll jumps */
                input:focus, textarea:focus, select:focus {
                    scroll-margin: 0 !important;
                    scroll-behavior: auto !important;
                }
                
                /* Stable tab content */
                .tab-content {
                    contain: layout;
                }
                
                /* Force GPU acceleration for smooth interactions */
                .btn, button, [role="button"] {
                    will-change: auto;
                    transform: translateZ(0);
                }
                
                /* Prevent modal backdrop scroll issues */
                .modal-backdrop {
                    touch-action: none;
                }
            }
        `;
        
        // Remove existing if present
        const existing = document.getElementById('mobile-scroll-fixes');
        if (existing) existing.remove();
        
        document.head.appendChild(style);
    }
    
    
    // Simple focus handling - just prevent major jumps
    let focusScrollY = 0;
    document.addEventListener('focusin', (e) => {
        if (e.target.matches('input, textarea, select')) {
            focusScrollY = window.pageYOffset || document.documentElement.scrollTop || 0;
            
            // Simple restoration after focus settles
            setTimeout(() => {
                const currentScroll = window.pageYOffset || document.documentElement.scrollTop || 0;
                
                // Only restore if there was a significant unwanted jump
                if (currentScroll === 0 && focusScrollY > 100) {
                    isRestoring = true;
                    window.scrollTo(0, focusScrollY);
                    setTimeout(() => { isRestoring = false; }, 100);
                }
            }, 300);
        }
    }, { passive: true });
    
    // Simple tab click handling
    document.addEventListener('click', (e) => {
        const tabTrigger = e.target.closest('[data-bs-toggle="tab"]');
        if (tabTrigger) {
            const beforeScroll = window.pageYOffset || document.documentElement.scrollTop || 0;
            
            // Quick check after tab switch
            setTimeout(() => {
                const afterScroll = window.pageYOffset || document.documentElement.scrollTop || 0;
                
                // Only restore if we jumped to top unexpectedly
                if (afterScroll === 0 && beforeScroll > 50) {
                    isRestoring = true;
                    window.scrollTo(0, beforeScroll);
                    setTimeout(() => { isRestoring = false; }, 100);
                }
            }, 50);
        }
    }, { passive: true });
    
    
    // Simple orientation change handling
    let orientationScroll = 0;
    window.addEventListener('orientationchange', () => {
        orientationScroll = window.pageYOffset || document.documentElement.scrollTop || 0;
        
        // Restore after orientation settles
        setTimeout(() => {
            if (orientationScroll > 0) {
                isRestoring = true;
                window.scrollTo(0, orientationScroll);
                setTimeout(() => { isRestoring = false; }, 100);
            }
        }, 500);
    });
    
    // Provide a simple global scroll restore function
    window.safeRestoreScroll = function(targetY, options) {
        options = options || {};
        const y = Math.max(0, targetY || 0);
        
        isRestoring = true;
        
        try {
            window.scrollTo({
                top: y,
                behavior: options.behavior || 'auto'
            });
        } catch (e) {
            window.scrollTo(0, y);
        }
        
        setTimeout(() => { isRestoring = false; }, 150);
    };
    
    // Flag that stabilizer is active
    window.mobileViewportStabilizerActive = true;
    
    console.log('Mobile Viewport Stabilizer: Simplified version loaded');
    
})();