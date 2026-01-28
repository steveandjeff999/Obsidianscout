/**
 * FRC Scouting Platform 
 * Team 5454 Scout 2026
 * Modern UI and Interaction JavaScript
 */

/**
 * Apply per-user preferences stored in localStorage across the site.
 * - font_size: number => sets root font-size and CSS variable
 * - reduced_motion: true/false => disables animations/transitions when enabled
 * - compact_density: true/false => toggles compact-density class on body
 * - darkMode: true/false => toggles dark-mode classes
 * - obsidian_sidebar_collapsed: 1/0 or true/false => calls setSidebarCollapsed if available
 */
function applyUserPreferences() {
    try {
        // Font size
        try {
            const fs = localStorage.getItem('font_size');
            if (fs && /^[0-9]+$/.test(fs)) {
                document.documentElement.style.setProperty('--obsidian-base-font-size', fs + 'px');
                document.documentElement.style.fontSize = fs + 'px';
                // Don't force body font-size unless explicitly needed
                document.body.style.fontSize = '';
            } else {
                document.documentElement.style.removeProperty('--obsidian-base-font-size');
                document.documentElement.style.fontSize = '';
                document.body.style.fontSize = '';
            }
        } catch (e) { console.warn('applyUserPreferences font_size error', e); }

        // Reduced motion
        try {
            const reduced = localStorage.getItem('reduced_motion');
            const id = 'reducedMotionStyle';
            let s = document.getElementById(id);
            if (reduced === 'true') {
                if (!s) {
                    s = document.createElement('style');
                    s.id = id;
                    s.textContent = '* { transition-duration: 0s !important; animation-duration: 0s !important; animation-delay: 0s !important; }';
                    document.head.appendChild(s);
                }
                document.documentElement.classList.add('reduced-motion');
            } else {
                if (s && s.parentNode) s.parentNode.removeChild(s);
                document.documentElement.classList.remove('reduced-motion');
            }
        } catch (e) { console.warn('applyUserPreferences reduced_motion error', e); }

        // Compact density
        try {
            const compact = localStorage.getItem('compact_density');
            if (compact === 'true') document.body.classList.add('compact-density'); else document.body.classList.remove('compact-density');
        } catch (e) { console.warn('applyUserPreferences compact_density error', e); }

        // Dark mode
        try {
            const dark = localStorage.getItem('darkMode');
            if (dark === 'true') { document.documentElement.classList.add('dark-mode'); document.body.classList.add('dark-mode'); }
            else { document.documentElement.classList.remove('dark-mode'); document.body.classList.remove('dark-mode'); }
        } catch (e) { console.warn('applyUserPreferences darkMode error', e); }

        // Accent color (per-user override stored in localStorage)
        try {
            const accent = localStorage.getItem('accent_color');
            if (accent && /^#([0-9A-F]{3}){1,2}$/i.test(accent)) {
                document.documentElement.style.setProperty('--accent', accent);
                document.documentElement.style.setProperty('--nav-accent', accent);
                // derive rgb and set --accent-rgb for components that use rgb variants
                const toRgb = (hex => {
                    const v = hex.replace('#','');
                    const r = parseInt(v.length === 3 ? v[0]+v[0] : v.slice(0,2),16);
                    const g = parseInt(v.length === 3 ? v[1]+v[1] : v.slice(2,4),16);
                    const b = parseInt(v.length === 3 ? v[2]+v[2] : v.slice(4,6),16);
                    return `${r},${g},${b}`;
                })(accent);
                document.documentElement.style.setProperty('--accent-rgb', toRgb);
            } else {
                document.documentElement.style.removeProperty('--accent');
                document.documentElement.style.removeProperty('--nav-accent');
                document.documentElement.style.removeProperty('--accent-rgb');
            }
        } catch (e) { console.warn('applyUserPreferences accent error', e); }

        // Sidebar collapsed (use existing helper if available)
        try {
            const sb = localStorage.getItem('obsidian_sidebar_collapsed');
            if (typeof setSidebarCollapsed === 'function') {
                setSidebarCollapsed(sb === '1' || sb === 'true');
            } else {
                // Fallback: toggle a class so CSS can adapt
                if (sb === '1' || sb === 'true') document.body.classList.add('sidebar-collapsed'); else document.body.classList.remove('sidebar-collapsed');
            }
        } catch (e) { console.warn('applyUserPreferences sidebar error', e); }

    } catch (e) {
        console.warn('applyUserPreferences error', e);
    }
}

// Run on initial load and whenever localStorage changes in another tab
document.addEventListener('DOMContentLoaded', function(){ try{ applyUserPreferences(); }catch(e){} });
window.addEventListener('storage', function(){ try{ applyUserPreferences(); }catch(e){} });
// Expose globally
window.applyUserPreferences = applyUserPreferences;

// Global share button helpers - make them available on any page
window.showShareReadyButtons = function(scope) {
    try {
        const selector = scope ? `.share-when-ready[data-share-scope="${scope}"]` : '.share-when-ready';
        document.querySelectorAll(selector).forEach(btn => btn.classList.remove('d-none'));
    } catch (e) { console.warn('showShareReadyButtons error', e); }
};
window.hideShareReadyButtons = function(scope) {
    try {
        const selector = scope ? `.share-when-ready[data-share-scope="${scope}"]` : '.share-when-ready';
        document.querySelectorAll(selector).forEach(btn => btn.classList.add('d-none'));
    } catch (e) { console.warn('hideShareReadyButtons error', e); }
};

document.addEventListener('DOMContentLoaded', function() {
    // Register service worker for offline support
    if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
            .then(reg => {
                console.log('Service Worker registered:', reg.scope);
                // Force update check
                reg.update();
                // Listen for messages from the service worker (offline/online notifications)
                try {
                    navigator.serviceWorker.addEventListener('message', function(event) {
                        if (event && event.data && event.data.type === 'offline-banner') {
                            showOfflineBanner(!!event.data.show);
                        }
                    });
                } catch (e) {
                    // Some browsers may not support addEventListener on navigator.serviceWorker
                    console.warn('Could not attach serviceWorker message listener', e);
                }
            })
            .catch(err => {
                console.warn('Service Worker registration failed:', err);
            });
    }

    // Show or hide a small yellow offline banner across the top of the page
    function showOfflineBanner(show) {
        try {
            let banner = document.getElementById('offline-banner');
            if (show) {
                if (!banner) {
                    banner = document.createElement('div');
                    banner.id = 'offline-banner';
                    banner.setAttribute('role','status');
                    // Position fixed so it stays at top; we'll offset below any topbar
                    banner.style.position = 'fixed';
                    banner.style.left = '0';
                    banner.style.right = '0';
                    banner.style.zIndex = '99999';

                    // Stronger, high-contrast colors for dark mode and readability
                    const prefersDark = document.body.classList.contains('dark-mode') || document.body.classList.contains('theme-dark') || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
                    banner.style.background = prefersDark ? '#ffb74d' : '#fff3bf';
                    banner.style.color = '#0b0b0b';
                    banner.style.padding = '8px 12px';
                    banner.style.textAlign = 'center';
                    banner.style.fontSize = '13px';
                    banner.style.fontWeight = '600';
                    banner.style.boxSizing = 'border-box';
                    banner.style.boxShadow = prefersDark ? '0 2px 8px rgba(0,0,0,0.6)' : '0 2px 4px rgba(0,0,0,0.06)';
                    banner.style.borderBottom = '1px solid rgba(0,0,0,0.12)';
                    banner.style.opacity = '0';
                    banner.style.transition = 'opacity 0.25s ease, transform 0.15s ease';
                    banner.style.pointerEvents = 'auto';
                    banner.textContent = 'You appear to be offline — showing cached content';

                    // Append banner and measure
                    document.body.appendChild(banner);
                    const topbar = document.querySelector('.topbar') || document.querySelector('.navbar') || null;
                    const sidebar = document.getElementById('appSidebar') || document.querySelector('.sidebar') || null;
                    const topOffset = topbar ? topbar.offsetHeight : 0;
                    // Position banner below topbar
                    banner.style.top = topOffset + 'px';

                    // Compute left offset to avoid overlapping sidebar (when visible)
                    let leftOffset = 0;
                    try {
                        if (sidebar && window.getComputedStyle(sidebar).display !== 'none' && window.innerWidth >= 900) {
                            const rect = sidebar.getBoundingClientRect();
                            leftOffset = rect.width || 0;
                        }
                    } catch (e) { leftOffset = 0; }

                    // Apply left offset and width so banner doesn't cross the sidebar
                    banner.style.left = leftOffset + 'px';
                    banner.style.width = `calc(100% - ${leftOffset}px)`;

                    // Add padding to body so content isn't covered by the banner
                    const measured = banner.offsetHeight || 36;
                    const currentPadding = parseInt(window.getComputedStyle(document.body).paddingTop) || 0;
                    banner.dataset._paddingAdded = String(measured);
                    document.body.style.paddingTop = (currentPadding + measured) + 'px';

                    // Make banner persistent (not closable) per request — no close button added

                    // Attach resize and sidebar-toggle handlers once so banner repositions responsively
                    if (!banner.dataset._listenerAttached) {
                        const reposition = () => {
                            try {
                                const topbar = document.querySelector('.topbar') || document.querySelector('.navbar') || null;
                                const sidebar = document.getElementById('appSidebar') || document.querySelector('.sidebar') || null;
                                const topOffset = topbar ? topbar.offsetHeight : 0;
                                banner.style.top = topOffset + 'px';

                                let leftOffset = 0;
                                if (sidebar && window.getComputedStyle(sidebar).display !== 'none' && window.innerWidth >= 900) {
                                    const rect = sidebar.getBoundingClientRect();
                                    leftOffset = rect.width || 0;
                                }
                                banner.style.left = leftOffset + 'px';
                                banner.style.width = `calc(100% - ${leftOffset}px)`;

                                // Adjust padding if height changed
                                const measuredNow = banner.offsetHeight || 36;
                                const previous = parseInt(banner.dataset._paddingAdded || '0') || 0;
                                if (measuredNow !== previous) {
                                    const currentPaddingNow = parseInt(window.getComputedStyle(document.body).paddingTop) || 0;
                                    const basePadding = Math.max(0, currentPaddingNow - previous);
                                    document.body.style.paddingTop = (basePadding + measuredNow) + 'px';
                                    banner.dataset._paddingAdded = String(measuredNow);
                                }
                            } catch (e) { /* ignore */ }
                        };

                        window.addEventListener('resize', reposition);
                        const sidebarToggle = document.getElementById('sidebarToggle');
                        if (sidebarToggle) sidebarToggle.addEventListener('click', () => setTimeout(reposition, 260));
                        banner.dataset._listenerAttached = '1';
                    }
                }
                // Recalculate positioning in case layout changed since last show
                try {
                    const topbar = document.querySelector('.topbar') || document.querySelector('.navbar') || null;
                    const sidebar = document.getElementById('appSidebar') || document.querySelector('.sidebar') || null;
                    const topOffset = topbar ? topbar.offsetHeight : 0;
                    banner.style.top = topOffset + 'px';

                    let leftOffset = 0;
                    if (sidebar && window.getComputedStyle(sidebar).display !== 'none' && window.innerWidth >= 900) {
                        const rect = sidebar.getBoundingClientRect();
                        leftOffset = rect.width || 0;
                    }
                    banner.style.left = leftOffset + 'px';
                    banner.style.width = `calc(100% - ${leftOffset}px)`;

                    // Adjust body padding if banner height changed
                    const measured = banner.offsetHeight || 36;
                    const previous = parseInt(banner.dataset._paddingAdded || '0') || 0;
                    if (measured !== previous) {
                        try {
                            const currentPadding = parseInt(window.getComputedStyle(document.body).paddingTop) || 0;
                            // remove previous then add new
                            const basePadding = Math.max(0, currentPadding - previous);
                            document.body.style.paddingTop = (basePadding + measured) + 'px';
                            banner.dataset._paddingAdded = String(measured);
                        } catch (e) {}
                    }
                } catch (e) {}

                // Reveal
                requestAnimationFrame(() => { banner.style.opacity = '1'; });
            } else {
                if (banner) {
                    banner.style.opacity = '0';
                    setTimeout(() => {
                        try {
                            const added = parseInt(banner.dataset._paddingAdded || '0');
                            if (added) {
                                const currentPadding = parseInt(window.getComputedStyle(document.body).paddingTop) || 0;
                                const newPadding = Math.max(0, currentPadding - added);
                                document.body.style.paddingTop = newPadding + 'px';
                            }
                        } catch (e) {}
                        banner.remove();
                    }, 300);
                }
            }

            // Set global network banner flag and re-evaluate server reachability/UI
            try {
                window.scoutingNetworkOffline = !!show;
                if (typeof window.refreshServerStatus === 'function') {
                    // Let offline manager decide which button to show based on server availability
                    window.refreshServerStatus();
                } else if (typeof window.updateSaveButtonVisibility === 'function') {
                    window.updateSaveButtonVisibility();
                }
            } catch (e) { /* ignore */ }

        } catch (e) {
            console.warn('showOfflineBanner error', e);
        }
    }

    // Optional: react to browser online/offline events too
    window.addEventListener('online', function() { showOfflineBanner(false); });
    window.addEventListener('offline', function() { showOfflineBanner(true); });
    
    // Initialize all tooltips
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    if (tooltipTriggerList.length) {
        [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
    }
    
    // Initialize all popovers
    const popoverTriggerList = document.querySelectorAll('[data-bs-toggle="popover"]');
    if (popoverTriggerList.length) {
        [...popoverTriggerList].map(popoverTriggerEl => new bootstrap.Popover(popoverTriggerEl));
    }
    
    // Initialize bootstrap toasts ONLY if they have the 'show' class
    const toastElList = document.querySelectorAll('.toast.show');
    if (toastElList.length) {
        [...toastElList].map(toastEl => {
            const toast = new bootstrap.Toast(toastEl, {
                autohide: true,
                delay: 5000
            });
            toast.show();
            // Add auto-removal after hiding
            toastEl.addEventListener('hidden.bs.toast', () => {
                setTimeout(() => {
                    toastEl.remove();
                }, 300);
            });
        });
    }
    
    // Dynamic page transitions
    initPageTransitions();
    
    // Counter buttons for scouting form
    initializeCounters();
    
    // Star rating system
    initializeRatings();
    
    // QR code generation
    const generateQRButton = document.getElementById('generateQR');
    if (generateQRButton) {
        generateQRButton.addEventListener('click', generateQRCode);
    }
    
    // Match period tabs with smooth transitions
    initializeMatchPeriodTabs();
    
    // Initialize auto period timer feature
    initializeAutoPeriodTimer();
    
    // Form validation with better user feedback
    validateForms();
    
    // Enable "Start Scouting" button when team and match are selected
    enableStartScoutingButton();
    
    // Initialize charts if visualization page is loaded
    if (document.querySelector('.chart-container')) {
        initializeCharts();
    }
    
    // Render Plotly graphs if any are present
    if (document.querySelector('.plotly-graph')) {
        renderPlotlyGraphs();
    }
    
    // Initialize points calculation if scouting form is present
    initializePointsCalculation();
    
    // Data table initialization
    initializeDataTables();
    
    // Add event listeners for the import/export functionality
    setupImportExport();
    
    // Fix modal positioning to prevent flashing/jumping
    setupModalBehavior();
    
    // Initialize search functionality
    setupSearch();
    
    // Handle loading states for buttons and forms
    setupLoadingBehavior();
    
    // Setup global keyboard shortcuts
    setupKeyboardShortcuts();
    
    // Initialize offline data manager
    setupOfflineDataManager();

    // Observe strategy results visibility to toggle strategy share button
    try {
        const strategyResultsEl = document.getElementById('strategyResults');
        if (strategyResultsEl) {
            const mo = new MutationObserver((mutationsList) => {
                mutationsList.forEach(m => {
                    // When style or class changes, check visibility
                    const isVisible = !strategyResultsEl.classList.contains('d-none') && strategyResultsEl.style.display !== 'none';
                    if (isVisible) {
                        if (typeof window.showShareReadyButtons === 'function') window.showShareReadyButtons('strategy');
                    } else {
                        if (typeof window.hideShareReadyButtons === 'function') window.hideShareReadyButtons('strategy');
                    }
                });
            });
            mo.observe(strategyResultsEl, { attributes: true, attributeFilter: ['class', 'style'] });
            // Initial state
            const isVisibleNow = !strategyResultsEl.classList.contains('d-none') && strategyResultsEl.style.display !== 'none';
            if (isVisibleNow) {
                if (typeof window.showShareReadyButtons === 'function') window.showShareReadyButtons('strategy');
            }
        }
    } catch (e) { /* silently ignore observer failures */ }
    
    // Initialize scouting form with save functionality
    initScoutingForm();
    
    // Double-confirm delete logic for /data/manage
    let deleteConfirmTimeouts = {};
    document.querySelectorAll('.double-confirm-delete').forEach(function(btn) {
        btn.addEventListener('click', function(e) {
            const entryId = btn.getAttribute('data-entry-id');
            if (!deleteConfirmTimeouts[entryId]) {
                // First click: show notification
                showDeleteConfirmNotification(btn, entryId);
                deleteConfirmTimeouts[entryId] = setTimeout(() => {
                    deleteConfirmTimeouts[entryId] = null;
                    btn.textContent = 'Delete';
                    btn.classList.remove('btn-warning');
                    btn.classList.add('btn-danger');
                }, 5000);
                btn.textContent = 'Click again to confirm';
                btn.classList.remove('btn-danger');
                btn.classList.add('btn-warning');
            } else {
                // Second click: submit hidden form
                clearTimeout(deleteConfirmTimeouts[entryId]);
                deleteConfirmTimeouts[entryId] = null;
                // Find or create a hidden form and submit
                let form = document.getElementById('delete-form-' + entryId);
                if (!form) {
                    form = document.createElement('form');
                    form.method = 'POST';
                    form.action = `/data/delete/${entryId}`;
                    form.style.display = 'none';
                    form.id = 'delete-form-' + entryId;
                    document.body.appendChild(form);
                }
                form.submit();
            }
        });
    });
});

// Global error handlers to catch uncaught exceptions and promise rejections
window.addEventListener('error', function(e) {
    try {
        console.error('Global JS error:', e.message || e.error || e);
    } catch (err) { console.warn('Error in global error handler', err); }
});

window.addEventListener('unhandledrejection', function(ev) {
    try {
        console.warn('Unhandled promise rejection:', ev.reason);
    } catch (err) { console.warn('Error in unhandledrejection handler', err); }
});

/**
 * Setup page transitions for smoother navigation experience
 */
function initPageTransitions() {
    // Add a class to the body when page is fully loaded
    document.body.classList.add('page-loaded');
    
    // Listen for link clicks and add page exit animation
    document.querySelectorAll('a:not([target="_blank"]):not([href^="#"]):not(.modal-trigger):not(.no-transition)').forEach(link => {
            link.addEventListener('click', function(e) {
                // Skip if modifier keys are pressed
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                
                const href = this.getAttribute('href');
                
                // Skip if it's an anchor or javascript link
                if (!href || href.startsWith('#') || href.startsWith('javascript:')) return;
                
                // Skip API calls and downloads
                if (href.includes('/api/') || this.getAttribute('download')) return;
                
                e.preventDefault();
                
                // Show loading indicator
                document.body.classList.add('page-transition');
                
                // After a short delay, navigate to the new page
                setTimeout(() => {
                    window.location.href = href;
                }, 300);
            });
    });
    
    // Add loading overlay functionality
    window.showLoadingOverlay = function() {
        const loadingOverlay = document.getElementById('loading-overlay');
        if (loadingOverlay) {
            loadingOverlay.classList.remove('d-none');
        }
    };
    
    window.hideLoadingOverlay = function() {
        const loadingOverlay = document.getElementById('loading-overlay');
        if (loadingOverlay) {
            loadingOverlay.classList.add('d-none');
        }
    };
}

/**
 * Initialize counter buttons for scouting form with improved UX
 */
function initializeCounters() {
    // Create a set to track which buttons we've already attached listeners to
    const processedButtons = new Set();
    
    // First handle buttons inside counter-container elements (supports configurable step and optional alternate +/- buttons)
    const counters = document.querySelectorAll('.counter-container');
    
    counters.forEach(counter => {
        const buttons = counter.querySelectorAll('.btn-counter');
        const countInput = counter.querySelector('input[type="number"]');
        if (!buttons.length || !countInput) return;

        // Add processed buttons
        buttons.forEach(b => processedButtons.add(b));

        const clamp = (val, min, max) => {
            if (!isNaN(min) && val < min) val = min;
            if (!isNaN(max) && max !== null && val > max) val = max;
            return val;
        };

        const updateCounter = (delta) => {
            let current = parseInt(countInput.value || 0);
            const min = parseInt(countInput.min || 0);
            const max = (countInput.max !== undefined && countInput.max !== '') ? parseInt(countInput.max) : null;
            let newValue = clamp(current + delta, min, max);

            // Add a pulse animation
            countInput.classList.add('counter-pulse');
            setTimeout(() => {
                countInput.classList.remove('counter-pulse');
            }, 300);

            countInput.value = newValue;
            countInput.dispatchEvent(new Event('change'));
            updatePointsCalculation();

            // Update disable state for all buttons in this container
            buttons.forEach(b => {
                if (b.classList.contains('btn-decrement')) {
                    b.disabled = parseInt(countInput.value) <= min;
                }
                if (b.classList.contains('btn-increment') && max !== null) {
                    b.disabled = parseInt(countInput.value) >= max;
                }
            });
        };

        // Attach click handlers to any .btn-counter in the container
        buttons.forEach(btn => {
            btn.addEventListener('click', () => {
                // Determine step: prefer data-step attribute, otherwise parse integer from text content
                let step = 1;
                if (typeof btn.dataset.step !== 'undefined' && btn.dataset.step !== '') {
                    step = Math.abs(parseInt(btn.dataset.step)) || 1;
                } else {
                    const txt = (btn.textContent || '').trim();
                    const m = txt.match(/-?\d+/);
                    if (m) step = Math.abs(parseInt(m[0])) || 1;
                }
                const sign = btn.classList.contains('btn-decrement') ? -1 : 1;
                updateCounter(sign * step);

                // Add visual feedback
                btn.classList.add('btn-pulse');
                setTimeout(() => btn.classList.remove('btn-pulse'), 300);
            });
        });

        // Set initial button disabled state
        const minVal = parseInt(countInput.min || 0);
        const maxVal = (countInput.max !== undefined && countInput.max !== '') ? parseInt(countInput.max) : null;
        buttons.forEach(b => {
            if (b.classList.contains('btn-decrement')) b.disabled = parseInt(countInput.value) <= minVal;
            if (b.classList.contains('btn-increment') && maxVal !== null) b.disabled = parseInt(countInput.value) >= maxVal;
        });

        // Keyboard shortcuts - use single-step arrows
        countInput.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowUp') {
                e.preventDefault();
                updateCounter(1);
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                updateCounter(-1);
            }
        });

        // If alt buttons exist, arrange controls into a compact grid (matches visual spec)
        try {
            const hasAlt = counter.querySelector('.btn-alt');
            if (hasAlt) counter.classList.add('counter-grid'); else counter.classList.remove('counter-grid');
        } catch (e) { /* ignore */ }

    });

    // Now handle buttons with data-target attributes that weren't already processed
    const targetCounters = document.querySelectorAll('[data-target]');
    targetCounters.forEach(btn => {
        if (!btn.classList.contains('btn-decrement') && !btn.classList.contains('btn-increment')) return;
        
        // Skip if we've already processed this button
        if (processedButtons.has(btn)) return;
        
        btn.addEventListener('click', () => {
            const targetId = btn.dataset.target;
            const input = document.getElementById(targetId);
            if (!input) return;

            // Prefer data-step attribute; fallback to parsing from button text
            let step = 1;
            if (typeof btn.dataset.step !== 'undefined' && btn.dataset.step !== '') {
                step = Math.abs(parseInt(btn.dataset.step)) || 1;
            } else {
                const txt = (btn.textContent || '').trim();
                const m = txt.match(/-?\d+/);
                if (m) step = Math.abs(parseInt(m[0])) || 1;
            }

            let newValue = parseInt(input.value || 0);
            const min = parseInt(input.min || 0);
            const max = (input.max !== undefined && input.max !== '') ? parseInt(input.max) : null;

            if (btn.classList.contains('btn-decrement')) {
                newValue = Math.max(min, newValue - step);
            } else if (btn.classList.contains('btn-increment')) {
                newValue = newValue + step;
                if (max !== null) newValue = Math.min(max, newValue);
            }

            input.value = newValue;
            input.dispatchEvent(new Event('change'));
            updatePointsCalculation();

            // Add visual feedback
            btn.classList.add('btn-pulse');
            setTimeout(() => btn.classList.remove('btn-pulse'), 300);
        });
    });

    // Move any alt buttons out to sit adjacent to the input for clarity (handles multiple templates)
    try {
        document.querySelectorAll('.counter-container').forEach(container => {
            const input = container.querySelector('input[type="number"]');
            if (!input) return;
            // Move decrement alt before input
            const decAlt = container.querySelector('.btn-decrement.btn-alt');
            if (decAlt) {
                // place immediately after primary decrement (insert after the primary element itself to avoid moving outside container)
                const primaryDec = container.querySelector('.btn-decrement:not(.btn-alt)');
                if (primaryDec) {
                    primaryDec.insertAdjacentElement('afterend', decAlt);
                    decAlt.style.display = 'inline-block';
                }
            }
            // Move increment alt after input
            const incAlt = container.querySelector('.btn-increment.btn-alt');
            if (incAlt) {
                const primaryInc = container.querySelector('.btn-increment:not(.btn-alt)');
                if (primaryInc) {
                    primaryInc.insertAdjacentElement('beforebegin', incAlt);
                    incAlt.style.display = 'inline-block';
                }
            }
        });
    } catch (err) {
        console.warn('moveAltButtons error', err);
    }

    // Detect counters that wrapped onto multiple lines and add a class so CSS
    // can adjust layout (and trigger a resize so spacing recalculates).
    try {
        document.querySelectorAll('.counter-container').forEach(container => {
            const children = Array.from(container.children).filter(c => c.offsetParent !== null);
            if (!children.length) return;
            const tops = children.map(c => Math.round(c.getBoundingClientRect().top));
            const uniqueTops = Array.from(new Set(tops));
            const wrapped = uniqueTops.length > 1;
            container.classList.toggle('counter-wrapped', wrapped);
            const card = container.closest('.card');
            if (card) card.classList.toggle('card-counter-wrapped', wrapped);
        });
        // Let other layout handlers (scale-ui) recompute spacing
        setTimeout(() => window.dispatchEvent(new Event('resize')), 60);
    } catch (err) {
        console.warn('counter wrap detection error', err);
    }

    // Initialize spinning counters (if admin enabled for team)
    function initializeSpinningCounters() {
        console.debug('spinning counters: initialize called');
        // Previously required server-side approval; now run per-user based on local preference
        if (!document.body.classList.contains('spinning-counters')) { console.debug('spinning counters: server-side not enabled (ignored) — running per-user preference'); }
        // Respect reduced-motion preference
        if (document.documentElement.classList.contains('reduced-motion')) { console.debug('spinning counters: reduced-motion enabled; abort'); return; }
        // Respect client-side preference (stored in localStorage 'spinning_counters_enabled')
        try { const localPref = localStorage.getItem('spinning_counters_enabled'); if (localPref === 'false' || localPref === '0') { console.debug('spinning counters: disabled by local pref'); return; } } catch (e) { /* ignore */ }

        // Support multiple counter container types used in templates
        const containerSelector = '.counter-container, .counter-control, .counter-shell, .input-group.counter-control, .counter-container-inline';
        let anyAdded = false;
        document.querySelectorAll(containerSelector).forEach(container => {
            // Normalise container element (some templates use nested structures)
            if (!container) return;
            // Don't add if already present (support legacy knob and new display)
            if (container.querySelector('.spin-knob, .spin-display')) return;
            // Prefer explicit counter inputs, fall back to any number input inside
            const input = container.querySelector('input.counter-input[type="number"]') || container.querySelector('input[type="number"]');
            if (!input) return;

            // Create a full-size spinning display that shows the value centered
            const display = document.createElement('div');
            display.className = 'spin-display';
            display.setAttribute('role','spinbutton');
            display.setAttribute('aria-label','Spinning counter');
            display.tabIndex = 0;

            const ring = document.createElement('div');
            ring.className = 'spin-ring';
            const valueEl = document.createElement('div');
            valueEl.className = 'spin-value';
            valueEl.textContent = input.value || '0';

            display.appendChild(ring);
            display.appendChild(valueEl);

            // Insert display and hide the original input (keep it in DOM for form submission)
            input.insertAdjacentElement('afterend', display);
            input.style.display = 'none';
            // Hide any button counters inside this container (we are replacing them)
            try { container.querySelectorAll('.btn-counter').forEach(b => { b.style.display = 'none'; }); } catch (e) {}
            anyAdded = true;

            // Pointer-based rotation handling applied to the display; ring rotates visually while value stays upright
            let pressing = false;
            let lastAngle = null;
            let accumulated = 0; // degrees
            let startValue = 0;

            function angleFromEvent(e) {
                const rect = display.getBoundingClientRect();
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;
                return Math.atan2(e.clientY - cy, e.clientX - cx) * 180 / Math.PI;
            }

            display.addEventListener('pointerdown', (e) => {
                try { display.setPointerCapture(e.pointerId); } catch (ex) {}
                pressing = true;
                lastAngle = null;
                accumulated = 0;
                startValue = parseInt(input.value || 0);
                e.preventDefault();
            });

            display.addEventListener('pointermove', (e) => {
                if (!pressing) return;
                const angle = angleFromEvent(e);
                if (lastAngle === null) {
                    lastAngle = angle;
                    return;
                }
                let delta = angle - lastAngle;
                if (delta > 180) delta -= 360;
                if (delta < -180) delta += 360;
                accumulated += delta;
                lastAngle = angle;

                // Each 0.125 rotation (45deg) increments by one
                const steps = Math.floor(accumulated / 45);
                if (steps !== 0) {
                    let newVal = startValue + steps;
                    const min = parseInt(input.min || 0);
                    const max = (input.max !== undefined && input.max !== '') ? parseInt(input.max) : null;
                    if (!isNaN(min)) newVal = Math.max(min, newVal);
                    if (max !== null && !isNaN(max)) newVal = Math.min(max, newVal);
                    input.value = newVal;
                    valueEl.textContent = newVal;
                    input.dispatchEvent(new Event('change'));
                }

                // Visual rotation feedback: rotate the ring only so the number stays upright
                ring.style.transform = `rotate(${accumulated}deg)`;
                e.preventDefault();
            });

            display.addEventListener('pointerup', (e) => {
                try { display.releasePointerCapture(e.pointerId); } catch (ex) {}
                pressing = false;
                accumulated = 0;
                ring.style.transform = '';
            });

            // Keyboard accessibility: left/right to change by 1
            display.addEventListener('keydown', (e) => {
                if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
                    e.preventDefault(); const v = parseInt(input.value || 0) + 1; input.value = v; valueEl.textContent = v; input.dispatchEvent(new Event('change'));
                } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
                    e.preventDefault(); const v = Math.max(parseInt(input.min || 0), parseInt(input.value || 0) - 1); input.value = v; valueEl.textContent = v; input.dispatchEvent(new Event('change'));
                }
            });

            // Update display when input changes (keeps sync if changed programmatically)
            input.addEventListener('change', () => { try { valueEl.textContent = input.value || '0'; } catch(e){} });

            // Prevent touch-based scrolling while rotating
            display.style.touchAction = 'none';
        });
        // If we added ANY knobs, mark the UI as active so CSS can hide buttons globally
        try { if (anyAdded) document.body.classList.add('spinning-counters-active'); } catch(e) {}
    }

    // Call during initialization
    try { initializeSpinningCounters(); } catch (err) { console.warn('initializeSpinningCounters error', err); }

    // Observe mutations and initialize spinning knobs when dynamic counters are added
    try {
        const observer = new MutationObserver((mutations) => {
            let added = false;
            const containerSelector = '.counter-container, .counter-control, .counter-shell, .input-group.counter-control, .counter-container-inline';
            for (const m of mutations) {
                for (const n of m.addedNodes) {
                    if (n.nodeType !== 1) continue;
                    try {
                        if ((n.matches && n.matches(containerSelector)) || (n.querySelector && n.querySelector(containerSelector))) { added = true; break; }
                    } catch (err) { /* ignore malformed selectors on non-elements */ }
                }
                if (added) break;
            }
            if (added) {
                try { initializeSpinningCounters(); } catch (e) { console.warn('initializeSpinningCounters (observer) error', e); }
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });

        // Teardown: remove knobs and restore buttons
        function teardownSpinningCounters() {
            try {
                // Remove knobs and displays
                document.querySelectorAll('.spin-knob, .spin-display').forEach(k => k.remove());
                // Restore visible buttons and inputs
                const containerSelector = '.counter-container, .counter-control, .counter-shell, .input-group.counter-control, .counter-container-inline';
                document.querySelectorAll(containerSelector).forEach(container => {
                    try { container.querySelectorAll('.btn-counter').forEach(b => { b.style.display = ''; }); } catch (e) {}
                    try { const input = container.querySelector('input[type="number"]'); if (input) input.style.display = ''; } catch(e) {}
                });
                // Clear active class
                try { document.body.classList.remove('spinning-counters-active'); } catch(e) {}
            } catch (err) {
                console.warn('teardownSpinningCounters error', err);
            }
        }

        // Re-init or teardown when local preference changes in another tab
        window.addEventListener('storage', (e) => {
            if (e.key === 'spinning_counters_enabled') {
                try {
                    if (e.newValue === 'false' || e.newValue === '0') {
                        teardownSpinningCounters();
                    } else {
                        initializeSpinningCounters();
                    }
                } catch (err) { console.warn('initialize/teardown (storage) error', err); }
            }
        });
    } catch (err) { console.warn('spinning counter observer setup failed', err); }
}

/**
 * Initialize star rating system with improved feedback
 */
function initializeRatings() {
    const ratingContainers = document.querySelectorAll('.rating-container');
    
    ratingContainers.forEach(container => {
        const stars = container.querySelectorAll('.rating-star');
        const hiddenInput = container.parentElement.querySelector('input[type="hidden"]');
        
        // Show current rating on load
        if (hiddenInput && hiddenInput.value) {
            const currentRating = parseInt(hiddenInput.value);
            stars.forEach((s, i) => {
                if (stars.length - i <= currentRating) {
                    s.classList.add('active');
                }
            });
        }
        
        // Update rating when clicking stars
        stars.forEach((star, index) => {
            // Show rating preview on hover
            star.addEventListener('mouseenter', () => {
                // Reset all stars
                stars.forEach(s => s.classList.remove('hover'));
                
                // Highlight stars up to the hovered one
                for (let i = 0; i <= index; i++) {
                    stars[i].classList.add('hover');
                }
            });
            
            // Reset on mouse leave
            container.addEventListener('mouseleave', () => {
                stars.forEach(s => s.classList.remove('hover'));
            });
            
            // Set rating on click
            star.addEventListener('click', () => {
                const rating = stars.length - index;
                
                // Update hidden input
                if (hiddenInput) {
                    hiddenInput.value = rating;
                    hiddenInput.dispatchEvent(new Event('change'));
                }
                
                // Update visual state with animation
                stars.forEach((s, i) => {
                    s.classList.remove('active');
                    s.classList.remove('animate-star');
                });
                
                setTimeout(() => {
                    stars.forEach((s, i) => {
                        if (i >= index) {
                            s.classList.add('active');
                            s.classList.add('animate-star');
                        }
                    });
                }, 10);
                
                // Show feedback toast
                showToast(`Rating set to ${rating} stars`, 'info');
            });
        });
    });
}

/**
 * Display toast notification
 * @param {string} message - The message to display
 * @param {string} type - The type of toast (success, danger, warning, info)
 * @param {number} duration - Duration in milliseconds to show the toast (default 3000)
 */
function showToast(message, type = 'info', duration = 3000) {
    const toastContainer = document.querySelector('.toast-container');
    if (!toastContainer) return;
    
    // Create new toast element
    const toastId = 'toast-' + Date.now();
    const toast = document.createElement('div');
    toast.className = `toast show`;
    toast.id = toastId;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    
    // Toast content based on type
    let icon;
    switch (type) {
        case 'success': icon = 'fa-check-circle'; break;
        case 'danger': icon = 'fa-exclamation-triangle'; break;
        case 'warning': icon = 'fa-exclamation-circle'; break;
        default: icon = 'fa-info-circle';
    }
    
    toast.innerHTML = `
        <div class="toast-header bg-${type} ${['success', 'danger', 'primary'].includes(type) ? 'text-white' : ''}">
            <i class="fas ${icon} me-2"></i>
            <strong class="me-auto">Notification</strong>
            <small>Just now</small>
            <button type="button" class="btn-close ${['success', 'danger', 'primary'].includes(type) ? 'btn-close-white' : ''}" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
        <div class="toast-body">
            ${message}
        </div>
    `;
    
    // Add toast to container
    toastContainer.appendChild(toast);
    
    // Initialize Bootstrap toast
    const bsToast = new bootstrap.Toast(toast, {
        autohide: true,
        delay: duration
    });
    
    // Show the toast
    bsToast.show();
    
    // Remove from DOM after hiding
    toast.addEventListener('hidden.bs.toast', () => {
        setTimeout(() => {
            toast.remove();
        }, 300);
    });
}

/**
 * Generate QR code from form data with mobile-first responsive design
 * Optimized for visibility on all screen sizes, especially mobile devices
 */
function generateQRCode() {
    const form = document.getElementById('scouting-form');
    const qrcodeContainer = document.getElementById('qrcode');
    
    if (!form || !qrcodeContainer) return;
    
    // Show loading animation
    qrcodeContainer.innerHTML = '<div class="d-flex justify-content-center my-4"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div></div>';
    
    // Check if QRCode library is available
    if (typeof QRCode === 'undefined') {
        console.error('QRCode library not loaded');
        qrcodeContainer.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle me-2"></i>
                Error: QR Code library not loaded. Please check your internet connection.
            </div>
        `;
        showToast('Failed to load QR Code library', 'danger');
        return;
    }
    
    // Slight delay to ensure loading animation is visible
    setTimeout(() => {
        try {
            // Clear loading animation
            qrcodeContainer.innerHTML = '';
            
            // Get all form data
            const formData = new FormData(form);
            const formObject = {};
            
            // Process all form fields
            formData.forEach((value, key) => {
                const element = form.elements[key];
                
                // Handle different input types appropriately
                if (element && element.type === 'checkbox') {
                    formObject[key] = element.checked;
                } else if (element && element.type === 'number' || (!isNaN(value) && value !== '')) {
                    // Convert numeric values
                    formObject[key] = Number(value);
                } else {
                    formObject[key] = value;
                }
            });
            
            // Ensure checkboxes that are unchecked are included as false
            const allCheckboxes = form.querySelectorAll('input[type="checkbox"]');
            allCheckboxes.forEach(checkbox => {
                if (!formObject.hasOwnProperty(checkbox.id)) {
                    formObject[checkbox.id] = false;
                }
            });
            
            // Add calculated points to the data
            const pointsElements = document.querySelectorAll('.points-display');
            pointsElements.forEach(element => {
                const metricId = element.dataset.metricId;
                if (metricId) {
                    const pointsValue = element.querySelector('.points-value');
                    if (pointsValue) {
                        formObject[metricId + '_points'] = parseInt(pointsValue.textContent || '0');
                    }
                }
            });

            // Defensive fallback: ensure scout_name is populated even if the input was left blank
            try {
                const scoutField = form.elements['scout_name'] || document.getElementById('scout_name');
                const fallbackScout = (scoutField && scoutField.placeholder) ? scoutField.placeholder : (scoutField && scoutField.value) ? scoutField.value : 'Unknown';
                if (!formObject.scout_name || (typeof formObject.scout_name === 'string' && formObject.scout_name.trim() === '')) {
                    formObject.scout_name = fallbackScout;
                }
            } catch (e) {
                // ignore any issues from missing elements
            }
            
            // Add metadata
            formObject.generated_at = new Date().toISOString();
            formObject.offline_generated = true;
            
            // For debugging
            console.log("Complete form data for QR:", formObject);
            
            // Create JSON string with complete form data
            const jsonString = JSON.stringify(formObject);
            
            // Log the size to help with debugging
            const jsonSizeKB = (jsonString.length / 1024).toFixed(2);
            console.log(`QR data size: ${jsonSizeKB} KB, ${jsonString.length} characters`);
            
            // Calculate responsive QR code size based on viewport
            // Mobile-first: allow the QR to grow to most of the available page area
            const viewportWidth = window.innerWidth;
            const viewportHeight = window.innerHeight;
            const modalPadding = 40; // smaller padding so QR can use more space

            // Available area considering modal chrome/header/footer
            const availableWidth = Math.max(160, viewportWidth - modalPadding);
            const availableHeight = Math.max(160, viewportHeight - (modalPadding + 120));

            // On small devices, favor filling most of the viewport (but keep some breathing room)
            let qrSize;
            if (viewportWidth <= 640) {
                qrSize = Math.floor(Math.min(availableWidth * 0.92, availableHeight * 0.78));
            } else if (viewportWidth <= 1200) {
                qrSize = Math.floor(Math.min(availableWidth * 0.9, 640));
            } else {
                qrSize = Math.min(availableWidth, 520);
            }

            // Enforce sensible absolute bounds
            qrSize = Math.max(160, Math.min(qrSize, 800));
            
            console.log(`Viewport: ${viewportWidth}px, QR Size: ${qrSize}px`);
            
            // Clear any previous inline styles
            qrcodeContainer.style.cssText = '';
            
            // Apply responsive container styles
            qrcodeContainer.style.width = '100%';
            qrcodeContainer.style.maxWidth = qrSize + 'px';
            qrcodeContainer.style.margin = '0 auto';
            qrcodeContainer.style.padding = '0';
            qrcodeContainer.style.display = 'flex';
            qrcodeContainer.style.alignItems = 'center';
            qrcodeContainer.style.justifyContent = 'center';
            qrcodeContainer.style.minHeight = 'auto';
            
            // Generate QR code with responsive sizing
            try {
                // Clear previous content
                qrcodeContainer.innerHTML = '';
                
                // Create wrapper div for better control
                const qrWrapper = document.createElement('div');
                qrWrapper.style.cssText = `
                    width: 100%;
                    max-width: ${qrSize}px;
                    aspect-ratio: 1;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    background: #ffffff;
                    padding: 16px;
                    box-sizing: border-box;
                    border-radius: 12px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                `;
                qrcodeContainer.appendChild(qrWrapper);
                
                // Generate QR code inside wrapper
                new QRCode(qrWrapper, {
                    text: jsonString,
                    width: qrSize - 32, // Account for padding
                    height: qrSize - 32,
                    colorDark: "#000000",
                    colorLight: "#ffffff",
                    correctLevel: QRCode.CorrectLevel.M,
                    typeNumber: 0
                });
                
                // Style the generated elements for maximum visibility
                setTimeout(() => {
                    const qrCanvas = qrWrapper.querySelector('canvas');
                    const qrImg = qrWrapper.querySelector('img');
                    
                    // Detect Android
                    const isAndroid = /Android/i.test(navigator.userAgent);
                    console.log('Platform detected:', isAndroid ? 'Android' : 'iOS/Desktop');
                    
                    if (isAndroid) {
                        // ANDROID-SPECIFIC: Use canvas directly, it renders better on Android
                        if (qrImg && qrImg.parentNode) {
                            qrImg.parentNode.removeChild(qrImg);
                        }
                        
                        if (qrCanvas) {
                            qrCanvas.style.cssText = `
                                width: 100% !important;
                                height: auto !important;
                                max-width: ${qrSize - 32}px !important;
                                display: block !important;
                                margin: 0 auto !important;
                                image-rendering: pixelated !important;
                                -webkit-transform: translateZ(0) !important;
                            `;
                            console.log('Android: Using canvas for QR display');
                        }
                    } else {
                        // iOS/DESKTOP: Remove canvas, use image
                        if (qrCanvas && qrCanvas.parentNode) {
                            qrCanvas.parentNode.removeChild(qrCanvas);
                        }
                        
                        if (qrImg) {
                            qrImg.style.cssText = `
                                width: 100% !important;
                                height: 100% !important;
                                max-width: ${qrSize - 32}px !important;
                                max-height: ${qrSize - 32}px !important;
                                display: block !important;
                                margin: 0 auto !important;
                                object-fit: contain !important;
                                image-rendering: -webkit-optimize-contrast !important;
                                image-rendering: -moz-crisp-edges !important;
                                image-rendering: crisp-edges !important;
                                image-rendering: pixelated !important;
                            `;
                            console.log('iOS/Desktop: Using image for QR display');
                        }
                    }
                    
                    // Add click handler for small-screen fullscreen overlay (no hint text)
                    if (viewportWidth < 768) {
                        qrWrapper.style.cursor = 'pointer';
                        let fullscreenOverlay = null;

                        qrWrapper.addEventListener('click', () => {
                            if (fullscreenOverlay) {
                                // Exit fullscreen mode
                                if (fullscreenOverlay.parentNode) {
                                    fullscreenOverlay.parentNode.removeChild(fullscreenOverlay);
                                }
                                fullscreenOverlay = null;
                                document.documentElement.style.overflow = '';
                                document.body.style.overflow = '';
                                // Re-enable viewport scrolling
                                const viewport = document.querySelector('meta[name="viewport"]');
                                if (viewport && viewport._originalContent) {
                                    viewport.setAttribute('content', viewport._originalContent);
                                }
                            } else {
                                // Detect platform
                                const isAndroid = /Android/i.test(navigator.userAgent);
                                
                                // Get QR source based on platform
                                let qrSourceElement, qrSourceData;
                                
                                if (isAndroid) {
                                    // Android: Use canvas
                                    qrSourceElement = qrWrapper.querySelector('canvas');
                                    if (qrSourceElement) {
                                        qrSourceData = qrSourceElement.toDataURL('image/png');
                                        console.log('Android: Converting canvas to data URL for fullscreen');
                                    }
                                } else {
                                    // iOS/Desktop: Use image
                                    qrSourceElement = qrWrapper.querySelector('img');
                                    if (qrSourceElement) {
                                        qrSourceData = qrSourceElement.src;
                                    }
                                }
                                
                                if (!qrSourceElement || !qrSourceData) {
                                    console.error('No QR code source found');
                                    return;
                                }
                                
                                // Lock viewport to prevent iOS zoom/scroll issues
                                const viewport = document.querySelector('meta[name="viewport"]');
                                if (viewport) {
                                    viewport._originalContent = viewport.getAttribute('content');
                                    viewport.setAttribute('content', 'width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no');
                                }
                                
                                // Create fullscreen overlay that covers everything including iOS chrome
                                fullscreenOverlay = document.createElement('div');
                                fullscreenOverlay.style.cssText = `
                                    position: fixed;
                                    top: 0;
                                    left: 0;
                                    right: 0;
                                    bottom: 0;
                                    width: 100%;
                                    height: 100%;
                                    background: rgba(0, 0, 0, 0.95);
                                    z-index: 2147483647;
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    flex-direction: column;
                                    padding: 20px;
                                    box-sizing: border-box;
                                    -webkit-overflow-scrolling: touch;
                                    overflow: hidden;
                                `;
                                
                                // Create container for QR code
                                const fullscreenQRContainer = document.createElement('div');
                                const containerSize = Math.min(window.innerWidth, window.innerHeight) * 0.85;
                                fullscreenQRContainer.style.cssText = `
                                    width: ${containerSize}px;
                                    height: ${containerSize}px;
                                    background: #ffffff;
                                    padding: 15px;
                                    box-sizing: border-box;
                                    border-radius: 12px;
                                    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    position: relative;
                                `;
                                
                                // Create fullscreen QR image from source data
                                const fullscreenQR = document.createElement('img');
                                fullscreenQR.src = qrSourceData;
                                
                                // Style the fullscreen QR code
                                fullscreenQR.style.cssText = `
                                    width: 100% !important;
                                    height: 100% !important;
                                    max-width: 100% !important;
                                    max-height: 100% !important;
                                    object-fit: contain !important;
                                    display: block !important;
                                    margin: 0 !important;
                                    padding: 0 !important;
                                    border: none !important;
                                    image-rendering: -webkit-optimize-contrast !important;
                                    image-rendering: -moz-crisp-edges !important;
                                    image-rendering: crisp-edges !important;
                                    image-rendering: pixelated !important;
                                `;
                                
                                fullscreenQRContainer.appendChild(fullscreenQR);
                                
                                // Add close instruction
                                const closeHint = document.createElement('div');
                                closeHint.style.cssText = `
                                    color: #ffffff;
                                    font-size: 18px;
                                    margin-top: 20px;
                                    text-align: center;
                                    text-shadow: 0 2px 4px rgba(0,0,0,0.5);
                                    flex-shrink: 0;
                                `;
                                closeHint.innerHTML = '<i class="fas fa-times-circle me-2"></i>Tap anywhere to close';
                                
                                fullscreenOverlay.appendChild(fullscreenQRContainer);
                                fullscreenOverlay.appendChild(closeHint);
                                
                                // Append to documentElement for true fullscreen on iOS
                                document.documentElement.appendChild(fullscreenOverlay);
                                document.documentElement.style.overflow = 'hidden';
                                document.body.style.overflow = 'hidden';
                                
                                // Click anywhere to close
                                fullscreenOverlay.addEventListener('click', (e) => {
                                    e.preventDefault();
                                    e.stopPropagation();
                                    if (fullscreenOverlay.parentNode) {
                                        fullscreenOverlay.parentNode.removeChild(fullscreenOverlay);
                                    }
                                    fullscreenOverlay = null;
                                    document.documentElement.style.overflow = '';
                                    document.body.style.overflow = '';
                                    // Restore viewport
                                    const viewport = document.querySelector('meta[name="viewport"]');
                                    if (viewport && viewport._originalContent) {
                                        viewport.setAttribute('content', viewport._originalContent);
                                    }
                                    // no hint to update here - we removed the small-screen hint element
                                });
                                
                                // no inline hint text - overlay has its own close hint
                            }
                        });
                    }
                }, 100);
                
            } catch (qrError) {
                console.error('Error creating QR code:', qrError);
                
                // Fallback with lower error correction
                try {
                    qrcodeContainer.innerHTML = '';
                    
                    const qrWrapper = document.createElement('div');
                    qrWrapper.style.cssText = `
                        width: 100%;
                        max-width: ${qrSize}px;
                        aspect-ratio: 1;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        background: #ffffff;
                        padding: 16px;
                        box-sizing: border-box;
                        border-radius: 12px;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                    `;
                    qrcodeContainer.appendChild(qrWrapper);
                    
                    new QRCode(qrWrapper, {
                        text: jsonString,
                        width: qrSize - 32,
                        height: qrSize - 32,
                        colorDark: "#000000",
                        colorLight: "#ffffff",
                        correctLevel: QRCode.CorrectLevel.L
                    });
                    
                    setTimeout(() => {
                        const qrCanvas = qrWrapper.querySelector('canvas');
                        const qrImg = qrWrapper.querySelector('img');
                        
                        // Remove canvas to prevent duplicate display
                        if (qrCanvas && qrCanvas.parentNode) {
                            qrCanvas.parentNode.removeChild(qrCanvas);
                        }
                        
                        // Style the image
                        if (qrImg) {
                            qrImg.style.cssText = `
                                width: 100% !important;
                                height: 100% !important;
                                max-width: ${qrSize - 32}px !important;
                                max-height: ${qrSize - 32}px !important;
                                display: block !important;
                                margin: 0 auto !important;
                                object-fit: contain !important;
                                image-rendering: -webkit-optimize-contrast !important;
                                image-rendering: crisp-edges !important;
                            `;
                        }
                    }, 100);
                    
                } catch (fallbackError) {
                    console.error('Error with fallback QR code generation:', fallbackError);
                    qrcodeContainer.innerHTML = `
                        <div class="alert alert-danger">
                            <i class="fas fa-exclamation-triangle me-2"></i>
                            Error: Data too large for QR code. Please submit directly.
                        </div>
                    `;
                    showToast('Data too large for QR code', 'danger');
                    return;
                }
            }
            
            // Show download button
            const downloadContainer = document.getElementById('qrDownloadContainer');
            if (downloadContainer) {
                downloadContainer.classList.remove('d-none');
                
                const downloadButton = downloadContainer.querySelector('button');
                if (downloadButton) {
                    const newButton = downloadButton.cloneNode(true);
                    downloadButton.parentNode.replaceChild(newButton, downloadButton);
                    
                    newButton.addEventListener('click', () => {
                        const qrWrapper = qrcodeContainer.querySelector('div');
                        const img = qrWrapper ? qrWrapper.querySelector('img') : null;
                        const canvas = qrWrapper ? qrWrapper.querySelector('canvas') : null;
                        
                        if (img) {
                            const link = document.createElement('a');
                            link.href = img.src;
                            link.download = `team_${formObject.team_id}_match_${formObject.match_id}_qr.png`;
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                        } else if (canvas) {
                            // Convert canvas to image for download
                            const link = document.createElement('a');
                            link.href = canvas.toDataURL('image/png');
                            link.download = `team_${formObject.team_id}_match_${formObject.match_id}_qr.png`;
                            document.body.appendChild(link);
                            link.click();
                            document.body.removeChild(link);
                        }
                    });
                }
            }
            
            // Show success message
            showToast('QR Code generated successfully', 'success');
            
        } catch (error) {
            console.error('Error generating QR Code:', error);
            qrcodeContainer.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    Error generating QR Code: ${error.message}
                </div>
            `;
            showToast('Failed to generate QR Code', 'danger');
        }
    }, 300);
}

/**
 * Initialize match period tabs with smooth transitions
 */
function initializeMatchPeriodTabs() {
    const tabs = document.querySelectorAll('.match-period-tab');
    const sections = document.querySelectorAll('.match-period-section');

    if (!tabs.length || !sections.length) return;

    // Ensure sections have a CSS transition for opacity
    sections.forEach(section => {
        section.style.transition = 'opacity 0.25s ease-in-out';
    });

    const activateTab = (tabEl, targetId) => {
        // Update tab visual and semantic state
        tabs.forEach(t => {
            t.classList.toggle('active', t === tabEl);
            t.classList.remove('auto-tab', 'teleop-tab', 'endgame-tab', 'postmatch-tab');
            if (t === tabEl) {
                if (targetId.includes('auto')) t.classList.add('auto-tab');
                else if (targetId.includes('teleop')) t.classList.add('teleop-tab');
                else if (targetId.includes('endgame')) t.classList.add('endgame-tab');
                else if (targetId.includes('post')) t.classList.add('postmatch-tab');
            }
        });

        // Show target immediately and hide others with a fade
        sections.forEach(section => {
            if (section.id === targetId) {
                section.classList.remove('d-none');
                // Force a reflow to ensure transition runs
                section.style.opacity = '0';
                requestAnimationFrame(() => { section.style.opacity = '1'; });

                // Scroll into view if needed
                const rect = section.getBoundingClientRect();
                if (rect.top < 0 || rect.bottom > window.innerHeight) {
                    section.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            } else {
                // Fade out then add d-none when transition completes
                section.style.opacity = '0';
                const onTransitionEnd = (e) => {
                    if (e.propertyName === 'opacity' && section.style.opacity === '0') {
                        section.classList.add('d-none');
                        section.removeEventListener('transitionend', onTransitionEnd);
                    }
                };
                section.addEventListener('transitionend', onTransitionEnd);
            }
        });
    };

    // Initialize: show the active tab's section or default to the first tab
    const initialActive = document.querySelector('.match-period-tab.active') || tabs[0];
    if (initialActive) {
        const targetId = initialActive.getAttribute('data-target');
        // Hide all sections first
        sections.forEach(section => {
            if (section.id !== targetId) {
                section.classList.add('d-none');
                section.style.opacity = '0';
            } else {
                section.classList.remove('d-none');
                section.style.opacity = '1';
            }
        });
        activateTab(initialActive, targetId);
    }

    // Add click and keyboard handlers to tabs
    tabs.forEach(tab => {
        // Make tabs keyboard-accessible if they aren't already
        tab.setAttribute('role', 'button');
        tab.setAttribute('tabindex', '0');

        tab.addEventListener('click', (e) => {
            const targetId = tab.getAttribute('data-target');
            if (!targetId) return;
            activateTab(tab, targetId);
        });

        tab.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                const targetId = tab.getAttribute('data-target');
                if (!targetId) return;
                activateTab(tab, targetId);
            }
        });
    });
}

/**
 * Initialize Auto Period Timer functionality
 * Tracks first auto entry and shows reminder after auto period duration
 */
function initializeAutoPeriodTimer() {
    const timerToggle = document.getElementById('auto_period_timer_enabled');
    const reminderBanner = document.getElementById('auto-period-reminder-banner');
    const autoSection = document.getElementById('auto-section');
    const teleopTab = document.querySelector('.match-period-tab[data-target="teleop-section"]');
    
    if (!timerToggle || !reminderBanner || !autoSection) return;
    
    // Load saved preference from localStorage
    const savedPreference = localStorage.getItem('auto_period_timer_enabled');
    if (savedPreference === 'true') {
        timerToggle.checked = true;
    }
    
    // Save preference when toggle changes
    timerToggle.addEventListener('change', function() {
        localStorage.setItem('auto_period_timer_enabled', this.checked);
        if (!this.checked) {
            // If disabled, hide banner and reset timer state
            hideAutoPeriodReminder();
            window.autoPeriodTimerState = null;
        }
    });
    
    // Get auto period duration from data attribute (in seconds)
    const autoDurationSeconds = parseInt(autoSection.getAttribute('data-auto-duration')) || 15;
    const autoDurationMs = autoDurationSeconds * 1000;
    
    console.log(`Auto period timer initialized: ${autoDurationSeconds} seconds (${autoDurationMs}ms)`);
    
    // State object to track timer
    window.autoPeriodTimerState = {
        timerStarted: false,
        timerCompleted: false,
        reminderShown: false,
        autoPeriodDuration: autoDurationMs
    };
    
    /**
     * Start the auto period timer when first scoring entry is made
     */
    function startAutoPeriodTimer() {
        if (!timerToggle.checked) return;
        if (window.autoPeriodTimerState.timerStarted) return;
        
        const durationMs = window.autoPeriodTimerState.autoPeriodDuration;
        console.log(`Auto period timer started - will fire in ${durationMs}ms (${durationMs/1000} seconds)`);
        window.autoPeriodTimerState.timerStarted = true;
        
        // Set timeout for auto period duration
        setTimeout(() => {
            console.log('Auto period timer completed - showing reminder');
            window.autoPeriodTimerState.timerCompleted = true;
            
            // Only show reminder if still on auto tab
            const autoTab = document.querySelector('.match-period-tab[data-target="auto-section"]');
            const teleopSection = document.getElementById('teleop-section');
            
            if (autoTab && autoTab.classList.contains('active') && 
                teleopSection && teleopSection.classList.contains('d-none')) {
                showAutoPeriodReminder();
            }
        }, window.autoPeriodTimerState.autoPeriodDuration);
    }
    
    /**
     * Show the auto period reminder banner
     */
    function showAutoPeriodReminder() {
        if (window.autoPeriodTimerState.reminderShown) return;
        if (!timerToggle.checked) return;
        
        console.log('Showing auto period reminder');
        window.autoPeriodTimerState.reminderShown = true;
        // Position banner so it sits below topbar and does not cover the sidebar
        function positionBanner() {
            try {
                const topbar = document.querySelector('.topbar');
                const sidebar = document.getElementById('appSidebar');
                const isSidebarVisible = sidebar && window.getComputedStyle(sidebar).display !== 'none';

                // Determine top offset (height of topbar) and left offset (width of sidebar when visible)
                const topOffset = topbar ? topbar.offsetHeight : 0;
                let leftOffset = 0;

                if (isSidebarVisible) {
                    // use bounding rect to account for collapsed or fixed sidebars
                    const rect = sidebar.getBoundingClientRect();
                    leftOffset = rect.width || 0;
                }

                // On small screens don't offset by sidebar
                if (window.innerWidth < 900) {
                    leftOffset = 0;
                }

                // Apply styles to banner
                reminderBanner.style.top = topOffset + 'px';
                reminderBanner.style.left = leftOffset + 'px';
                reminderBanner.style.right = '0';
                reminderBanner.style.width = `calc(100% - ${leftOffset}px)`;
                reminderBanner.style.margin = '0';
                reminderBanner.style.borderRadius = '0';
            } catch (e) {
                console.warn('Could not position reminder banner', e);
            }
        }

        // Initially position and then show
        positionBanner();

        reminderBanner.classList.remove('d-none');
        reminderBanner.classList.add('show');

        // Add pulsing animation
        reminderBanner.style.animation = 'pulse 2s ease-in-out 3';

        // Reposition on window resize to adapt to responsive layout
        window.addEventListener('resize', positionBanner);

        // Reposition when sidebar toggles (if a toggle exists)
        const sidebarToggle = document.getElementById('sidebarToggle');
        if (sidebarToggle) {
            sidebarToggle.addEventListener('click', function() {
                // Slight delay while sidebar animates/collapses
                setTimeout(positionBanner, 260);
            });
        }
        
        // Play a subtle beep if browser supports it (optional)
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();
            
            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);
            
            oscillator.frequency.value = 800;
            oscillator.type = 'sine';
            gainNode.gain.value = 0.1;
            
            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.2);
        } catch (e) {
            // Audio not supported or blocked
            console.log('Audio notification not available');
        }
    }
    
    /**
     * Hide the auto period reminder banner
     */
    function hideAutoPeriodReminder() {
        reminderBanner.classList.remove('show');
        reminderBanner.classList.add('d-none');
    }
    
    // Expose hide function globally so tab switching can use it
    window.hideAutoPeriodReminder = hideAutoPeriodReminder;
    
    /**
     * Monitor auto period inputs for first entry
     */
    function monitorAutoInputs() {
        if (!autoSection) return;
        
        // Get all auto period inputs that add points (counters and checkboxes with points)
        const autoInputs = autoSection.querySelectorAll('input[type="number"], input[type="checkbox"]');
        
        autoInputs.forEach(input => {
            // For counters, check if value increases from 0
            if (input.type === 'number') {
                let lastValue = parseInt(input.value) || 0;
                
                input.addEventListener('change', function() {
                    const currentValue = parseInt(this.value) || 0;
                    
                    // Start timer if value increased from 0 or changed to positive
                    if (currentValue > 0 && lastValue === 0) {
                        startAutoPeriodTimer();
                    }
                    lastValue = currentValue;
                });
                
                // Also monitor increment button clicks
                const container = input.closest('.counter-container');
                if (container) {
                    const incrementBtn = container.querySelector('.btn-increment');
                    if (incrementBtn) {
                        incrementBtn.addEventListener('click', function() {
                            const currentValue = parseInt(input.value) || 0;
                            if (currentValue === 0) {
                                // Will be 1 after increment
                                setTimeout(() => startAutoPeriodTimer(), 50);
                            }
                        });
                    }
                }
            }
            // For checkboxes with points, check if they get checked
            else if (input.type === 'checkbox') {
                // Check if this checkbox adds points by looking at parent card
                const cardBody = input.closest('.card-body');
                if (cardBody) {
                    input.addEventListener('change', function() {
                        if (this.checked) {
                            startAutoPeriodTimer();
                        }
                    });
                }
            }
        });
    }
    
    // Initialize input monitoring
    monitorAutoInputs();
    
    // Hide reminder when switching to teleop tab
    if (teleopTab) {
        teleopTab.addEventListener('click', function() {
            hideAutoPeriodReminder();
        });
    }
    
    // Also hide when teleop tab is activated via keyboard
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            const focused = document.activeElement;
            if (focused && focused.classList.contains('teleop-tab')) {
                hideAutoPeriodReminder();
            }
        }
    });
}

/**
 * Improved form validation with better feedback
 */
function validateForms() {
    const forms = document.querySelectorAll('.needs-validation');
    
    Array.from(forms).forEach(form => {
        // Add custom validation styling as user types
        const inputs = form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            input.addEventListener('input', function () {
                // Clear previous error messages
                const feedbackElement = this.nextElementSibling?.classList.contains('invalid-feedback') 
                    ? this.nextElementSibling
                    : null;
                    
                if (feedbackElement) {
                    feedbackElement.textContent = '';
                }
                
                // Check validity as user types
                if (this.checkValidity()) {
                    this.classList.remove('is-invalid');
                    this.classList.add('is-valid');
                } else {
                    this.classList.remove('is-valid');
                    // Only add invalid class if user has started typing
                    if (this.value) {
                        this.classList.add('is-invalid');
                        
                        // Set custom error message based on validation type
                        if (feedbackElement) {
                            if (this.validity.valueMissing) {
                                feedbackElement.textContent = 'This field is required';
                            } else if (this.validity.typeMismatch) {
                                feedbackElement.textContent = `Please enter a valid ${this.type}`;
                            } else if (this.validity.rangeUnderflow) {
                                feedbackElement.textContent = `Value must be at least ${this.min}`;
                            } else if (this.validity.rangeOverflow) {
                                feedbackElement.textContent = `Value must be at most ${this.max}`;
                            }
                        }
                    }
                }
            });
        });

        // Handle form submission
        form.addEventListener('submit', event => {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
                
                // Find the first invalid element and focus it
                const invalidElement = form.querySelector(':invalid');
                if (invalidElement) {
                    invalidElement.focus();
                    
                    // Scroll to the invalid element if needed
                    invalidElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    
                    // Show toast message with error summary
                    const invalidCount = form.querySelectorAll(':invalid').length;
                    showToast(`Please fix ${invalidCount} form error${invalidCount !== 1 ? 's' : ''}`, 'warning');
                }
            } else {
                // Show saving indicator for better feedback
                const submitButton = form.querySelector('[type="submit"]');
                if (submitButton && !submitButton.classList.contains('no-loading-state')) {
                    const originalText = submitButton.innerHTML;
                    submitButton.disabled = true;
                    submitButton.innerHTML = `
                        <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
                        Saving...
                    `;
                    
                    // Reset button after a delay
                    setTimeout(() => {
                        submitButton.disabled = false;
                        submitButton.innerHTML = originalText;
                    }, 3000);
                }
            }
            
            form.classList.add('was-validated');
        }, false);
    });
}

/**
 * Enable "Start Scouting" button when team and match are selected
 */
function enableStartScoutingButton() {
    // Get button and necessary form elements
    const startButton = document.getElementById('start-scouting');
    if (!startButton) return;
    
    const teamSelector = document.getElementById('team-selector');
    const matchSelector = document.getElementById('match-selector');
    
    if (!teamSelector || !matchSelector) return;
    
    // Function to update button state
    const updateButtonState = () => {
        const teamSelected = teamSelector.value !== '';
        const matchSelected = matchSelector.value !== '';
        
        if (teamSelected && matchSelected) {
            startButton.disabled = false;
            startButton.classList.add('btn-pulse');
            setTimeout(() => {
                startButton.classList.remove('btn-pulse');
            }, 500);
        } else {
            startButton.disabled = true;
        }
        
        // Update visual indicators
        teamSelector.classList.toggle('is-valid', teamSelected);
        matchSelector.classList.toggle('is-valid', matchSelected);
        
        // Show focus indicator on the next field that needs completion
        if (!teamSelected) {
            teamSelector.classList.add('needs-attention');
            matchSelector.classList.remove('needs-attention');
        } else if (!matchSelected) {
            teamSelector.classList.remove('needs-attention');
            matchSelector.classList.add('needs-attention');
        } else {
            teamSelector.classList.remove('needs-attention');
            matchSelector.classList.remove('needs-attention');
        }
    };
    
    // Add change event listeners
    teamSelector.addEventListener('change', updateButtonState);
    matchSelector.addEventListener('change', updateButtonState);
    
    // Initial state check
    updateButtonState();
}

/**
 * Calculate points based on formula from game config
 * @param {string} formula - Formula string from game config
 * @param {Object} data - Object containing the values to use in the formula
 * @returns {number} Calculated points
 */
function calculatePoints(formula, data) {
    if (!formula || !data) return 0;
    
    try {
        // If we have a formula that references period durations, ensure we have them
        if (formula.includes('duration_seconds') || formula.includes('scoring_frequency')) {
            // Get duration values from data-attributes if available
            const autoDuration = parseInt(document.querySelector('meta[name="auto_duration"]')?.getAttribute('content') || '15');
            const teleopDuration = parseInt(document.querySelector('meta[name="teleop_duration"]')?.getAttribute('content') || '120');
            const endgameDuration = parseInt(document.querySelector('meta[name="endgame_duration"]')?.getAttribute('content') || '30');
            
            // Add these to the data object for formula calculation
            data.auto_duration_seconds = autoDuration;
            data.teleop_duration_seconds = teleopDuration;
            data.endgame_duration_seconds = endgameDuration;
            data.total_match_duration = autoDuration + teleopDuration + endgameDuration;
        }
        
        // Handle special case for auto-generated formulas
        if (formula === 'auto_generated') {
            // For metrics that use dynamic point calculations
            if (data.metric_id === 'auto_points') {
                return calculatePeriodPoints('auto', data);
            } else if (data.metric_id === 'teleop_points') {
                return calculatePeriodPoints('teleop', data);
            } else if (data.metric_id === 'endgame_points') {
                return calculatePeriodPoints('endgame', data);
            } else if (data.metric_id === 'total_points') {
                return calculatePeriodPoints('auto', data) + 
                       calculatePeriodPoints('teleop', data) + 
                       calculatePeriodPoints('endgame', data);
            }
        }
        
        // Create a function that evaluates the formula with the data
        let evalFunction = new Function(...Object.keys(data), `return ${formula}`);
        return evalFunction(...Object.values(data));
    } catch (error) {
        console.error('Error calculating points:', error);
        return 0;
    }
}

/**
 * Calculate points for a specific period using the config point values
 * @param {string} period - The period to calculate points for ('auto', 'teleop', or 'endgame')
 * @param {Object} data - Form data object
 * @returns {number} - Total points for the period
 */
function calculatePeriodPoints(period, data) {
    let points = 0;
    
    console.log(`Calculating points for period: ${period}`, data);
    
    // Use the global GAME_CONFIG that was passed via the script tag in base.html
    if (!window.GAME_CONFIG) {
        console.error('Game configuration not found');
        return 0;
    }
    
    try {
        // Get scoring elements for the period
        const periodConfig = window.GAME_CONFIG[`${period}_period`];
        console.log(`Period config for ${period}:`, periodConfig);
        
        if (!periodConfig || !periodConfig.scoring_elements) return 0;
        
        // Calculate points for each scoring element
        periodConfig.scoring_elements.forEach(element => {
            const elementId = element.id;
            console.log(`Processing element ${elementId} (${element.type}):`, element);
            
            // Skip if element is not in the form data
            if (!(elementId in data)) {
                console.log(`Element ${elementId} not found in form data`);
                return;
            }
            
            const elementValue = data[elementId];
            console.log(`Element ${elementId} value:`, elementValue);
            
            // Handle different element types
            if (element.type === 'boolean' && element.points) {
                // Boolean elements
                if (data[elementId] === true) {
                    points += element.points;
                }
            } else if (element.type === 'counter' && element.points) {
                // Counter elements with direct points
                points += data[elementId] * element.points;
            } else if (element.type === 'select' && element.points) {
                // Select elements with points object
                const selectedValue = data[elementId];
                if (typeof element.points === 'object' && selectedValue in element.points) {
                    points += element.points[selectedValue];
                }
            } else if (element.type === 'multiple_choice' && element.options) {
                // Multiple choice elements with individual option points
                const selectedValue = data[elementId];
                console.log(`Multiple choice element ${elementId}:`, {
                    selectedValue: selectedValue,
                    options: element.options,
                    elementData: element
                });
                
                if (selectedValue !== undefined && selectedValue !== null && selectedValue !== "") {
                    // Find the option that matches the selected value
                    const selectedOption = element.options.find(option => {
                        if (typeof option === 'object' && option.name !== undefined) {
                            // Compare both as strings to handle type mismatches
                            return String(option.name) === String(selectedValue);
                        }
                        return String(option) === String(selectedValue);
                    });
                    
                    console.log(`Found selected option for ${elementId}:`, selectedOption);
                    
                    // Add points if option has points defined
                    if (selectedOption && typeof selectedOption === 'object' && selectedOption.points) {
                        const pointsToAdd = selectedOption.points;
                        points += pointsToAdd;
                        console.log(`Adding ${pointsToAdd} points for ${elementId}, total now: ${points}`);
                    } else {
                        console.log(`No points to add for ${elementId}, selectedOption:`, selectedOption);
                    }
                } else {
                    console.log(`No selected value for multiple choice ${elementId}`);
                }
            } else if (element.game_piece_id) {
                // Game piece elements without direct points
                for (const gamePiece of window.GAME_CONFIG.game_pieces || []) {
                    if (gamePiece.id === element.game_piece_id) {
                        if (element.bonus) {
                            points += data[elementId] * gamePiece.bonus_points;
                        } else if (period === 'auto') {
                            points += data[elementId] * gamePiece.auto_points;
                        } else if (period === 'teleop') {
                            points += data[elementId] * gamePiece.teleop_points;
                        }
                        break;
                    }
                }
            }
        });
        
        console.log(`Total points calculated for ${period}: ${points}`);
        return points;
    } catch (error) {
        console.error(`Error calculating ${period} points:`, error);
        return 0;
    }
}

/**
 * Initialize points calculation on the scouting form with enhanced UI feedback
 */
function initializePointsCalculation() {
    const scoutingForm = document.getElementById('scouting-form');
    
    if (!scoutingForm) return;
    
    // Get all inputs that might affect points
    const allInputs = scoutingForm.querySelectorAll('input, select');
    
    // Add change event listener for realtime updates
    allInputs.forEach(input => {
        input.addEventListener('change', () => {
            updatePointsCalculation();
            
            // Add visual feedback on change
            const pointsDisplays = document.querySelectorAll('.points-display');
            pointsDisplays.forEach(display => {
                display.classList.add('points-updating');
                setTimeout(() => {
                    display.classList.remove('points-updating');
                }, 500);
            });
        });
    });
    
    // Initial calculation
    updatePointsCalculation();
}

/**
 * Update points calculation when form inputs change
 */
function updatePointsCalculation() {
    const scoutingForm = document.getElementById('scouting-form');
    const pointsContainers = document.querySelectorAll('.points-display');
    
    if (!scoutingForm || !pointsContainers.length) return;
    
    // Get all form data
    const formData = new FormData(scoutingForm);
    const data = {};
    
    // Convert form data to an object
    for (const [key, value] of formData.entries()) {
        // Convert boolean values from "on" to true
        if (value === "on") {
            data[key] = true;
        } 
        // Convert numeric values
        else if (!isNaN(value)) {
            data[key] = Number(value);
        } 
        // Keep string values
        else {
            data[key] = value;
        }
    }
    
    // Set default boolean values to false if not in the form data
    document.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        if (!data.hasOwnProperty(checkbox.id)) {
            data[checkbox.id] = false;
        }
    });
    
    // Calculate points for each container that has a formula
    pointsContainers.forEach(container => {
        const formula = container.dataset.formula;
        const metricId = container.dataset.metricId;
        const pointsValue = container.querySelector('.points-value');
        
        if (formula && pointsValue) {
            // Add metric ID to data object if available
            if (metricId) {
                data.metric_id = metricId;
            }
            
            const points = calculatePoints(formula, data);
            pointsValue.textContent = points;
        }
    });
    
    // Calculate total points
    const totalPointsContainer = document.getElementById('total-points');
    if (totalPointsContainer) {
        const totalFormula = totalPointsContainer.dataset.formula;
        const metricId = totalPointsContainer.dataset.metricId;
        
        if (totalFormula) {
            // Add metric ID to data object if available
            if (metricId) {
                data.metric_id = metricId;
            }
            
            const totalPoints = calculatePoints(totalFormula, data);
            const totalPointsValue = totalPointsContainer.querySelector('.points-value');
            if (totalPointsValue) {
                totalPointsValue.textContent = totalPoints;
            }
        }
    }
}

/**
 * Initialize data tables with search, sort and pagination
 */
function initializeDataTables() {
    // Check if DataTables library is available
    if (typeof $.fn.DataTable === 'undefined') return;
    
    const tables = document.querySelectorAll('.data-table');
    
    tables.forEach(table => {
        // Initialize with custom options
        $(table).DataTable({
            responsive: true,
            language: {
                search: '<i class="fas fa-search"></i>',
                searchPlaceholder: 'Search...',
                lengthMenu: 'Show _MENU_ entries',
                info: 'Showing _START_ to _END_ of _TOTAL_ entries',
                paginate: {
                    first: '<i class="fas fa-angle-double-left"></i>',
                    previous: '<i class="fas fa-angle-left"></i>',
                    next: '<i class="fas fa-angle-right"></i>',
                    last: '<i class="fas fa-angle-double-right"></i>'
                }
            },
            dom: '<"row"<"col-md-6"l><"col-md-6"f>><"table-responsive"t><"row"<"col-md-6"i><"col-md-6"p>>',
            pageLength: 10,
            lengthMenu: [[5, 10, 25, 50, -1], [5, 10, 25, 50, 'All']]
        });
    });
}

/**
 * Set up proper modal behavior
 */
function setupModalBehavior() {
    const modals = document.querySelectorAll('.modal');
    
    modals.forEach(modal => {
        // Fix scrollbar jump when modal opens
        modal.addEventListener('show.bs.modal', function() {
            const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
            document.body.style.paddingRight = scrollbarWidth + 'px';
            document.body.style.overflow = 'hidden';
        });
        
        // Reset when modal closes
        modal.addEventListener('hidden.bs.modal', function() {
            document.body.style.paddingRight = '';
            document.body.style.overflow = '';
        });
        
        // Prevent modal from closing when clicking inside modal content
        const modalContent = modal.querySelector('.modal-content');
        if (modalContent) {
            modalContent.addEventListener('click', function(event) {
                event.stopPropagation();
            });
        }
        
        // Add escape key listener
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && modal.classList.contains('show')) {
                const bsModal = bootstrap.Modal.getInstance(modal);
                if (bsModal) bsModal.hide();
            }
        });
    });
}

/**
 * Setup global search functionality
 */
function setupSearch() {
    const globalSearchInput = document.getElementById('global-search');
    const searchResultsContainer = document.getElementById('search-results');
    
    if (!globalSearchInput || !searchResultsContainer) return;
    
    // Debounce function to avoid excessive requests
    let searchTimeout;
    
    globalSearchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const query = this.value.trim();
        
        if (query.length < 2) {
            searchResultsContainer.innerHTML = '';
            searchResultsContainer.classList.add('d-none');
            return;
        }
        
        // Set timeout for debounce
        searchTimeout = setTimeout(() => {
            // Show loading indicator
            searchResultsContainer.innerHTML = '<div class="text-center p-3"><div class="spinner-border spinner-border-sm" role="status"></div><div class="mt-2">Searching...</div></div>';
            searchResultsContainer.classList.remove('d-none');
            
            // Fetch search results
            fetchWithOfflineFallback(`/api/search?q=${encodeURIComponent(query)}`)
                .then(data => {
                    // Generate results HTML
                    if (data.results && data.results.length) {
                        // Format and display results
                        let resultsHtml = '<div class="list-group">';
                        data.results.forEach(result => {
                            resultsHtml += `
                                <a href="${result.url}" class="list-group-item list-group-item-action">
                                    <div class="d-flex w-100 justify-content-between">
                                        <h6 class="mb-1">${result.title}</h6>
                                        <small class="text-muted">${result.type}</small>
                                    </div>
                                    <p class="mb-1 small">${result.description || ''}</p>
                                </a>
                            `;
                        });
                        resultsHtml += '</div>';
                        searchResultsContainer.innerHTML = resultsHtml;
                    } else {
                        searchResultsContainer.innerHTML = '<div class="p-3 text-center">No results found</div>';
                    }
                })
                .catch(error => {
                    console.error('Search error:', error);
                    searchResultsContainer.innerHTML = '<div class="p-3 text-center text-danger">Error performing search</div>';
                });
        }, 300);
    });
    
    // Close search results when clicking outside
    document.addEventListener('click', function(event) {
        if (!searchResultsContainer.contains(event.target) && event.target !== globalSearchInput) {
            searchResultsContainer.classList.add('d-none');
        }
    });
    
    // Clear search on Escape key
    globalSearchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            this.value = '';
            searchResultsContainer.innerHTML = '';
            searchResultsContainer.classList.add('d-none');
        }
    });
}

/**
 * Setup loading behavior for buttons and forms
 */
function setupLoadingBehavior() {
    // Handle loading state for buttons with data-loading-text attribute
    document.querySelectorAll('[data-loading-text]').forEach(button => {
        button.addEventListener('click', function() {
            if (this.classList.contains('no-loading-state') || this.disabled) return;
            
            const loadingText = this.getAttribute('data-loading-text');
            const originalHtml = this.innerHTML;
            const originalWidth = this.offsetWidth;
            
            // Set minimum width to prevent button size change
            this.style.minWidth = originalWidth + 'px';
            
            // Save original HTML for restoration
            this.setAttribute('data-original-html', originalHtml);
            
            // Update button with loading state
            this.disabled = true;
            this.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>${loadingText || 'Loading...'}`;
            
            // Restore original state after action completes
            // This requires manually calling resetLoadingButton(buttonElement) from your AJAX handlers
        });
    });
    
    // Make this function globally available
    window.resetLoadingButton = function(button) {
        if (!button) return;
        
        const originalHtml = button.getAttribute('data-original-html');
        if (originalHtml) {
            button.innerHTML = originalHtml;
            button.disabled = false;
        }
    };
}

/**
 * Setup keyboard shortcuts for common actions
 */
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        // Only handle keyboard shortcuts when not in an input field
        if (e.target.matches('input, textarea, select')) return;
        
        // Alt+S - Go to Scouting page
        if (e.altKey && e.key === 's') {
            e.preventDefault();
            window.location.href = '/scouting';
        }
        
        // Alt+D - Go to Dashboard
        if (e.altKey && e.key === 'd') {
            e.preventDefault(); 
            window.location.href = '/';
        }
        
        // Alt+V - Go to Visualization
        if (e.altKey && e.key === 'v') {
            e.preventDefault();
            window.location.href = '/visualization';
        }
        
        // Alt+T - Go to Teams
        if (e.altKey && e.key === 't') {
            e.preventDefault();
            window.location.href = '/teams';
        }
        
        // Alt+M - Go to Matches
        if (e.altKey && e.key === 'm') {
            e.preventDefault();
            window.location.href = '/matches';
        }
        
        // Alt+C - Go to Configuration
        if (e.altKey && e.key === 'c') {
            e.preventDefault();
            window.location.href = '/config';
        }
        
        // ? - Show keyboard shortcuts help
        if (e.key === '?') {
            e.preventDefault();
            showKeyboardShortcutsHelp();
        }
    });
}

/**
 * Display keyboard shortcuts help modal
 */
function showKeyboardShortcutsHelp() {
    // Create modal if it doesn't exist yet
    let modal = document.getElementById('keyboard-shortcuts-modal');
    
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'keyboard-shortcuts-modal';
        modal.className = 'modal fade';
        modal.tabIndex = '-1';
        modal.setAttribute('aria-hidden', 'true');
        
        modal.innerHTML = `
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Keyboard Shortcuts</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <table class="table table-sm">
                            <thead>
                                <tr>
                                    <th>Shortcut</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>S</kbd></td>
                                    <td>Go to Scouting</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>D</kbd></td>
                                    <td>Go to Dashboard</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>V</kbd></td>
                                    <td>Go to Visualization</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>T</kbd></td>
                                    <td>Go to Teams</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>M</kbd></td>
                                    <td>Go to Matches</td>
                                </tr>
                                <tr>
                                    <td><kbd>Alt</kbd> + <kbd>C</kbd></td>
                                    <td>Go to Configuration</td>
                                </tr>
                                <tr>
                                    <td><kbd>?</kbd></td>
                                    <td>Show this help</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    }
    
    // Show the modal
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
}

/**
 * Render Plotly graphs from data attributes
 * Used in the visualization pages
 */
function renderPlotlyGraphs() {
    // Check if Plotly is available
    if (typeof Plotly === 'undefined') {
        console.error('Plotly is not loaded. Make sure to include Plotly.js before calling renderPlotlyGraphs()');
        return;
    }
    
    // Find all elements with plotly-graph class
    const graphElements = document.querySelectorAll('.plotly-graph');
    
    console.log(`Found ${graphElements.length} graph elements to render`);
    
    const renderPromises = [];
    graphElements.forEach(element => {
        // Get graph data from data attribute
        try {
            // Parse the JSON data from the data-graph attribute
            const graphJson = element.getAttribute('data-graph');
            if (!graphJson) {
                console.error('No graph data found for element:', element.id);
                element.innerHTML = `
                    <div class="alert alert-warning">
                        <i class="fas fa-exclamation-circle me-2"></i>
                        No graph data available.
                    </div>`;
                return;
            }
            
            console.log(`Rendering graph for ${element.id}, data length: ${graphJson.length}`);
            
            // Parse the JSON data - handle potential HTML unescaping
            let parsedData;
            try {
                parsedData = JSON.parse(graphJson);
            } catch (parseError) {
                console.error('JSON parse error, trying to fix escaped JSON:', parseError);
                // Sometimes the JSON gets HTML escaped when rendered in templates
                const unescapedJson = graphJson
                    .replace(/&quot;/g, '"')
                    .replace(/&#39;/g, "'")
                    .replace(/&lt;/g, '<')
                    .replace(/&gt;/g, '>');
                    
                try {
                    parsedData = JSON.parse(unescapedJson);
                } catch (secondError) {
                    console.error('Failed to parse JSON even after unescaping:', secondError);
                    // Add debugging information
                    console.debug('Raw JSON data:', graphJson);
                    throw new Error('Failed to parse graph data');
                }
            }
            
            // Check which format we're dealing with
            function applyClientThemeAndPlot(dataObj, layoutObj) {
                // Compute card background and text color to match UI
                try {
                    // Helpers: parse rgb/rgba/hex to {r,g,b,a}
                    function parseColor(s) {
                        if (!s) return null;
                        s = s.trim().toLowerCase();
                        if (s === 'transparent') return null;
                        const rgbMatch = s.match(/rgba?\(([^)]+)\)/);
                        if (rgbMatch) {
                            const parts = rgbMatch[1].split(',').map(p => p.trim());
                            const r = parseInt(parts[0]);
                            const g = parseInt(parts[1]);
                            const b = parseInt(parts[2]);
                            const a = parts[3] !== undefined ? parseFloat(parts[3]) : 1;
                            // Treat fully transparent colors as no background so we fall back
                            if (a === 0) return null;
                            return {r,g,b,a};
                        }
                        const hexMatch = s.match(/^#([0-9a-f]{6})$/i);
                        if (hexMatch) {
                            const hex = hexMatch[1];
                            const r = parseInt(hex.substr(0,2),16);
                            const g = parseInt(hex.substr(2,2),16);
                            const b = parseInt(hex.substr(4,2),16);
                            return {r,g,b,a:1};
                        }
                        return null;
                    }

                    function rgbaString(col, alpha) {
                        if (!col) return `rgba(128,128,128,${alpha})`;
                        return `rgba(${col.r}, ${col.g}, ${col.b}, ${alpha})`;
                    }

                    function luminance(col) {
                        if (!col) return 0;
                        const srgb = [col.r, col.g, col.b].map(v => v/255).map(c => {
                            return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4);
                        });
                        return 0.2126*srgb[0] + 0.7152*srgb[1] + 0.0722*srgb[2];
                    }

                    // Walk up ancestors to find first non-transparent background
                    function findEffectiveBackground(el) {
                        let cur = el;
                        while (cur) {
                            try {
                                const cs = getComputedStyle(cur);
                                const bg = cs.backgroundColor;
                                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return {css: bg, parsed: parseColor(bg)};
                            } catch (e) {
                                // ignore and continue
                            }
                            cur = cur.parentElement;
                        }
                        const bodyBg = getComputedStyle(document.body).backgroundColor;
                        return {css: bodyBg, parsed: parseColor(bodyBg)};
                    }

                    const cardFind = element.closest('.card') || element.parentElement || document.body;
                    const cardBgInfo = findEffectiveBackground(cardFind);
                    const bodyBgInfo = findEffectiveBackground(document.body);

                    // Decide intended theme: prefer an explicit body class if present
                    const intendedDark = document.body.classList.contains('dark-mode') || document.body.classList.contains('theme-dark');

                    // If card background luminance doesn't match intended theme, prefer body background
                    const cardLum = cardBgInfo.parsed ? luminance(cardBgInfo.parsed) : null;
                    const bodyLum = bodyBgInfo.parsed ? luminance(bodyBgInfo.parsed) : null;

                    let bgParsed = cardBgInfo.parsed || bodyBgInfo.parsed;
                    let bgCss = cardBgInfo.css || bodyBgInfo.css;

                    if (cardLum !== null && bodyLum !== null) {
                        const cardIsDark = cardLum < 0.5;
                        const bodyIsDark = bodyLum < 0.5;
                        // If card color contradicts the intended theme, choose body background instead
                        if (cardIsDark !== intendedDark && bodyIsDark === intendedDark) {
                            bgParsed = bodyBgInfo.parsed;
                            bgCss = bodyBgInfo.css;
                        }
                    }

                    const textColor = (cardFind && getComputedStyle(cardFind).color) || getComputedStyle(document.body).color || '#000';

                    // Invert the chosen background color per user's request
                    function invertParsedColor(p) {
                        if (!p) return null;
                        try {
                            const lum = luminance(p);
                            // Preserve pure white and pure black to avoid off-white/brown artifacts
                            if (lum >= 0.95) return {r:255,g:255,b:255,a: p.a !== undefined ? p.a : 1};
                            if (lum <= 0.05) return {r:0,g:0,b:0,a: p.a !== undefined ? p.a : 1};
                        } catch (e) {
                            // fall back
                        }
                        return { r: 255 - p.r, g: 255 - p.g, b: 255 - p.b, a: p.a };
                    }
                    function parsedToCss(p) {
                        if (!p) return 'rgba(255,255,255,1)';
                        return `rgba(${p.r}, ${p.g}, ${p.b}, ${p.a !== undefined ? p.a : 1})`;
                    }

                    const chosenParsed = bgParsed || bodyBgInfo.parsed || parseColor(bgCss);
                    // Use the chosen background color directly (do not invert) so charts match the surrounding UI
                    const chosenCss = parsedToCss(chosenParsed) || (bodyBgInfo.css === 'transparent' ? 'rgba(255,255,255,1)' : bodyBgInfo.css);

                    layoutObj = layoutObj || {};
                    layoutObj.template = null; // prevent plotly_dark from winning
                    layoutObj.plot_bgcolor = chosenCss;
                    layoutObj.paper_bgcolor = chosenCss;
                    layoutObj.font = layoutObj.font || {};
                    layoutObj.font.color = textColor;

                    const subtleGrid = rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.12);
                    const faintLine = rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.06);
                    layoutObj.xaxis = layoutObj.xaxis || {};
                    layoutObj.yaxis = layoutObj.yaxis || {};
                    layoutObj.xaxis.gridcolor = layoutObj.xaxis.gridcolor || subtleGrid;
                    layoutObj.yaxis.gridcolor = layoutObj.yaxis.gridcolor || subtleGrid;
                    layoutObj.xaxis.zerolinecolor = layoutObj.xaxis.zerolinecolor || faintLine;
                    layoutObj.yaxis.zerolinecolor = layoutObj.yaxis.zerolinecolor || faintLine;
                    layoutObj.xaxis.tickfont = layoutObj.xaxis.tickfont || {};
                    layoutObj.yaxis.tickfont = layoutObj.yaxis.tickfont || {};
                    layoutObj.xaxis.tickfont.color = layoutObj.xaxis.tickfont.color || textColor;
                    layoutObj.yaxis.tickfont.color = layoutObj.yaxis.tickfont.color || textColor;

                    if (layoutObj.legend) {
                        layoutObj.legend.font = layoutObj.legend.font || {};
                        layoutObj.legend.font.color = layoutObj.legend.font.color || textColor;
                    }
                    if (layoutObj.annotations) {
                        layoutObj.annotations.forEach(function(a){ if (!a.font) a.font = {}; a.font.color = a.font.color || textColor; });
                    }
                    if (layoutObj.polar) {
                        layoutObj.polar.angularaxis = layoutObj.polar.angularaxis || {};
                        layoutObj.polar.radialaxis = layoutObj.polar.radialaxis || {};
                        layoutObj.polar.angularaxis.tickfont = layoutObj.polar.angularaxis.tickfont || {};
                        layoutObj.polar.radialaxis.tickfont = layoutObj.polar.radialaxis.tickfont || {};
                        layoutObj.polar.angularaxis.tickfont.color = layoutObj.polar.angularaxis.tickfont.color || textColor;
                        layoutObj.polar.radialaxis.tickfont.color = layoutObj.polar.radialaxis.tickfont.color || textColor;
                        layoutObj.polar.radialaxis.gridcolor = layoutObj.polar.radialaxis.gridcolor || rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.12);
                    }

                    // Plot then relayout to be sure templates are overridden
                    return Promise.resolve(Plotly.newPlot(element.id, dataObj, layoutObj, {responsive: true, displayModeBar: true, displaylogo: false}))
                        .then(function(){
                            const relayout = {
                                'template': null,
                                'plot_bgcolor': layoutObj.plot_bgcolor,
                                'paper_bgcolor': layoutObj.paper_bgcolor,
                                'font.color': (layoutObj.font && layoutObj.font.color) || textColor,
                                'legend.font.color': (layoutObj.legend && layoutObj.legend.font && layoutObj.legend.font.color) || textColor,
                                'xaxis.tickfont.color': (layoutObj.xaxis && layoutObj.xaxis.tickfont && layoutObj.xaxis.tickfont.color) || textColor,
                                'yaxis.tickfont.color': (layoutObj.yaxis && layoutObj.yaxis.tickfont && layoutObj.yaxis.tickfont.color) || textColor,
                                'xaxis.gridcolor': (layoutObj.xaxis && layoutObj.xaxis.gridcolor) || subtleGrid,
                                'yaxis.gridcolor': (layoutObj.yaxis && layoutObj.yaxis.gridcolor) || subtleGrid,
                                'xaxis.zerolinecolor': (layoutObj.xaxis && layoutObj.xaxis.zerolinecolor) || faintLine,
                                'yaxis.zerolinecolor': (layoutObj.yaxis && layoutObj.yaxis.zerolinecolor) || faintLine
                            };
                            if (layoutObj.polar) {
                                relayout['polar.radialaxis.gridcolor'] = layoutObj.polar.radialaxis.gridcolor || rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.12);
                                relayout['polar.angularaxis.tickfont.color'] = layoutObj.polar.angularaxis.tickfont.color || textColor;
                                relayout['polar.radialaxis.tickfont.color'] = layoutObj.polar.radialaxis.tickfont.color || textColor;
                            }
                            return Plotly.relayout(element.id, relayout).catch(()=>{});
                        }).catch(()=>{});
                } catch (e) {
                    console.warn('Failed to compute client theme for Plotly element', e);
                    // Fallback to plotting without client theme
                    return Promise.resolve(Plotly.newPlot(element.id, dataObj, layoutObj || {}, {responsive: true, displayModeBar: true, displaylogo: false}));
                }
            }

            if (parsedData.data && parsedData.layout) {
                // Our custom format with data and layout properties
                console.log('Using custom format with data and layout properties');
                renderPromises.push(applyClientThemeAndPlot(parsedData.data, parsedData.layout));
            } else {
                // Using plotly.io.to_json format
                console.log('Using plotly.io.to_json format');
                // parsedData in this case is an array or figure object — pass as data
                if (parsedData.data && parsedData.layout) {
                    renderPromises.push(applyClientThemeAndPlot(parsedData.data, parsedData.layout));
                } else if (parsedData.data) {
                    renderPromises.push(applyClientThemeAndPlot(parsedData.data, parsedData.layout || {}));
                } else {
                    // It's likely a figure encoded by plotly; try to plot directly and apply layout after
                    const maybeFig = parsedData;
                    if (maybeFig.data && maybeFig.layout) {
                        renderPromises.push(applyClientThemeAndPlot(maybeFig.data, maybeFig.layout));
                    } else {
                        // Fallback: try plotting the parsedData directly
                        renderPromises.push(applyClientThemeAndPlot(parsedData, {}));
                    }
                }
            }
            
            console.log(`Successfully rendered graph for ${element.id}`);
        } catch (error) {
            console.error('Error rendering Plotly graph for element', element.id, ':', error);
            
            // Create a more informative error indicator in the graph container
            element.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-circle me-2"></i>
                    Error loading graph: ${error.message}
                </div>`;
            
            // Add a debug button that shows the data when clicked
            const debugBtn = document.createElement('button');
            debugBtn.className = 'btn btn-sm btn-outline-danger mt-2';
            debugBtn.textContent = 'Debug Info';
            debugBtn.onclick = () => {
                console.log(`Debug data for ${element.id}:`, element.getAttribute('data-graph'));
                alert('Debug info logged to console. Press F12 to view.');
            };
            element.querySelector('.alert').appendChild(debugBtn);
        }
    });

    // When all graph rendering promises are complete, show share buttons for graphs
    Promise.all(renderPromises).then(() => {
        try {
            if (graphElements && graphElements.length > 0) {
                if (typeof window.showShareReadyButtons === 'function') window.showShareReadyButtons('graphs');
            }
        } catch (e) { console.warn('Error while showing share buttons after graphs render', e); }
    }).catch(err => { console.warn('Some graphs failed to render', err); });
}

/**
 * Re-apply client theme values to all already-rendered Plotly charts.
 * This is called when the page theme (body classes) changes so charts
 * update their background, grid and text colors to match the surrounding UI.
 */
window.rethemePlotlyCharts = function() {
    if (typeof Plotly === 'undefined') return;
    // Reuse parsing and luminance helpers similar to applyClientThemeAndPlot
    function parseColor(s) {
        if (!s) return null;
        s = s.trim().toLowerCase();
        if (s === 'transparent') return null;
        const rgbMatch = s.match(/rgba?\(([^)]+)\)/);
        if (rgbMatch) {
            const parts = rgbMatch[1].split(',').map(p => p.trim());
            const r = parseInt(parts[0]);
            const g = parseInt(parts[1]);
            const b = parseInt(parts[2]);
            const a = parts[3] !== undefined ? parseFloat(parts[3]) : 1;
            if (a === 0) return null;
            return {r,g,b,a};
        }
        const hexMatch = s.match(/^#([0-9a-f]{6})$/i);
        if (hexMatch) {
            const hex = hexMatch[1];
            const r = parseInt(hex.substr(0,2),16);
            const g = parseInt(hex.substr(2,2),16);
            const b = parseInt(hex.substr(4,2),16);
            return {r,g,b,a:1};
        }
        return null;
    }

    function rgbaString(col, alpha) {
        if (!col) return `rgba(128,128,128,${alpha})`;
        return `rgba(${col.r}, ${col.g}, ${col.b}, ${alpha})`;
    }

    function luminance(col) {
        if (!col) return 0;
        const srgb = [col.r, col.g, col.b].map(v => v/255).map(c => {
            return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4);
        });
        return 0.2126*srgb[0] + 0.7152*srgb[1] + 0.0722*srgb[2];
    }

    function findEffectiveBackground(el) {
        let cur = el;
        while (cur) {
            try {
                const cs = getComputedStyle(cur);
                const bg = cs.backgroundColor;
                if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return {css: bg, parsed: parseColor(bg)};
            } catch (e) {}
            cur = cur.parentElement;
        }
        const bodyBg = getComputedStyle(document.body).backgroundColor;
        return {css: bodyBg, parsed: parseColor(bodyBg)};
    }

    document.querySelectorAll('.plotly-graph').forEach(element => {
        try {
            if (!element.id || !element._fullLayout) return;

            const cardEl = element.closest('.card') || element.parentElement || document.body;
            const cardBgInfo = findEffectiveBackground(cardEl);
            const bodyBgInfo = findEffectiveBackground(document.body);
            const intendedDark = document.body.classList.contains('dark-mode') || document.body.classList.contains('theme-dark');

            const cardLum = cardBgInfo.parsed ? luminance(cardBgInfo.parsed) : null;
            const bodyLum = bodyBgInfo.parsed ? luminance(bodyBgInfo.parsed) : null;

            let bgParsed = cardBgInfo.parsed || bodyBgInfo.parsed;
            let bgCss = cardBgInfo.css || bodyBgInfo.css;
            function invertParsedColor(p) {
                if (!p) return null;
                try {
                    const lum = luminance(p);
                    if (lum >= 0.95) return {r:255,g:255,b:255,a: p.a !== undefined ? p.a : 1};
                    if (lum <= 0.05) return {r:0,g:0,b:0,a: p.a !== undefined ? p.a : 1};
                } catch (e) {}
                return { r: 255 - p.r, g: 255 - p.g, b: 255 - p.b, a: p.a };
            }
            function parsedToCss(p) { if (!p) return 'rgba(255,255,255,1)'; return `rgba(${p.r}, ${p.g}, ${p.b}, ${p.a !== undefined ? p.a : 1})`; }
            const chosenParsed = bgParsed || bodyBgInfo.parsed || parseColor(bgCss);
            // Use the chosen background directly to match card/body theme (don't invert)
            const chosenCss = parsedToCss(chosenParsed) || (bodyBgInfo.css === 'transparent' ? 'rgba(255,255,255,1)' : bodyBgInfo.css);
            bgParsed = chosenParsed; bgCss = chosenCss;
            if (cardLum !== null && bodyLum !== null) {
                const cardIsDark = cardLum < 0.5;
                const bodyIsDark = bodyLum < 0.5;
                if (cardIsDark !== intendedDark && bodyIsDark === intendedDark) {
                    bgParsed = bodyBgInfo.parsed;
                    bgCss = bodyBgInfo.css;
                }
            }

            const textColor = (cardEl && getComputedStyle(cardEl).color) || getComputedStyle(document.body).color || '#000';

            const relayout = {
                'template': null,
                'plot_bgcolor': bgCss,
                'paper_bgcolor': bgCss,
                'font.color': textColor,
                'legend.font.color': textColor,
                'xaxis.gridcolor': rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.12),
                'yaxis.gridcolor': rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.12),
                'xaxis.zerolinecolor': rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.06),
                'yaxis.zerolinecolor': rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.06),
                'xaxis.tickfont.color': textColor,
                'yaxis.tickfont.color': textColor
            };

            if (element._fullLayout && element._fullLayout.polar) {
                relayout['polar.radialaxis.gridcolor'] = rgbaString(parseColor(textColor) || {r:128,g:128,b:128}, 0.12);
                relayout['polar.angularaxis.tickfont.color'] = textColor;
                relayout['polar.radialaxis.tickfont.color'] = textColor;
            }

            Plotly.relayout(element.id, relayout).catch(()=>{});
        } catch (e) {
            console.warn('Failed to retheme Plotly element', element.id, e);
        }
    });
};

/**
 * Setup import and export functionality
 * Handles file uploads, Excel imports/exports, and QR code scanning
 */
function setupImportExport() {
    // File upload form handling
    const fileInputs = document.querySelectorAll('.custom-file-input');
    fileInputs.forEach(input => {
        input.addEventListener('change', function() {
            // Update the file name display
            const fileName = this.files[0]?.name || 'Choose file...';
            const fileLabel = this.nextElementSibling;
            if (fileLabel) {
                fileLabel.textContent = fileName;
            }
            
            // Enable submit button if file is selected
            const submitBtn = this.closest('form')?.querySelector('[type="submit"]');
            if (submitBtn) {
                submitBtn.disabled = !this.files.length;
                
                if (this.files.length) {
                    submitBtn.classList.add('btn-success');
                    submitBtn.classList.remove('btn-secondary');
                } else {
                    submitBtn.classList.remove('btn-success');
                    submitBtn.classList.add('btn-secondary');
                }
            }
        });
    });
    
    // QR Code scanner functionality
    const qrScannerContainer = document.getElementById('qr-scanner-container');
    const qrResult = document.getElementById('qr-result');
    const startScanButton = document.getElementById('start-scan');
    const stopScanButton = document.getElementById('stop-scan');
    
    // Initialize QR scanner if all elements exist
    if (qrScannerContainer && startScanButton && stopScanButton) {
        let scanner = null;
        
        // Start scanning when button clicked
        startScanButton.addEventListener('click', function() {
            // Show the scanner container
            qrScannerContainer.classList.remove('d-none');
            this.disabled = true;
            stopScanButton.disabled = false;
            
            // Clear any previous results
            if (qrResult) {
                qrResult.innerHTML = '';
                qrResult.classList.add('d-none');
            }
            
            // Initialize scanner if needed
            // Enhanced QR Code scanner configuration for better detection
            if (!scanner && window.Html5QrcodeScanner) {
                scanner = new Html5QrcodeScanner('qr-reader', {
                    fps: 15, // Increase frames per second for faster detection
                    qrbox: { width: 300, height: 300 }, // Larger scanning area for better accuracy
                    disableFlip: false, // Allow flipping for mirrored QR codes
                    aspectRatio: 1.0, // Maintain square aspect ratio
                    formatsToSupport: [Html5QrcodeSupportedFormats.QR_CODE],
                    experimentalFeatures: {
                        useBarCodeDetectorIfSupported: true // Use advanced barcode detection if available
                    },
                    rememberLastUsedCamera: true, // Automatically use the last selected camera
                    supportedScanTypes: [Html5QrcodeScanType.SCAN_TYPE_CAMERA]
                });

                // On successful scan
                scanner.render((decodedText) => {
                    console.log("QR Code detected:", decodedText); // Log detected QR code for debugging
                    // ...existing code for processing the QR code...
                }, (errorMessage) => {
                    console.warn("QR scanning error:", errorMessage); // Log warnings for missed scans
                });
            } else if (scanner) {
                scanner.render((decodedText) => {
                    // Same handler as above
                }, (errorMessage) => {
                    console.error('QR scanning error:', errorMessage);
                });
            }
        });
        
        // Stop scanning when button clicked
        stopScanButton.addEventListener('click', function() {
            if (scanner) {
                scanner.clear();
            }
            
            // Reset button states
            startScanButton.disabled = false;
            this.disabled = true;
            
            // Hide scanner container
            qrScannerContainer.classList.add('d-none');
        });
    }
    
    // Excel export button handling
    const exportButtons = document.querySelectorAll('.export-excel-btn');
    exportButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            // Show loading state
            const originalText = this.innerHTML;
            this.disabled = true;
            this.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status"></span>Exporting...`;
            
            // Get export parameters
            const exportType = this.dataset.exportType || 'all';
            const teamId = this.dataset.teamId || '';
            const matchId = this.dataset.matchId || '';
            const eventId = this.dataset.eventId || '';
            
            // Build query params
            let params = `type=${exportType}`;
            if (teamId) params += `&team_id=${teamId}`;
            if (matchId) params += `&match_id=${matchId}`;
            if (eventId) params += `&event_id=${eventId}`;
            
            // Trigger download
            window.location.href = `/data/export_excel?${params}`;
            
            // Reset button after a delay
            setTimeout(() => {
                this.disabled = false;
                this.innerHTML = originalText;
            }, 1500);
        });
    });
    
    // Excel import form handling
    const excelImportForm = document.getElementById('excel-import-form');
    if (excelImportForm) {
        excelImportForm.addEventListener('submit', function(e) {
            e.preventDefault();
            
            // Get the file input
            const fileInput = this.querySelector('input[type="file"]');
            if (!fileInput || !fileInput.files.length) {
                showToast('Please select an Excel file to import', 'warning');
                return;
            }
            
            // Show loading overlay
            window.showLoadingOverlay();
            
            // Create form data for upload
            const formData = new FormData(this);
            
            // Submit the form using fetch
            fetch(this.action, {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                // Hide loading overlay
                window.hideLoadingOverlay();
                
                if (data.success) {
                    showToast('Excel data imported successfully!', 'success');
                    
                    // Show import results
                    const resultsContainer = document.getElementById('import-results');
                    if (resultsContainer && data.results) {
                        resultsContainer.innerHTML = `
                            <div class="alert alert-success mb-4">
                                <i class="fas fa-check-circle me-2"></i>
                                Import completed successfully
                            </div>
                            <div class="card">
                                <div class="card-header">
                                    <h5 class="mb-0">Import Results</h5>
                                </div>
                                <div class="card-body">
                                    <dl class="row">
                                        <dt class="col-sm-4">Teams imported:</dt>
                                        <dd class="col-sm-8">${data.results.teams || 0}</dd>
                                        
                                        <dt class="col-sm-4">Matches imported:</dt>
                                        <dd class="col-sm-8">${data.results.matches || 0}</dd>
                                        
                                        <dt class="col-sm-4">Scouting records imported:</dt>
                                        <dd class="col-sm-8">${data.results.scouting || 0}</dd>
                                        
                                        <dt class="col-sm-4">Total records:</dt>
                                        <dd class="col-sm-8">${data.results.total || 0}</dd>
                                    </dl>
                                </div>
                            </div>
                        `;
                    }
                    
                    // Reset form
                    this.reset();
                    const fileLabel = fileInput.nextElementSibling;
                    if (fileLabel) {
                        fileLabel.textContent = 'Choose file...';
                    }
                } else {
                    // Show error message
                    showToast(`Error: ${data.message || 'Import failed'}`, 'danger');
                }
            })
            .catch(error => {
                console.error('Error importing Excel data:', error);
                window.hideLoadingOverlay();
                showToast('Server error while importing data', 'danger');
            });
        });
    }
}

/**
 * Manage offline scouting data storage and synchronization
 * This function handles the UI for the offline data management section
 */
function setupOfflineDataManager() {
    const offlineDataContainer = document.getElementById('offline-data-container');
    if (!offlineDataContainer) return;
    
    // Function to refresh the list of offline entries
    const refreshOfflineEntries = () => {
        try {
            // Get stored entries index
            const offlineScoutingIndex = JSON.parse(localStorage.getItem('offline_scouting_index') || '[]');
            
            // If no entries, show empty state
            if (offlineScoutingIndex.length === 0) {
                offlineDataContainer.innerHTML = `
                    <div class="alert alert-info">
                        <i class="fas fa-info-circle me-2"></i>
                        No offline scouting data available.
                    </div>
                `;
                return;
            }
            
            // Sort entries by timestamp (newest first)
            offlineScoutingIndex.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
            
            // Create table of entries
            let html = `
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead>
                            <tr>
                                <th>Team</th>
                                <th>Match</th>
                                <th>Date/Time</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
            `;
            
            offlineScoutingIndex.forEach(entry => {
                const date = new Date(entry.timestamp);
                const formattedDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
                
                html += `
                    <tr data-storage-key="${entry.storage_key}">
                        <td>${entry.team_number}</td>
                        <td>${entry.match_number}</td>
                        <td>${formattedDate}</td>
                        <td>
                            <div class="btn-group btn-group-sm">
                                <button type="button" class="btn btn-primary view-offline-data" title="View">
                                    <i class="fas fa-eye"></i>
                                </button>
                                <button type="button" class="btn btn-success sync-offline-data" title="Sync">
                                    <i class="fas fa-sync"></i>
                                </button>
                                <button type="button" class="btn btn-danger delete-offline-data" title="Delete">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            });
            
            html += `
                        </tbody>
                    </table>
                </div>
                <div class="d-flex justify-content-end mt-3">
                    <button type="button" class="btn btn-primary" id="sync-all-offline-data">
                        <i class="fas fa-sync me-2"></i> Sync All Offline Data
                    </button>
                </div>
            `;
            
            offlineDataContainer.innerHTML = html;
            
            // Add event listeners to buttons
            document.querySelectorAll('.view-offline-data').forEach(button => {
                button.addEventListener('click', function() {
                    const storageKey = this.closest('tr').dataset.storageKey;
                    viewOfflineData(storageKey);
                });
            });
            
            document.querySelectorAll('.sync-offline-data').forEach(button => {
                button.addEventListener('click', function() {
                    const storageKey = this.closest('tr').dataset.storageKey;
                    syncOfflineData(storageKey);
                });
            });
            
            document.querySelectorAll('.delete-offline-data').forEach(button => {
                button.addEventListener('click', function() {
                    const storageKey = this.closest('tr').dataset.storageKey;
                    deleteOfflineData(storageKey);
                });
            });
            
            const syncAllButton = document.getElementById('sync-all-offline-data');
            if (syncAllButton) {
                syncAllButton.addEventListener('click', syncAllOfflineData);
            }
        } catch (error) {
            console.error('Error refreshing offline entries:', error);
            offlineDataContainer.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    Error loading offline data: ${error.message}
                </div>
            `;
        }
    };
    
    // Function to view offline data
    const viewOfflineData = (storageKey) => {
        try {
            const data = JSON.parse(localStorage.getItem(storageKey));
            if (!data) {
                showToast('Data not found in local storage', 'error');
                return;
            }
            
            // Create and show modal with data
            let modal = document.getElementById('offline-data-modal');
            if (!modal) {
                modal = document.createElement('div');
                modal.id = 'offline-data-modal';
                modal.className = 'modal fade';
                modal.setAttribute('tabindex', '-1');
                modal.innerHTML = `
                    <div class="modal-dialog modal-lg">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Offline Scouting Data</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                            </div>
                            <div class="modal-body">
                                <pre class="bg-light p-3 rounded" style="max-height: 400px; overflow-y: auto;"></pre>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                            </div>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
            }
            
            // Populate with data
            const pre = modal.querySelector('pre');
            pre.textContent = JSON.stringify(data, null, 2);
            
            // Show modal
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();
            
        } catch (error) {
            console.error('Error viewing offline data:', error);
            showToast('Error viewing data: ' + error.message, 'danger');
        }
    };
    
    // Function to sync a single offline entry
    const syncOfflineData = async (storageKey) => {
        try {
            const data = JSON.parse(localStorage.getItem(storageKey));
            if (!data) {
                showToast('Data not found in local storage', 'error');
                return;
            }
            
            // Check connectivity
            if (!navigator.onLine) {
                showToast('Cannot sync while offline', 'warning');
                return;
            }
            
            const button = document.querySelector(`tr[data-storage-key="${storageKey}"] .sync-offline-data`);
            if (button) {
                const originalHtml = button.innerHTML;
                button.disabled = true;
                button.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
                
                try {
                    // Submit to server
                    const response = await fetch('/scouting/api/submit_offline', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(data)
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        // Remove from local storage
                        removeOfflineEntry(storageKey);
                        showToast('Data synchronized successfully!', 'success');
                        
                        // Refresh the list
                        refreshOfflineEntries();
                    } else {
                        button.disabled = false;
                        button.innerHTML = originalHtml;
                        showToast(`Error synchronizing: ${result.message}`, 'danger');
                    }
                } catch (error) {
                    button.disabled = false;
                    button.innerHTML = originalHtml;
                    showToast('Error synchronizing data with server', 'danger');
                    console.error('Sync error:', error);
                }
            }
        } catch (error) {
            console.error('Error syncing offline data:', error);
            showToast('Error preparing data for sync: ' + error.message, 'danger');
        }
    };
    
    // Function to delete offline data
    const deleteOfflineData = (storageKey) => {
        // Confirm before deleting
        if (confirm('Are you sure you want to delete this offline entry?')) {
            try {
                removeOfflineEntry(storageKey);
                showToast('Offline entry deleted', 'success');
                refreshOfflineEntries();
            } catch (error) {
                console.error('Error deleting offline data:', error);
                showToast('Error deleting entry: ' + error.message, 'danger');
            }
        }
    };
    
    // Helper function to remove an entry from local storage
    const removeOfflineEntry = (storageKey) => {
        // Remove from index
        let offlineScoutingIndex = JSON.parse(localStorage.getItem('offline_scouting_index') || '[]');
        offlineScoutingIndex = offlineScoutingIndex.filter(entry => entry.storage_key !== storageKey);
        localStorage.setItem('offline_scouting_index', JSON.stringify(offlineScoutingIndex));
        
        // Remove actual data
        localStorage.removeItem(storageKey);
    };
    
    // Function to sync all offline data
    const syncAllOfflineData = async () => {
        const offlineScoutingIndex = JSON.parse(localStorage.getItem('offline_scouting_index') || '[]');
        if (offlineScoutingIndex.length === 0) {
            showToast('No offline entries to sync', 'info');
            return;
        }
        
        // Check connectivity
        if (!navigator.onLine) {
            showToast('Cannot sync while offline', 'warning');
            return;
        }
        
        const syncAllButton = document.getElementById('sync-all-offline-data');
        if (syncAllButton) {
            const originalHtml = syncAllButton.innerHTML;
            syncAllButton.disabled = true;
            syncAllButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Syncing...';
            
            // Count for stats
            let success = 0;
            let failed = 0;
            
            // Process each entry
            for (const entry of offlineScoutingIndex) {
                try {
                    const data = JSON.parse(localStorage.getItem(entry.storage_key));
                    if (!data) continue;
                    
                    // Submit to server
                    const response = await fetch('/scouting/api/submit_offline', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(data)
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        // Remove from local storage
                        localStorage.removeItem(entry.storage_key);
                        success++;
                    } else {
                        failed++;
                        console.error('Error syncing entry:', result.message);
                    }
                } catch (error) {
                    failed++;
                    console.error('Error processing entry:', error);
                }
            }
            
            // Update index to remove synced entries
            let updatedIndex = [];
            if (failed > 0) {
                // If any failed, rebuild the index from remaining entries
                updatedIndex = [];
                offlineScoutingIndex.forEach(entry => {
                    if (localStorage.getItem(entry.storage_key)) {
                        updatedIndex.push(entry);
                    }
                });
            }
            
            localStorage.setItem('offline_scouting_index', JSON.stringify(updatedIndex));
            
            // Reset button state
            syncAllButton.disabled = false;
            syncAllButton.innerHTML = originalHtml;
            
            // Show result message
            showToast(`Sync complete: ${success} successful, ${failed} failed`, success > 0 ? 'success' : 'warning');
            
            // Refresh the list
            refreshOfflineEntries();
        }
    };
    
    // Initialize by refreshing the entries list
    refreshOfflineEntries();
    
    // Set up refresh button if it exists
    const refreshButton = document.getElementById('refresh-offline-data');
    if (refreshButton) {
        refreshButton.addEventListener('click', refreshOfflineEntries);
    }
}

// Initialize offline data manager when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    setupOfflineDataManager();
});

/**
 * Helper function to attempt recovery of malformed QR data
 * @param {string} rawData - The raw data from QR code
 * @returns {Object|null} - Recovered data object or null if recovery failed
 */
function attemptQRDataRecovery(rawData) {
    // Bail out early if empty data
    if (!rawData || rawData.trim() === '') return null;
    
    try {
        // First try direct JSON parse in case it's valid but threw an error in the main flow
        return JSON.parse(rawData);
    } catch (e) {
        // Continue with recovery methods
    }
    
    try {
        // Check if it's our minimal t/m/d format
        if (rawData.includes('"t":') && rawData.includes('"m":') && rawData.includes('"d":')) {
            // Try to fix common JSON formatting issues
            let fixedData = rawData.replace(/'/g, '"');  // Replace single quotes with double quotes
            fixedData = fixedData.replace(/(\w+):/g, '"$1":'); // Add quotes to keys
            
            // Try to parse again
            try {
                const parsed = JSON.parse(fixedData);
                
                // Expand to full format
                return {
                    team_id: parsed.t,
                    match_id: parsed.m,
                    data: parsed.d,
                    recovered: true
                };
            } catch (e) {
                // Continue with other methods
            }
        }
        
        // Check for comma-separated format
        if (rawData.includes(',') && !rawData.includes('{')) {
            const parts = rawData.split(',');
            if (parts.length >= 3) {
                // Assume team_id, match_id, data format
                return {
                    team_id: parts[0].trim(),
                    match_id: parts[1].trim(),
                    data: parts.slice(2).join(',').trim(),
                    recovered: true,
                    format: 'comma-separated'
                };
            }
        }
        
        // Check for colon-based format
        if (rawData.includes(':') && !rawData.includes('{')) {
            const parts = rawData.split(':');
            if (parts.length >= 2) {
                // Attempt to parse as key:value pairs
                const dataObj = {};
                
                for (let i = 0; i < parts.length; i += 2) {
                    if (i + 1 < parts.length) {
                        const key = parts[i].trim();
                        const value = parts[i + 1].trim();
                        dataObj[key] = isNaN(value) ? value : Number(value);
                    }
                }
                
                if (Object.keys(dataObj).length > 0) {
                    return {
                        recovered: true,
                        format: 'colon-separated',
                        ...dataObj
                    };
                }
            }
        }
        
        // Try to handle serialized or escaped JSON
        if (rawData.includes('\\')) {
            // Try to unescape
            const unescaped = rawData.replace(/\\"/g, '"')
                                      .replace(/\\\\/g, '\\')
                                      .replace(/\\n/g, '\n')
                                      .replace(/\\r/g, '\r')
                                      .replace(/\\t/g, '\t');
            
            // Check if it's now valid JSON
            try {
                return JSON.parse(unescaped);
            } catch (e) {
                // Continue with other methods
            }
        }
        
        // Last resort: If it looks like it has numbers and separators,
        // treat it as a key-value structure with = or : separators
        if (/[0-9]+[=:]/i.test(rawData)) {
            const dataObj = {};
            
            // Try to extract key-value pairs
            const pairs = rawData.match(/([A-Za-z0-9_]+)[=:]([^=:]+)(?=[A-Za-z0-9_]+[=:]|$)/g);
            
            if (pairs && pairs.length > 0) {
                pairs.forEach(pair => {
                    const [key, value] = pair.split(/[=:]/);
                    if (key && value) {
                        dataObj[key.trim()] = isNaN(value.trim()) ? value.trim() : Number(value.trim());
                    }
                });
                
                if (Object.keys(dataObj).length > 0) {
                    return {
                        recovered: true,
                        format: 'key-value-extracted',
                        ...dataObj
                    };
                }
            }
        }
        
        // If all attempts failed
        return null;
    } catch (error) {
        console.error('Recovery error:', error);
        return null;
    }
}

/**
 * Initialize scouting form with online/offline save functionality
 */
function initScoutingForm() {
    const form = document.getElementById('scouting-form');
    const saveButton = document.getElementById('save-button');
    const generateQRButton = document.getElementById('generateQR');
    
    if (!form || !saveButton) return;
    
    // Initialize points calculation
    initializePointsCalculation();
    
    // Handle save button click
    saveButton.addEventListener('click', async function(e) {
        // Prevent default form submission
        e.preventDefault();

        // If the browser is offline, skip network attempts and fall back immediately
        if (!navigator.onLine) {
            showToast('You appear to be offline. Generating QR code / saving locally instead.', 'warning');
            generateQRCode();
            return;
        }

        // If online, always attempt to submit to the server first. This avoids cases where
        // the ping-based status incorrectly hides the server save option when the server
        // is actually reachable.
        try {
            try { if (typeof refreshServerStatus === 'function') refreshServerStatus(); } catch (e) { /* ignore */ }
            submitScoutingForm();
        } catch (e) {
            console.warn('Error attempting to submit scouting form:', e);
            showToast('Unable to save directly. Generating QR code instead.', 'warning');
            generateQRCode();
        }
    });

    // Attach save-local handler via reusable function
    if (typeof setupSaveLocally === 'function') {
        try { setupSaveLocally(); } catch (e) { /* ignore */ }
    }
    
    // Submit the form data directly to the server (with one quick retry on transient failures)
    function submitScoutingForm() {
        // Show loading state on button
        const originalText = saveButton.innerHTML;
        saveButton.disabled = true;
        saveButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Saving...';

        // Get form data
        const formData = new FormData(form);

        const doFetch = () => fetch('/scouting/api/save', { method: 'POST', body: formData });

        // Attempt save, then retry once on failure if still online
        doFetch()
        .then(async response => {
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return response.json();
        })
        .then(data => {
            // Reset button state
            saveButton.disabled = false;
            saveButton.innerHTML = originalText;

            // Handle response
            if (data && data.success) {
                showToast('Scouting data saved successfully!', 'success');
            } else {
                showToast(`Error: ${data && data.message ? data.message : 'Failed to save data'}`, 'danger');
            }
        })
        .catch(async error => {
            console.warn('Error saving scouting data (first attempt):', error);

            // If we're still online, try one quick retry after refreshing server status
            if (navigator.onLine) {
                try {
                    await new Promise(r => setTimeout(r, 800));
                    if (typeof refreshServerStatus === 'function') await refreshServerStatus();
                    const retryResp = await doFetch();
                    if (retryResp.ok) {
                        const retryData = await retryResp.json();
                        saveButton.disabled = false;
                        saveButton.innerHTML = originalText;
                        if (retryData && retryData.success) {
                            showToast('Scouting data saved successfully (on retry)!', 'success');
                            return;
                        } else {
                            showToast(`Error: ${retryData && retryData.message ? retryData.message : 'Failed to save data'}`, 'danger');
                            return;
                        }
                    }
                } catch (e2) {
                    console.warn('Retry failed:', e2);
                }
            }

            // Reset button state and fallback to QR/local save
            saveButton.disabled = false;
            saveButton.innerHTML = originalText;
            showToast('Unable to save data directly. Falling back to QR code.', 'warning');
            setTimeout(() => { generateQRCode(); }, 1000);
        });
    }
}

// Initialize the scouting form when the DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Add to the existing event listeners
    initScoutingForm();
});

/**
 * Attach handler to "Save Locally" button to persist form to localStorage
 */
function setupSaveLocally() {
    const form = document.getElementById('scouting-form');
    const saveLocalButton = document.getElementById('save-local-button');
    if (!form || !saveLocalButton) return;

    // Remove previous listener if present by cloning
    const newBtn = saveLocalButton.cloneNode(true);
    saveLocalButton.parentNode.replaceChild(newBtn, saveLocalButton);

    newBtn.addEventListener('click', function(e) {
        e.preventDefault();

        if (!form.checkValidity()) {
            form.classList.add('was-validated');
            showToast('Please fix form errors before saving locally', 'warning');
            return;
        }

        try {
            const formData = new FormData(form);
            const formObject = {};

            formData.forEach((value, key) => {
                const element = form.elements[key];
                if (element && element.type === 'checkbox') {
                    formObject[key] = element.checked;
                } else if (element && element.type === 'number' || (!isNaN(value) && value !== '')) {
                    formObject[key] = Number(value);
                } else {
                    formObject[key] = value;
                }
            });

            // Ensure unchecked checkboxes are included
            form.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
                if (!formObject.hasOwnProperty(checkbox.id)) {
                    formObject[checkbox.id] = false;
                }
            });

            // Add calculated points
            const pointsElements = document.querySelectorAll('.points-display');
            pointsElements.forEach(element => {
                const metricId = element.dataset.metricId;
                if (metricId) {
                    const pointsValue = element.querySelector('.points-value');
                    if (pointsValue) {
                        formObject[metricId + '_points'] = parseInt(pointsValue.textContent || '0');
                    }
                }
            });

            // Metadata
            formObject.generated_at = new Date().toISOString();
            formObject.offline_saved = true;

            // Defensive fallback: ensure scout_name is populated even if the input was left blank
            try {
                const scoutField = form.elements['scout_name'] || document.getElementById('scout_name');
                const fallbackScout = (scoutField && scoutField.placeholder) ? scoutField.placeholder : (scoutField && scoutField.value) ? scoutField.value : 'Unknown';
                if (!formObject.scout_name || (typeof formObject.scout_name === 'string' && formObject.scout_name.trim() === '')) {
                    formObject.scout_name = fallbackScout;
                }
            } catch (e) {
                // ignore any issues from missing elements
            }

            // Build storage key and index entry
            const timestamp = new Date().toISOString();
            const storageKey = `offline_scouting_${Date.now()}`;

            // Try to capture team/match numbers for the index
            const teamNumber = formObject.team_number || formObject.team_id || '';
            const matchNumber = formObject.match_number || formObject.match_id || '';

            // Save item
            localStorage.setItem(storageKey, JSON.stringify(formObject));

            // Update index
            let index = JSON.parse(localStorage.getItem('offline_scouting_index') || '[]');
            index.push({
                storage_key: storageKey,
                team_number: teamNumber,
                match_number: matchNumber,
                timestamp: timestamp
            });
            localStorage.setItem('offline_scouting_index', JSON.stringify(index));

            showToast('Form saved locally. You can sync it later from the Offline Data page.', 'success');

            // Refresh offline manager UI if present
            if (typeof setupOfflineDataManager === 'function') {
                try { setupOfflineDataManager(); } catch (e) { /* ignore */ }
            }
        } catch (error) {
            console.error('Error saving form locally:', error);
            showToast('Failed to save locally', 'danger');
        }
    });
}

function showDeleteConfirmNotification(btn, entryId) {
    // Use Bootstrap toast if available, else fallback to alert
    if (window.bootstrap && document.getElementById('delete-toast')) {
        const toast = document.getElementById('delete-toast');
        toast.querySelector('.toast-body').textContent = 'Click again to confirm delete.';
        new bootstrap.Toast(toast).show();
    } else {
        // Create a temporary non-blocking toast if Bootstrap is available, otherwise a console message
        if (window.bootstrap) {
            // Create toast container if needed
            let container = document.getElementById('global-toast-container');
            if (!container) {
                container = document.createElement('div');
                container.id = 'global-toast-container';
                container.className = 'position-fixed bottom-0 end-0 p-3';
                container.style.zIndex = 9999;
                document.body.appendChild(container);
            }

            const toastEl = document.createElement('div');
            toastEl.className = 'toast align-items-center text-bg-warning border-0';
            toastEl.setAttribute('role', 'alert');
            toastEl.setAttribute('aria-live', 'assertive');
            toastEl.setAttribute('aria-atomic', 'true');
            toastEl.style.minWidth = '200px';

            const toastBody = document.createElement('div');
            toastBody.className = 'd-flex';
            toastBody.innerHTML = `<div class="toast-body">Click again to confirm delete.</div>`;

            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn-close btn-close-white me-2 m-auto';
            btn.setAttribute('data-bs-dismiss', 'toast');
            btn.setAttribute('aria-label', 'Close');

            toastBody.appendChild(btn);
            toastEl.appendChild(toastBody);
            container.appendChild(toastEl);

            const bsToast = new bootstrap.Toast(toastEl, { autohide: true, delay: 4000 });
            bsToast.show();
            // Remove element after hidden
            toastEl.addEventListener('hidden.bs.toast', () => {
                toastEl.remove();
            });
        } else {
            console.log('Click again to confirm delete.');
        }
    }
}

// Utility: Fetch API data from IndexedDB if offline
async function getAPIDataFromIDB(url) {
    return new Promise(resolve => {
        const open = indexedDB.open('ScoutAppDB', 1);
        open.onupgradeneeded = () => {
            open.result.createObjectStore('api', { keyPath: 'url' });
        };
        open.onsuccess = () => {
            const db = open.result;
            const tx = db.transaction('api', 'readonly');
            const req = tx.objectStore('api').get(url);
            req.onsuccess = () => {
                resolve(req.result ? req.result.data : null);
                db.close();
            };
            req.onerror = () => {
                resolve(null);
                db.close();
            };
        };
        open.onerror = () => resolve(null);
    });
}

// Example usage: Fetch API data, fallback to IndexedDB if offline
async function fetchWithOfflineFallback(apiUrl) {
    if (navigator.onLine) {
        try {
            const res = await fetch(apiUrl);
            if (res.ok) return await res.json();
        } catch (e) {
            // Network error, fallback to IDB
        }
    }
    // Offline or fetch failed
    const cached = await getAPIDataFromIDB(apiUrl);
    if (cached) return cached;
    throw new Error('No data available offline');
}