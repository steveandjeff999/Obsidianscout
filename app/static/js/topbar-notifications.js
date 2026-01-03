(function(){
    'use strict';

    const STORAGE_KEY = 'obsidian_dismissed_notifications_v1';

    // In-memory cache of fetched notifications to avoid waiting on network when
    // user opens the dropdown. Cached for the page lifetime; can be invalidated
    // by calling fetchRecentNotifications(true).
    let notificationsCache = null;
    let notificationsCacheAt = 0; // timestamp ms
    const NOTIFICATIONS_CACHE_TTL = 1000 * 60; // 60s

    function loadDismissed() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); } catch(e) { return []; }
    }
    function saveDismissed(arr){ try { localStorage.setItem(STORAGE_KEY, JSON.stringify(arr)); } catch(e){} }

    function markDismissed(id){
        const arr = loadDismissed();
        if (!arr.includes(id)) arr.push(id);
        saveDismissed(arr);
    }

    function isDismissed(id){
        const arr = loadDismissed();
        return arr.includes(id);
    }

    function setBadge(count){
        const badge = document.getElementById('notificationsBadge');
        if (!badge) return;
        if (!count || count <= 0) {
            badge.style.display = 'none';
            badge.textContent = '';
        } else {
            badge.style.display = '';
            badge.textContent = count > 99 ? '99+' : String(count);
        }
    }

    async function fetchChatState(){
        try {
            const resp = await fetch('/chat/state');
            if (!resp.ok) return null;
            return await resp.json();
        } catch(e){ return null; }
    }

    function renderNotifications(items){
        const list = document.getElementById('notificationsList');
        if (!list) return;
        // Batch DOM updates with a fragment to reduce layout thrashing
        list.innerHTML = '';
        const frag = document.createDocumentFragment();
        // Limit rendering to a reasonable number to avoid heavy work on slow devices
        const MAX_RENDER = 25;
        let rendered = 0;
        if (!items || items.length === 0) {
            const el = document.createElement('div');
            el.className = 'list-group-item text-muted small';
            el.textContent = 'No notifications';
            frag.appendChild(el);
            list.appendChild(frag);
            return;
        }
        for (let i = 0; i < items.length && rendered < MAX_RENDER; i++) {
            const n = items[i];
            if (!n || !n.id) continue;
            if (isDismissed(n.id)) continue; // skip dismissed

            rendered += 1;
            const item = document.createElement('div');
            item.className = 'list-group-item notification-item';
            item.setAttribute('data-notif-id', n.id);
            // Mark chat-derived entries so socket handler can find/update them
            try {
                if (String(n.id || '').toLowerCase().startsWith('chat')) {
                    item.setAttribute('data-source', 'chat');
                }
            } catch(e) {}

            const content = document.createElement('div');
            content.style.flex = '1';
            // Use text nodes where possible to avoid re-parsing HTML
            const titleDiv = document.createElement('div');
            titleDiv.className = 'fw-semibold';
            titleDiv.textContent = n.title || (n.message || 'Notification');
            const metaDiv = document.createElement('div');
            // Start clamped to two lines; an expand button will toggle the parent's `expanded` class
            metaDiv.className = 'notif-meta clamp-2';
            metaDiv.textContent = n.message || '';

            content.appendChild(titleDiv);
            content.appendChild(metaDiv);

            // Expand / collapse control (hidden unless message overflows)
            const expandBtn = document.createElement('button');
            expandBtn.className = 'notification-expand small';
            expandBtn.type = 'button';
            expandBtn.style.display = 'none';
            expandBtn.textContent = 'More';
            expandBtn.setAttribute('aria-expanded','false');
            expandBtn.addEventListener('click', function(e){
                e.preventDefault();
                const nowExpanded = item.classList.toggle('expanded');
                expandBtn.textContent = nowExpanded ? 'Less' : 'More';
                expandBtn.setAttribute('aria-expanded', nowExpanded ? 'true' : 'false');
                if (nowExpanded) item.setAttribute('aria-expanded','true'); else item.removeAttribute('aria-expanded');
            });
            content.appendChild(expandBtn);

            const actions = document.createElement('div');
            actions.className = 'd-flex flex-column align-items-end';
            const dismissBtn = document.createElement('button');
            dismissBtn.className = 'notification-dismiss small';
            dismissBtn.title = 'Dismiss';
            dismissBtn.innerHTML = '<i class="fas fa-times"></i>';
            dismissBtn.addEventListener('click', function(e){
                e.preventDefault();
                markDismissed(n.id);
                if (item && item.parentNode) item.parentNode.removeChild(item);
                // update badge
                updateBadgeFromList();
            });

            actions.appendChild(dismissBtn);
            item.appendChild(content);
            item.appendChild(actions);
            frag.appendChild(item);
        }

        // If there were more items than we rendered, add a small footer line
        if (items.length > MAX_RENDER) {
            const more = document.createElement('div');
            more.className = 'list-group-item small text-muted text-center';
            more.textContent = `Showing ${MAX_RENDER} of ${items.length} notifications`;
            frag.appendChild(more);
        }

        list.appendChild(frag);

        // Detect overflowed messages and show expand buttons where needed
        try {
            Array.from(list.querySelectorAll('.notification-item')).forEach(el => {
                const meta = el.querySelector('.notif-meta');
                const btn = el.querySelector('.notification-expand');
                if (!meta || !btn) return;
                // If the content is taller than the clamped height, show the toggle
                if (meta.scrollHeight > meta.clientHeight + 1) {
                    btn.style.display = '';
                } else {
                    btn.style.display = 'none';
                }
            });
        } catch(e) { /* ignore measurement errors */ }

        updateBadgeFromList();
    }

    function updateBadgeFromList(){
        const list = document.getElementById('notificationsList');
        if (!list) return setBadge(0);
        const count = Array.from(list.children).filter(ch => ch.classList && ch.classList.contains('notification-item')).length;
        setBadge(count);
    }

    function escapeHtml(text){
        const d = document.createElement('div'); d.textContent = text || ''; return d.innerHTML;
    }

    // Load initial notifications from server-provided site_notifications (if present on page)
    function loadSiteNotificationsFromDOM(){
        try {
            // Some pages may include site notifications in a global variable; try to read it
            if (window.site_notifications && Array.isArray(window.site_notifications)) {
                return window.site_notifications;
            }
        } catch(e){}
        return null;
    }

    async function init(){
        const siteNotes = loadSiteNotificationsFromDOM();
        if (siteNotes) {
            // Normalize to simple objects
            const mapped = siteNotes.map(n => ({ id: n.id || ('site-'+(n.level||'')+'-'+(n.message||'').slice(0,12)), title: n.level ? (n.level.toUpperCase()) : 'Notice', message: n.message || '' }));
            renderNotifications(mapped);
        } else {
            // Show immediate lightweight chat-unread entry while we background-fetch the full list
            const state = await fetchChatState();
            if (state && typeof state.unreadCount !== 'undefined') {
                const unread = state.unreadCount || 0;
                const entries = [];
                if (unread > 0) entries.push({ id: 'chat-unread', title: `You have ${unread} unread chat message(s)`, message: 'Open chat to view messages' });
                renderNotifications(entries);
            } else {
                // keep the Loading... placeholder until background fetch completes
            }
        }

        // Start a background preload of notifications so opening the dropdown is instant
        // Do not await here; populate notificationsCache when available.
        (async function preloadNotifications(){
            try {
                const resp = await fetch('/notifications/recent');
                if (!resp.ok) return;
                const data = await resp.json();
                if (Array.isArray(data.notifications)) {
                    notificationsCache = data.notifications.map(n => ({ id: n.id, title: n.title || n.level || 'Notice', message: n.message || '' }));
                    notificationsCacheAt = Date.now();
                    // If the current displayed list is still Loading... or empty, render now
                    const list = document.getElementById('notificationsList');
                    if (list && list.textContent && list.textContent.trim() === 'Loading...') {
                        renderNotifications(notificationsCache);
                    }
                }
            } catch(e){ /* ignore preload errors */ }
        })();

        // Wire clear all button
        const clearBtn = document.getElementById('clearAllNotificationsBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', function(e){
                e.preventDefault();
                // mark all as dismissed
                const list = document.getElementById('notificationsList');
                if (!list) return;
                Array.from(list.querySelectorAll('[data-notif-id]')).forEach(el => {
                    const id = el.getAttribute('data-notif-id'); if (id) markDismissed(id);
                });
                // fallback: mark all existing items
                Array.from(list.children).forEach(ch => {
                    const id = ch.getAttribute && ch.getAttribute('data-notif-id');
                    if (id) markDismissed(id);
                });
                list.innerHTML = '<div class="list-group-item text-muted small">No notifications</div>';
                setBadge(0);
            });
        }

        // If socket.io exists, listen for chat events to update badge
        if (window.socket) {
            window.socket.on('dm_message', function(msg){
                // If not on chat page, increment unread indicator
                if (!window.location.pathname.startsWith('/chat')) {
                    try {
                        const list = document.getElementById('notificationsList');
                        if (!list) return;

                        // Try to find an existing chat entry and update it in-place
                        const existing = list.querySelector('.notification-item[data-source="chat"]');
                        if (existing) {
                            try {
                                const titleEl = existing.querySelector('.fw-semibold');
                                const metaEl = existing.querySelector('.notif-meta');
                                if (titleEl) titleEl.textContent = `New chat message from ${msg.sender || 'someone'}`;
                                if (metaEl) metaEl.textContent = msg.text || '';
                            } catch(e) {}
                        } else {
                            const entry = { id: 'chat-unread', title: `New chat message from ${msg.sender || 'someone'}`, message: msg.text || '' };
                            // prepend
                            renderNotifications([entry].concat(Array.from(list.children).map(ch => {
                                return { id: ch.getAttribute && ch.getAttribute('data-notif-id') || Math.random().toString(36).slice(2), title: ch.querySelector('.fw-semibold') ? ch.querySelector('.fw-semibold').textContent : '', message: ch.querySelector('.notif-meta') ? ch.querySelector('.notif-meta').textContent : '' };
                            })));
                        }

                        // Optimistically increment visible badge for immediate feedback
                        try {
                            const badge = document.getElementById('notificationsBadge');
                            if (badge) {
                                let cur = 0;
                                const txt = badge.textContent && badge.textContent.trim();
                                if (txt) {
                                    if (txt === '99+') cur = 99;
                                    else cur = parseInt(txt.replace(/[^0-9]/g, '')) || 0;
                                }
                                setBadge(cur + 1);
                            }
                        } catch(e) {}

                        // Also update chat unread badge if backend supports /chat/state
                        fetchChatState().then(state => { if (state && typeof state.unreadCount !== 'undefined') setBadge(state.unreadCount); });
                    } catch(e){}
                }
            });
        }

        // Periodically poll for chat state to keep badge in sync
        setInterval(async function(){
            const state = await fetchChatState();
            if (state && typeof state.unreadCount !== 'undefined') {
                setBadge(state.unreadCount || 0);
            }
        }, 10000);

        // Show menu when opened: refresh content
        const toggle = document.getElementById('notificationsToggle');
        if (toggle) {
            toggle.addEventListener('click', async function(){
                // if dropdown becomes visible, refresh quickly using cached data if available
                setTimeout(async function(){
                    const menu = document.getElementById('notificationsMenu');
                    if (!menu) return;
                    if (menu.classList.contains('show')) {
                        try {
                            // Prefer cached notifications when available and fresh
                            const now = Date.now();
                            if (notificationsCache && (now - notificationsCacheAt) < NOTIFICATIONS_CACHE_TTL) {
                                renderNotifications(notificationsCache);
                                // Also refresh chat unread badge in background
                                fetchChatState().then(state => { if (state && typeof state.unreadCount !== 'undefined') setBadge(state.unreadCount); });
                                return;
                            }

                            // Try server endpoint for structured notifications
                            const resp = await fetch('/notifications/recent');
                            if (resp.ok) {
                                const data = await resp.json();
                                if (Array.isArray(data.notifications)) {
                                    notificationsCache = data.notifications.map(n => ({ id: n.id, title: n.title || n.level || 'Notice', message: n.message || '' }));
                                    notificationsCacheAt = Date.now();
                                    renderNotifications(notificationsCache);
                                    return;
                                }
                            }
                        } catch(e){}
                        // Fallback: poll chat state if nothing else
                        const state = await fetchChatState();
                        if (state && typeof state.unreadCount !== 'undefined') {
                            const entries = [];
                            if (state.unreadCount > 0) entries.push({ id: 'chat-unread', title: `You have ${state.unreadCount} unread chat message(s)`, message: 'Open chat to view messages' });
                            renderNotifications(entries);
                        }
                    }
                }, 50);
            });
        }
    }

    // Init on DOM ready
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
