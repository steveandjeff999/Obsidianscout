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

            // Cache matches data
            const matchesSelect = document.getElementById('match-selector');
            if (matchesSelect) {
                const matches = Array.from(matchesSelect.options)
                    .filter(opt => opt.value)
                    .map(opt => ({
                        id: opt.value,
                        match_type: opt.getAttribute('data-match-type'),
                        match_number: opt.getAttribute('data-match-number'),
                        text: opt.textContent
                    }));
                
                localStorage.setItem(CACHE_KEYS.MATCHES, JSON.stringify(matches));
                console.log(`[Offline Manager] Cached ${matches.length} matches`);
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
