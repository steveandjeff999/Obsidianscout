document.addEventListener('DOMContentLoaded', function() {
  const wrapper = document.getElementById('site-notification-wrapper');
  if (!wrapper) return;

  // Helper to adjust main padding so the banner doesn't overlap sticky navbar/content
  function adjustMainPadding() {
    const main = document.querySelector('main');
    if (!main) return;
    // total visible banner height
    const visible = Array.from(wrapper.querySelectorAll('.site-notification')).reduce((sum, el) => sum + el.offsetHeight, 0);
    // keep navbar padding (main has 70px for navbar); add visible banner height
    main.style.paddingTop = (70 + visible) + 'px';
  }

  // Initial adjust
  adjustMainPadding();

  wrapper.addEventListener('click', function(e) {
    const btn = e.target.closest('[data-notif-id]');
    if (!btn) return;
    const id = btn.getAttribute('data-notif-id');
    // Remove visually
    const alertEl = btn.closest('.site-notification');
    if (alertEl) {
  // animate then remove
  alertEl.classList.remove('show');
  alertEl.style.transition = 'height 220ms ease, opacity 220ms ease, margin 220ms ease, padding 220ms ease';
  alertEl.style.height = alertEl.offsetHeight + 'px';
  // force reflow
  void alertEl.offsetHeight;
  alertEl.style.opacity = '0';
  alertEl.style.padding = '0';
  alertEl.style.margin = '0';
  alertEl.style.height = '0';
  setTimeout(() => { alertEl.remove(); adjustMainPadding(); }, 230);
    }
    // Persist dismissal in localStorage so user won't see it again in this browser
    try {
      let dismissed = JSON.parse(localStorage.getItem('dismissed_notifications') || '[]');
      if (!dismissed.includes(id)) dismissed.push(id);
      localStorage.setItem('dismissed_notifications', JSON.stringify(dismissed));
    } catch (e) {}

    // Also try to persist dismissal server-side for logged-in users (best-effort)
    try {
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
      fetch('/auth/notifications/dismiss', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json', 
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken
        },
        credentials: 'same-origin',
        body: JSON.stringify({notif_id: id})
      }).catch(()=>{});
    } catch (e) {}
  });

  // On load, hide any dismissed by this browser
  // On load, hide any dismissed by this browser
  try {
    let dismissed = JSON.parse(localStorage.getItem('dismissed_notifications') || '[]');
    if (dismissed && dismissed.length) {
      dismissed.forEach(id => {
        const el = wrapper.querySelector('[data-notif-id="' + id + '"]');
        if (el) {
      const parent = el.closest('.site-notification');
      if (parent) parent.remove();
        }
      });
    // after removing dismissed, adjust layout
    adjustMainPadding();
    }
  } catch (e) {}
  
  // Best-effort: fetch server-side dismissals for the logged-in user and hide those too
  try {
    fetch('/auth/notifications/dismissed', {headers:{'X-Requested-With':'XMLHttpRequest'}})
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!data || !data.dismissed) return;
        data.dismissed.forEach(id => {
          const el = wrapper.querySelector('[data-notif-id="' + id + '"]');
          if (el) {
            const parent = el.closest('.site-notification');
            if (parent) parent.remove();
          }
        });
        adjustMainPadding();
      }).catch(()=>{});
  } catch(e) {}
});
