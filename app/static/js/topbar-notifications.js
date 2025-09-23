(function(){
    'use strict';

    const STORAGE_KEY = 'obsidian_dismissed_notifications_v1';

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
        list.innerHTML = '';
        if (!items || items.length === 0) {
            const el = document.createElement('div');
            el.className = 'list-group-item text-muted small';
            el.textContent = 'No notifications';
            list.appendChild(el);
            return;
        }

        items.forEach(n => {
            if (!n || !n.id) return;
            if (isDismissed(n.id)) return; // skip dismissed

            const item = document.createElement('div');
            item.className = 'list-group-item notification-item';

            const content = document.createElement('div');
            content.style.flex = '1';
            content.innerHTML = `<div class="fw-semibold">${escapeHtml(n.title || (n.message||'Notification'))}</div>
                                 <div class="notif-meta">${escapeHtml(n.message||'')}</div>`;

            const actions = document.createElement('div');
            actions.className = 'd-flex flex-column align-items-end';
            const dismissBtn = document.createElement('button');
            dismissBtn.className = 'notification-dismiss small';
            dismissBtn.title = 'Dismiss';
            dismissBtn.innerHTML = '<i class="fas fa-times"></i>';
            dismissBtn.addEventListener('click', function(e){
                e.preventDefault();
                markDismissed(n.id);
                item.remove();
                // update badge
                updateBadgeFromList();
            });

            actions.appendChild(dismissBtn);
            item.appendChild(content);
            item.appendChild(actions);
            list.appendChild(item);
        });

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
            // Fallback: fetch chat unread state and show count only
            const state = await fetchChatState();
            if (state && typeof state.unreadCount !== 'undefined') {
                const unread = state.unreadCount || 0;
                // create a simple notification entry for unread chats when present
                const entries = [];
                if (unread > 0) entries.push({ id: 'chat-unread', title: `You have ${unread} unread chat message(s)`, message: 'Open chat to view messages' });
                renderNotifications(entries);
            } else {
                renderNotifications([]);
            }
        }

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
                        // Add a simple entry for chat unread and re-render
                        const list = document.getElementById('notificationsList');
                        if (!list) return;
                        // If a chat-unread entry exists, update its text
                        const existing = list.querySelector('.notification-item[data-source="chat"]');
                        if (existing) {
                            // noop: increment handled by server poll; keep simple
                        } else {
                            const entry = { id: 'chat-unread', title: `New chat message from ${msg.sender || 'someone'}`, message: msg.text || '' };
                            // prepend
                            renderNotifications([entry].concat(Array.from(list.children).map(ch => {
                                return { id: ch.getAttribute && ch.getAttribute('data-notif-id') || Math.random().toString(36).slice(2), title: ch.querySelector('.fw-semibold') ? ch.querySelector('.fw-semibold').textContent : '', message: ch.querySelector('.notif-meta') ? ch.querySelector('.notif-meta').textContent : '' };
                            })));
                        }
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
                // if dropdown becomes visible, refresh
                setTimeout(async function(){
                    const menu = document.getElementById('notificationsMenu');
                    if (!menu) return;
                    if (menu.classList.contains('show')) {
                        // Re-fetch server state and site notifications (if available via endpoint)
                        try {
                            // Try server endpoint for structured notifications if provided
                            const resp = await fetch('/notifications/recent');
                            if (resp.ok) {
                                const data = await resp.json();
                                if (Array.isArray(data.notifications)) {
                                    renderNotifications(data.notifications.map(n => ({ id: n.id, title: n.title || n.level || 'Notice', message: n.message || '' })));
                                    return;
                                }
                            }
                        } catch(e){}
                        // Fallback: poll chat state
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
