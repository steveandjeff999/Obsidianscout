/**
 * Offline Scouting Form Manager
 * Caches match schedule, team data, and game config for full offline functionality
 */

(function() {
    'use strict';

    const CACHE_KEYS = {
        TEAMS: 'scouting_teams_cache',
        MATCHES: 'scouting_matches_cache',
        GAME_CONFIG: 'scouting_game_config_cache',
        CURRENT_EVENT: 'scouting_current_event_cache',
        CACHE_TIMESTAMP: 'scouting_cache_timestamp',
        OFFLINE_FORMS: 'scouting_offline_forms',
        FORM_HTML_TEMPLATE: 'scouting_form_html_template'  // Single universal form template
    };

    const CACHE_DURATION = 24 * 60 * 60 * 1000; // 24 hours in milliseconds

    /**
     * Initialize offline caching system
     */
    function initializeOfflineCache() {
        // Check if we're on the scouting form page
        if (!window.location.pathname.includes('/scouting/form')) {
            return;
        }

        console.log('[Offline Manager] Initializing offline cache for scouting form...');

        // Cache data on page load if online
        if (navigator.onLine) {
            cacheScoutingData();
            
            // Start pre-caching forms after initial data is cached
            setTimeout(() => {
                preCacheAllForms();
            }, 2000); // Wait 2 seconds to avoid blocking initial page load
        }

        // Listen for online/offline events
        window.addEventListener('online', handleOnline);
        window.addEventListener('offline', handleOffline);

        // Check cache age and refresh if needed
        checkCacheAge();
        
        // Intercept form loads to cache rendered HTML
        interceptFormLoads();
        
        // Attach match selector listener so team dropdown can be filtered locally (works offline)
        try {
            const matchSel = document.getElementById('match-selector');
            if (matchSel) {
                matchSel.addEventListener('change', function() {
                    try { filterTeamsByMatchId(this.value); } catch (e) { /* ignore */ }
                });

                // Apply initial filter if a match is already selected or stored
                const initialMatch = matchSel.value || localStorage.getItem('last_match_id');
                if (initialMatch) {
                    try { filterTeamsByMatchId(initialMatch); } catch (e) { /* ignore */ }
                }
            }
        } catch (e) {
            // ignore attach errors
        }
        // Ensure server status and save button visibility reflect current connectivity on initial load
        try {
            // Do an immediate server check and schedule periodic checks
            refreshServerStatus();
            if (!window._scoutingServerPingInterval) {
                window._scoutingServerPingInterval = setInterval(refreshServerStatus, 15000); // every 15s
                // Expose helpers for other modules to reuse
                try { window.refreshServerStatus = refreshServerStatus; window.updateSaveButtonVisibility = updateSaveButtonVisibility; window.checkServerReachable = checkServerReachable; } catch (e) { /* ignore */ }
                // Clear interval on unload to avoid background pings
                const cleanup = () => {
                    try { clearInterval(window._scoutingServerPingInterval); window._scoutingServerPingInterval = null; } catch (e) {}
                };
                window.addEventListener('beforeunload', cleanup, { once: true });
            }
        } catch (e) { /* ignore */ }
    }

    /**
     * Cache all necessary scouting data
     */
    function cacheScoutingData() {
        console.log('[Offline Manager] Caching scouting data...');

        try {
            // Cache teams data
            const teamsSelect = document.getElementById('team-selector');
            if (teamsSelect) {
                const teams = Array.from(teamsSelect.options)
                    .filter(opt => opt.value)
                    .map(opt => ({
                        id: opt.value,
                        team_number: opt.getAttribute('data-team-number'),
                        team_name: opt.getAttribute('data-team-name'),
                        text: opt.textContent
                    }));
                
                localStorage.setItem(CACHE_KEYS.TEAMS, JSON.stringify(teams));
                console.log(`[Offline Manager] Cached ${teams.length} teams`);
            }

            // Cache matches data with alliance information
            const matchesSelect = document.getElementById('match-selector');
            if (matchesSelect) {
                const matches = Array.from(matchesSelect.options)
                    .filter(opt => opt.value)
                    .map(opt => ({
                        id: opt.value,
                        match_type: opt.getAttribute('data-match-type'),
                        match_number: opt.getAttribute('data-match-number'),
                        red_alliance: opt.getAttribute('data-red-alliance') || '',
                        blue_alliance: opt.getAttribute('data-blue-alliance') || '',
                        text: opt.textContent
                    }));
                
                localStorage.setItem(CACHE_KEYS.MATCHES, JSON.stringify(matches));
                console.log(`[Offline Manager] Cached ${matches.length} matches with alliance data`);
            }

            // Cache game config if available in the page
            if (typeof window.gameConfig !== 'undefined') {
                localStorage.setItem(CACHE_KEYS.GAME_CONFIG, JSON.stringify(window.gameConfig));
                console.log('[Offline Manager] Cached game config');
            }

            // Always cache/update universal form template HTML if present (to capture config changes)
            const formContent = document.getElementById('form-content');
            const scoutingForm = document.getElementById('scouting-form');
            if (formContent && scoutingForm) {
                const formHTML = formContent.innerHTML;
                
                try {
                    localStorage.setItem(CACHE_KEYS.FORM_HTML_TEMPLATE, formHTML);
                    console.log('[Offline Manager] Cached/updated universal form template HTML');
                } catch (e) {
                    console.warn('[Offline Manager] Could not cache form template:', e);
                }
            }

            // Update cache timestamp
            localStorage.setItem(CACHE_KEYS.CACHE_TIMESTAMP, Date.now().toString());
            
            console.log('[Offline Manager] All data cached successfully');

            // Proactively cache a universal form template if we are online and none is stored yet
            if (navigator.onLine) {
                try {
                    const hasTemplate = !!localStorage.getItem(CACHE_KEYS.FORM_HTML_TEMPLATE);
                    const teams = JSON.parse(localStorage.getItem(CACHE_KEYS.TEAMS) || '[]');
                    const matches = JSON.parse(localStorage.getItem(CACHE_KEYS.MATCHES) || '[]');
                    if (!hasTemplate && teams.length && matches.length) {
                        cacheFormHTMLTemplate(teams[0].id, matches[0].id);
                    }
                } catch (e) {
                    console.warn('[Offline Manager] Could not auto-cache template:', e);
                }
            }
        } catch (e) {
            console.error('[Offline Manager] Error caching data:', e);
        }
    }
    
    /**
     * Intercept form loads to cache server-rendered HTML template (always update to catch config changes)
     */
    function interceptFormLoads() {
        // Always cache/update the form template on load to capture config changes
        window._scoutingFormLoadHandler = function(teamId, matchId, formHTML) {
            if (!formHTML) return;
            
            // Always update to ensure latest config is cached
            try {
                localStorage.setItem(CACHE_KEYS.FORM_HTML_TEMPLATE, formHTML);
                console.log('[Offline Manager] Cached/updated universal form template HTML');
            } catch (e) {
                console.warn('[Offline Manager] Could not cache form template:', e);
            }
        };
    }
    
    /**
     * Pre-cache/update universal form template (always fetch to ensure latest config)
     */
    async function preCacheAllForms() {
        if (!navigator.onLine) {
            console.log('[Offline Manager] Cannot pre-cache form while offline');
            return;
        }
        
        // Always update template to ensure latest config (no longer check if already cached)
        console.log('[Offline Manager] Updating form template cache...');
        
        const teams = getCachedTeams();
        const matches = getCachedMatches();
        
        if (!teams.length || !matches.length) {
            console.log('[Offline Manager] No teams or matches available for pre-caching');
            return;
        }
        
        // Check if we should pre-cache (user preference or automatic)
        const preCacheEnabled = localStorage.getItem('scouting_precache_enabled') !== 'false'; // Default true
        if (!preCacheEnabled) {
            console.log('[Offline Manager] Pre-caching disabled by user preference');
            return;
        }
        
        console.log('[Offline Manager] Fetching/updating universal form template...');
        showNotification('Updating form template cache...', 'info');
        
        // Fetch one form as the universal template (use first team and first match)
        const success = await cacheFormHTMLTemplate(teams[0].id, matches[0].id);
        
        if (success) {
            console.log('[Offline Manager] Universal form template updated successfully');
            showNotification('Form template updated - latest config now available offline!', 'success');
            localStorage.setItem('scouting_precache_timestamp', Date.now().toString());
        } else {
            console.error('[Offline Manager] Failed to update universal form template');
            showNotification('Failed to update form template', 'error');
        }
    }
    
    /**
     * Cache universal form HTML template by fetching from server
     */
    async function cacheFormHTMLTemplate(teamId, matchId) {
        try {
            const formData = new FormData();
            formData.append('team_id', teamId);
            formData.append('match_id', matchId);
            
            const response = await fetch(window.location.pathname, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const data = await response.json();
            
            if (data.success && data.html) {
                try {
                    localStorage.setItem(CACHE_KEYS.FORM_HTML_TEMPLATE, data.html);
                    console.log('[Offline Manager] Universal form template cached');
                    return true;
                } catch (e) {
                    console.warn('[Offline Manager] Could not cache form template:', e);
                    return false;
                }
            }
            
            return false;
        } catch (error) {
            console.warn('[Offline Manager] Error caching form template:', error);
            return false;
        }
    }

    /**
     * Check if cache is stale and needs refresh
     */
    function checkCacheAge() {
        try {
            const timestamp = localStorage.getItem(CACHE_KEYS.CACHE_TIMESTAMP);
            if (!timestamp) {
                console.log('[Offline Manager] No cache timestamp found');
                return;
            }

            const age = Date.now() - parseInt(timestamp);
            if (age > CACHE_DURATION) {
                console.log('[Offline Manager] Cache is stale, refreshing...');
                if (navigator.onLine) {
                    cacheScoutingData();
                }
            } else {
                console.log(`[Offline Manager] Cache is fresh (${Math.round(age / 1000 / 60)} minutes old)`);
            }
        } catch (e) {
            console.error('[Offline Manager] Error checking cache age:', e);
        }
    }

    /**
     * Handle online event
     */
    function handleOnline() {
        console.log('[Offline Manager] Connection restored');
        showNotification('Connection restored. Syncing data...', 'success');
        
        // Refresh cache with latest data
        cacheScoutingData();
        
        // Try to sync any offline forms
        syncOfflineForms();
        
        // Recheck server reachability and update UI
        try { refreshServerStatus(); } catch (e) { /* ignore */ }
        
        // Check if pre-cache is stale and refresh if needed
        const preCacheTimestamp = localStorage.getItem('scouting_precache_timestamp');
        if (!preCacheTimestamp || (Date.now() - parseInt(preCacheTimestamp)) > CACHE_DURATION) {
            console.log('[Offline Manager] Pre-cache is stale, refreshing...');
            setTimeout(() => {
                preCacheAllForms();
            }, 5000); // Wait 5 seconds after coming online
        }
    }

    /**
     * Handle offline event
     */
    function handleOffline() {
        console.log('[Offline Manager] Connection lost');
        showNotification('You are now offline. Form will work from cached data.', 'warning');
        // Update UI to reflect offline state
        try { updateSaveButtonVisibility(); } catch (e) { /* ignore */ }
    }

    /**
     * Check whether the server is reachable by pinging a lightweight health endpoint with timeout
     * Returns a Promise<boolean>
     */
    function checkServerReachable(timeoutMs = 2500) {
        const url = '/health';
        try {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), timeoutMs);
            return fetch(url + '?_=' + Date.now(), {
                method: 'GET',
                cache: 'no-store',
                headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest', 'Pragma': 'no-cache' },
                signal: controller.signal
            }).then(async resp => {
                clearTimeout(timer);
                if (!resp || !resp.ok) return false;
                // Ensure we received the expected JSON health response (not cached HTML fallback)
                const ct = resp.headers.get('content-type') || '';
                if (!ct.toLowerCase().includes('application/json')) return false;
                try {
                    const body = await resp.json();
                    // Accept either {status:'healthy'} or {status:'ok'} (case-insensitive)
                    if (body && body.status && String(body.status).toLowerCase().includes('heal')) return true;
                    if (body && body.status && String(body.status).toLowerCase().includes('ok')) return true;
                    // If health endpoint returns other successful JSON, consider it reachable
                    return true;
                } catch (e) {
                    return false;
                }
            }).catch(err => {
                clearTimeout(timer);
                return false;
            });
        } catch (e) {
            return Promise.resolve(false);
        }
    }

    /**
     * Refresh stored server status and update UI
     */
    function refreshServerStatus() {
        // Debounce multiple calls by honoring an in-flight check
        if (refreshServerStatus._inFlight) return refreshServerStatus._inFlight;
        const p = checkServerReachable().then(online => {
            window.scoutingServerOnline = !!online;
            console.log('[Offline Manager] server reachable:', window.scoutingServerOnline);
            try { updateSaveButtonVisibility(); } catch (e) { /* ignore */ }
            return online;
        }).finally(() => { refreshServerStatus._inFlight = null; });
        refreshServerStatus._inFlight = p;
        return p;
    }

    /**
     * Update visibility of save controls based on server reachability (preferred) or fallback to navigator.onLine
     */
    function updateSaveButtonVisibility() {
        try {
            const saveButton = document.getElementById('save-button');
            const saveLocalBtn = document.getElementById('save-local-button');
            if (!saveButton) return;

            // Always show the server "Save" button so users can attempt to save even when
            // the server ping indicates unreachable (some networks/proxies misreport reachability).
            saveButton.classList.remove('d-none');
            saveButton.disabled = false;
            if (saveLocalBtn) saveLocalBtn.classList.remove('d-none');

            // Kick off a background validation to keep the cached server status updated (best-effort)
            try { refreshServerStatus(); } catch (e) { /* ignore */ }
        } catch (e) {
            console.warn('[Offline Manager] updateSaveButtonVisibility error', e);
        }
    }

    /**
     * Get cached teams
     */
    function getCachedTeams() {
        try {
            const cached = localStorage.getItem(CACHE_KEYS.TEAMS);
            return cached ? JSON.parse(cached) : [];
        } catch (e) {
            console.error('[Offline Manager] Error getting cached teams:', e);
            return [];
        }
    }

    /**
     * Get cached matches
     */
    function getCachedMatches() {
        try {
            const cached = localStorage.getItem(CACHE_KEYS.MATCHES);
            return cached ? JSON.parse(cached) : [];
        } catch (e) {
            console.error('[Offline Manager] Error getting cached matches:', e);
            return [];
        }
    }

    /**
     * Get cached game config
     */
    function getCachedGameConfig() {
        try {
            const cached = localStorage.getItem(CACHE_KEYS.GAME_CONFIG);
            return cached ? JSON.parse(cached) : null;
        } catch (e) {
            console.error('[Offline Manager] Error getting cached game config:', e);
            return null;
        }
    }

    /**
     * Save form data offline
     */
    function saveFormOffline(formData) {
        try {
            const offlineForms = JSON.parse(localStorage.getItem(CACHE_KEYS.OFFLINE_FORMS) || '[]');
            
            const formEntry = {
                id: Date.now(),
                timestamp: new Date().toISOString(),
                data: formData,
                synced: false
            };
            
            offlineForms.push(formEntry);
            localStorage.setItem(CACHE_KEYS.OFFLINE_FORMS, JSON.stringify(offlineForms));
            
            console.log('[Offline Manager] Form saved offline:', formEntry.id);
            return formEntry;
        } catch (e) {
            console.error('[Offline Manager] Error saving form offline:', e);
            return null;
        }
    }

    /**
     * Sync offline forms when back online
     */
    async function syncOfflineForms() {
        try {
            const offlineForms = JSON.parse(localStorage.getItem(CACHE_KEYS.OFFLINE_FORMS) || '[]');
            const unsyncedForms = offlineForms.filter(f => !f.synced);
            
            if (unsyncedForms.length === 0) {
                console.log('[Offline Manager] No offline forms to sync');
                return;
            }

            console.log(`[Offline Manager] Syncing ${unsyncedForms.length} offline forms...`);
            
            let syncedCount = 0;
            for (const form of unsyncedForms) {
                try {
                    const response = await fetch('/scouting/api/save', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(form.data)
                    });

                    if (response.ok) {
                        form.synced = true;
                        syncedCount++;
                        console.log(`[Offline Manager] Synced form ${form.id}`);
                    } else {
                        console.error(`[Offline Manager] Failed to sync form ${form.id}:`, response.statusText);
                    }
                } catch (e) {
                    console.error(`[Offline Manager] Error syncing form ${form.id}:`, e);
                }
            }

            // Update localStorage with synced status
            localStorage.setItem(CACHE_KEYS.OFFLINE_FORMS, JSON.stringify(offlineForms));
            
            if (syncedCount > 0) {
                showNotification(`Successfully synced ${syncedCount} offline form(s)`, 'success');
            }
            
            // Clean up synced forms older than 7 days
            const sevenDaysAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
            const cleaned = offlineForms.filter(f => !f.synced || f.id > sevenDaysAgo);
            localStorage.setItem(CACHE_KEYS.OFFLINE_FORMS, JSON.stringify(cleaned));
            
        } catch (e) {
            console.error('[Offline Manager] Error syncing offline forms:', e);
        }
    }

    /**
     * Get cached universal form HTML template
     */
    function getCachedFormHTMLTemplate() {
        try {
            const html = localStorage.getItem(CACHE_KEYS.FORM_HTML_TEMPLATE);
            if (html) {
                console.log('[Offline Manager] Found cached universal form template');
                return html;
            }
        } catch (e) {
            console.error('[Offline Manager] Error retrieving cached form template:', e);
        }
        return null;
    }

    /**
     * Parse an alliance string like "111,222,333" into an array of team numbers
     */
    function parseAllianceTeams(allianceStr) {
        if (!allianceStr) return [];
        return allianceStr.split(',').map(s => s.trim()).filter(Boolean);
    }

    /**
     * Filter team <option>s to only those participating in the given matchId.
     * This runs entirely in-browser using cached MATCHES and TEAMS data so it works offline.
     * If matchId is falsy, it will clear the filter and show all teams again.
     */
    function filterTeamsByMatchId(matchId) {
        try {
            const teamsSelect = document.getElementById('team-selector');
            if (!teamsSelect) return;

            // If no match specified, show all teams
            if (!matchId) {
                Array.from(teamsSelect.options).forEach(opt => {
                    opt.hidden = false;
                    opt.style.display = '';
                });

                // Sync any custom select UI
                if (teamsSelect._customWrapper) syncCustomSelectVisibilityForNative(teamsSelect);
                return;
            }

            const matches = getCachedMatches();
            const match = matches.find(m => String(m.id) === String(matchId));
            if (!match) {
                // If we don't have the match cached, do nothing (leave options unchanged)
                return;
            }

            const red = parseAllianceTeams(match.red_alliance || '');
            const blue = parseAllianceTeams(match.blue_alliance || '');
            const allowed = new Set([...red, ...blue].map(s => String(s)));

            // Show placeholder option always and hide others not in allowed set
            Array.from(teamsSelect.options).forEach(opt => {
                if (!opt.value) { // placeholder option
                    opt.hidden = false;
                    opt.style.display = '';
                    return;
                }

                const teamNumber = opt.getAttribute('data-team-number') || opt.textContent || '';
                const allowedFlag = allowed.has(String(teamNumber).trim());

                opt.hidden = !allowedFlag;
                opt.style.display = allowedFlag ? '' : 'none';
            });

            // If current selection is now hidden, reset to placeholder
            const current = teamsSelect.options[teamsSelect.selectedIndex];
            if (current && current.hidden) {
                teamsSelect.value = '';
            }

            // Sync any custom select UI
            if (teamsSelect._customWrapper) syncCustomSelectVisibilityForNative(teamsSelect);
        } catch (e) {
            console.warn('[Offline Manager] Error filtering teams by match:', e);
        }
    }

    // Helper to sync custom select wrapper items for a native select element
    function syncCustomSelectVisibilityForNative(nativeSelect) {
        try {
            const wrapper = nativeSelect._customWrapper;
            if (!wrapper) return;
            const menu = wrapper.querySelector('.custom-select-menu');
            const items = Array.from(menu.querySelectorAll('.custom-select-item'));

            Array.from(nativeSelect.options).forEach((opt, idx) => {
                const item = items[idx];
                if (!item) return;
                if (opt.hidden) item.style.display = 'none'; else item.style.display = '';
                // keep selected/placeholder state in sync
                if (opt.selected) {
                    wrapper.querySelector('.custom-select-value').textContent = opt.textContent;
                    items.forEach(i => i.classList.remove('selected'));
                    item.classList.add('selected');
                }
            });
        } catch (e) {
            // Silently ignore if custom UI not present or structured differently
        }
    }

    /**
     * Generate form content offline using cached data
     */
    function generateFormOffline(teamId, matchId) {
        console.log('[Offline Manager] Loading form offline...');

        const teams = getCachedTeams();
        const matches = getCachedMatches();
        const team = teams.find(t => t.id == teamId);
        const match = matches.find(m => m.id == matchId);

        if (!team || !match) {
            console.error('[Offline Manager] Team or match not found in cache');
            showNotification('Cannot load form offline. Please connect to the internet first.', 'error');
            return null;
        }

        // Try to get cached universal form template
        const cachedHTML = getCachedFormHTMLTemplate();
        if (cachedHTML) {
            console.log('[Offline Manager] Using cached universal form template');
            
            return {
                html: cachedHTML,
                team: team,
                match: match,
                offline: true,
                cached: true,
                needsReset: true  // Flag to reset form values
            };
        }

        // Fallback: generate from game config (less ideal but works)
        const gameConfig = getCachedGameConfig();

        if (!gameConfig) {
            console.error('[Offline Manager] Missing game config for offline form generation');
            showNotification('Cannot load form offline. Please connect to the internet first.', 'error');
            return null;
        }

        return {
            team: team,
            match: match,
            gameConfig: gameConfig,
            offline: true,
            cached: false,
            needsReset: false
        };
    }

    /**
     * Show notification to user
     */
    function showNotification(message, type = 'info') {
        // Try to use existing toast system
        if (typeof showToast === 'function') {
            showToast(message, type);
            return;
        }

        // Fallback: create simple notification
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} position-fixed bottom-0 end-0 m-3`;
        notification.style.zIndex = '9999';
        notification.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'warning' ? 'exclamation-triangle' : 'info-circle'} me-2"></i>
            ${message}
        `;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 5000);
    }

    /**
     * Export functions for use in other scripts
     */
    window.ScoutingOfflineManager = {
        initialize: initializeOfflineCache,
        cacheData: cacheScoutingData,
        getCachedTeams: getCachedTeams,
        getCachedMatches: getCachedMatches,
        getCachedGameConfig: getCachedGameConfig,
        getCachedFormHTMLTemplate: getCachedFormHTMLTemplate,
        // Helpers for matching/filtering
        parseAllianceTeams: parseAllianceTeams,
        filterTeamsByMatchId: filterTeamsByMatchId,
        saveFormOffline: saveFormOffline,
        syncOfflineForms: syncOfflineForms,
        generateFormOffline: generateFormOffline,
        preCacheAllForms: preCacheAllForms,
        isOffline: () => !navigator.onLine,
        getPreCacheStatus: function() {
            const timestamp = localStorage.getItem('scouting_precache_timestamp');
            const hasTemplate = !!localStorage.getItem(CACHE_KEYS.FORM_HTML_TEMPLATE);
            return {
                cached: hasTemplate,
                timestamp: timestamp ? new Date(parseInt(timestamp)) : null,
                enabled: localStorage.getItem('scouting_precache_enabled') !== 'false'
            };
        },
        enablePreCache: function(enabled) {
            localStorage.setItem('scouting_precache_enabled', enabled ? 'true' : 'false');
            if (enabled && navigator.onLine) {
                preCacheAllForms();
            }
        }
    };

    // Auto-initialize on DOM load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeOfflineCache);
    } else {
        initializeOfflineCache();
    }

})();
