/**
 * Mobile Scroll Debug Helper
 * Add this temporarily to debug scroll issues
 * 
 * Add this script tag to base.html AFTER all other scripts:
 * <script src="{{ url_for('static', filename='js/scroll-debug.js') }}"></script>
 */

(function() {
    'use strict';
    
    const isMobile = window.innerWidth <= 900 || 
        /Android|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    
    if (!isMobile) {
        console.log('Not mobile, skipping scroll debug');
        return;
    }
    
    console.log('🔍 SCROLL DEBUG MODE ACTIVE');
    
    let lastScrollY = 0;
    let scrollEvents = [];
    let clickEvents = [];
    
    // Track all scroll events
    window.addEventListener('scroll', function(e) {
        const currentY = window.pageYOffset || document.documentElement.scrollTop || 0;
        
        if (Math.abs(currentY - lastScrollY) > 5) {
            const event = {
                timestamp: Date.now(),
                from: lastScrollY,
                to: currentY,
                diff: currentY - lastScrollY,
                stack: new Error().stack
            };
            
            scrollEvents.push(event);
            
            // Log significant scroll changes
            if (Math.abs(event.diff) > 20) {
                console.log(`📊 SIGNIFICANT SCROLL: ${event.from}px → ${event.to}px (${event.diff > 0 ? '+' : ''}${event.diff}px)`);
                
                // If jumped to top unexpectedly
                if (currentY === 0 && lastScrollY > 50) {
                    console.error('🚨 SCROLL TO TOP DETECTED!');
                    console.log('Stack trace:', event.stack);
                    
                    // Try to identify the cause
                    const recentClicks = clickEvents.filter(c => Date.now() - c.timestamp < 1000);
                    if (recentClicks.length > 0) {
                        console.log('Recent clicks that might have caused this:', recentClicks);
                    }
                }
            }
            
            lastScrollY = currentY;
            
            // Keep only recent events
            scrollEvents = scrollEvents.filter(e => Date.now() - e.timestamp < 10000);
        }
    }, true);
    
    // Track all click events
    document.addEventListener('click', function(e) {
        const event = {
            timestamp: Date.now(),
            target: e.target,
            tagName: e.target.tagName,
            className: e.target.className,
            id: e.target.id,
            href: e.target.href,
            type: e.target.type,
            scrollBefore: window.pageYOffset || document.documentElement.scrollTop || 0
        };
        
        clickEvents.push(event);
        
        console.log(`🖱️ CLICK: ${event.tagName}${event.className ? '.' + event.className.split(' ')[0] : ''}${event.id ? '#' + event.id : ''} at scroll ${event.scrollBefore}px`);
        
        // Check if click causes scroll change
        setTimeout(() => {
            const scrollAfter = window.pageYOffset || document.documentElement.scrollTop || 0;
            if (Math.abs(scrollAfter - event.scrollBefore) > 10) {
                console.warn(`⚠️ CLICK CAUSED SCROLL CHANGE: ${event.scrollBefore}px → ${scrollAfter}px`);
                console.log('Problematic element:', e.target);
            }
        }, 50);
        
        setTimeout(() => {
            const scrollAfter = window.pageYOffset || document.documentElement.scrollTop || 0;
            if (scrollAfter === 0 && event.scrollBefore > 20) {
                console.error('🚨 CLICK CAUSED SCROLL TO TOP!');
                console.log('Culprit element:', e.target);
                console.log('Element details:', {
                    tagName: e.target.tagName,
                    className: e.target.className,
                    id: e.target.id,
                    href: e.target.getAttribute('href'),
                    onclick: e.target.onclick,
                    role: e.target.getAttribute('role'),
                    dataAttributes: Array.from(e.target.attributes)
                        .filter(attr => attr.name.startsWith('data-'))
                        .map(attr => `${attr.name}="${attr.value}"`)
                });
            }
        }, 100);
        
        // Keep only recent clicks
        clickEvents = clickEvents.filter(c => Date.now() - c.timestamp < 10000);
    }, true);
    
    // Track focus events
    document.addEventListener('focusin', function(e) {
        const scrollBefore = window.pageYOffset || document.documentElement.scrollTop || 0;
        
        console.log(`🎯 FOCUS: ${e.target.tagName}${e.target.type ? '[' + e.target.type + ']' : ''} at scroll ${scrollBefore}px`);
        
        setTimeout(() => {
            const scrollAfter = window.pageYOffset || document.documentElement.scrollTop || 0;
            if (Math.abs(scrollAfter - scrollBefore) > 10) {
                console.warn(`⚠️ FOCUS CAUSED SCROLL CHANGE: ${scrollBefore}px → ${scrollAfter}px`);
                if (scrollAfter === 0 && scrollBefore > 20) {
                    console.error('🚨 FOCUS CAUSED SCROLL TO TOP!');
                    console.log('Input element:', e.target);
                }
            }
        }, 100);
    }, true);
    
    // Override scrollTo to see what's calling it
    const originalScrollTo = window.scrollTo;
    window.scrollTo = function(...args) {
        const stack = new Error().stack;
        
        let targetY = 0;
        if (typeof args[0] === 'object' && args[0].top !== undefined) {
            targetY = args[0].top;
        } else if (args.length >= 2) {
            targetY = args[1];
        }
        
        console.log(`📜 scrollTo called: target=${targetY}px`);
        
        if (targetY === 0) {
            console.error('🚨 scrollTo(0) called - POTENTIAL CULPRIT!');
            console.log('Call stack:', stack);
        }
        
        return originalScrollTo.apply(this, args);
    };
    
    // Global error handler to catch any script errors that might cause scroll issues
    window.addEventListener('error', function(e) {
        console.warn('Script error detected:', e.error);
        console.log('This error might be related to scroll issues');
    });
    
    // Log when page is fully loaded
    window.addEventListener('load', function() {
        console.log('🚀 Page fully loaded, scroll debug active');
        console.log('Current scroll position:', window.pageYOffset || document.documentElement.scrollTop || 0);
    });
    
    // Periodic status report
    setInterval(() => {
        const currentY = window.pageYOffset || document.documentElement.scrollTop || 0;
        console.log(`📊 Status: scroll=${currentY}px, recent events: ${scrollEvents.length} scrolls, ${clickEvents.length} clicks`);
    }, 10000);
    
    // Export debug functions to window for manual inspection
    window.scrollDebug = {
        getRecentScrolls: () => scrollEvents.slice(-10),
        getRecentClicks: () => clickEvents.slice(-10),
        getCurrentScroll: () => window.pageYOffset || document.documentElement.scrollTop || 0,
        logState: () => {
            console.log('=== SCROLL DEBUG STATE ===');
            console.log('Current scroll:', window.pageYOffset || document.documentElement.scrollTop || 0);
            console.log('Recent scrolls:', scrollEvents.slice(-5));
            console.log('Recent clicks:', clickEvents.slice(-5));
        }
    };
    
})();