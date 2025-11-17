/* countup-site.js
   Lightweight visibility-based number animator.
   - Animates numeric-only elements when they become visible
   - Skips elements whose numeric value equals the configured season (window.GAME_CONFIG.season or year)
   - Marks elements once animated to avoid repeating
   - Fast, subtle animation suitable for dashboards
*/
(function(){
    'use strict';

    // Check user preference (localStorage) to see if countups are enabled.
    // Respect explicit 'false' string to disable. Default: enabled.
    function isCountupEnabled() {
        try {
            var v = localStorage.getItem('countup_enabled');
            if (v === 'false') return false;
        } catch (e) {
            // localStorage not available -> fall back to enabled
        }
        return true;
    }

    function parseNumberFromText(s){
        if(!s) return NaN;
        const cleaned = String(s).trim().replace(/[\u200B-\u200D\s,]/g,''); // remove whitespace, commas, zero-width
        if(cleaned === '') return NaN;
        // allow integers and decimals
        return isFinite(cleaned) ? Number(cleaned) : NaN;
    }

    function formatNumber(n, useGrouping){
        try{
            if (useGrouping) return new Intl.NumberFormat().format(n);
            return String(n);
        }catch(e){ return String(n); }
    }

    function easeOutQuad(t){ return t*(2-t); }

    function animateValue(el, start, end, duration, useGrouping){
        const startTime = performance.now();
        function step(now){
            const t = Math.min(1, (now - startTime) / duration);
            const eased = easeOutQuad(t);
            const cur = Math.round(start + (end - start) * eased);
            el.textContent = formatNumber(cur, useGrouping);
            if(t < 1) requestAnimationFrame(step);
            else el.textContent = formatNumber(end, useGrouping);
        }
        requestAnimationFrame(step);
    }

    function shouldAnimateElement(el){
        // skip elements that contain child elements (keep to pure text nodes)
        if(el.children && el.children.length) return false;
        // Don't animate team numbers or usernames: these are rendered with specific classes/attributes
        try{
            if (el.closest && el.closest('.team-number, [data-team-num], .user-name, .username')) return false;
            // Also skip if the element itself has explicit data attribute to opt-out
            if (el.dataset && (el.dataset.teamNum !== undefined || el.dataset.username !== undefined || el.dataset.countup === 'false')) return false;
            // Special-case: on the /users listing page we render usernames inside cards/links
            // Avoid animating any text that appears inside a user card or a user-profile link
            if (typeof window !== 'undefined' && window.location && String(window.location.pathname).startsWith('/users')) {
                // If this element is inside an anchor that links to a user profile (/users/<id>) skip it
                try{
                    const a = el.closest && el.closest('a[href]');
                    if (a && typeof a.getAttribute === 'function') {
                        const href = a.getAttribute('href') || '';
                        if (href.indexOf('/users/') !== -1 || href === '/users') return false;
                    }
                } catch(e) {}
                // Also skip elements that are common username containers on that page (e.g., .card-title)
                if (el.classList && el.classList.contains('card-title')) return false;
                if (el.closest && el.closest('.card') && el.tagName && el.tagName.toLowerCase().startsWith('h')) return false;
            }
        } catch(e) { /* ignore DOM exceptions */ }
        const txt = (el.textContent || '').trim();
        if(!txt) return false;
        const num = parseNumberFromText(txt);
        if(Number.isNaN(num)) return false;
        // Only animate numbers greater than 10 — very small numbers are fast enough
        // and animating them looks slow/jerky, so skip them.
        if (num <= 10) return false;
        return true;
    }

    function collectCandidates(){
        // Narrow set of tags to check for numbers (span/div/p/td/th/headings)
        const selector = ['span','div','p','strong','b','td','th','h1','h2','h3','h4','h5','h6'].join(',');
        return Array.from(document.querySelectorAll(selector)).filter(el => shouldAnimateElement(el));
    }

    function init(){
        if (!isCountupEnabled()) return;
        try{
            const seasonVal = (window.GAME_CONFIG && (window.GAME_CONFIG.season || window.GAME_CONFIG.year)) ? Number(window.GAME_CONFIG.season || window.GAME_CONFIG.year) : null;

            const candidates = collectCandidates();
            if(!candidates.length) return;

            const observer = new IntersectionObserver(function(entries){
                entries.forEach(entry => {
                    if(!entry.isIntersecting) return;
                    const el = entry.target;
                    if(el.dataset._countup_done) { observer.unobserve(el); return; }
                    const raw = (el.textContent || '').trim();
                    const value = parseNumberFromText(raw);
                    if(Number.isNaN(value)) { observer.unobserve(el); return; }
                    if(seasonVal !== null && !Number.isNaN(seasonVal) && value === seasonVal){
                        // Do not animate numbers equal to season
                        el.dataset._countup_done = '1';
                        observer.unobserve(el);
                        return;
                    }
                    if(value <= 0){
                        el.dataset._countup_done = '1';
                        observer.unobserve(el);
                        return;
                    }

                    // Don't animate small numbers — set them instantly for snappier UX
                    if (value <= 10) {
                        el.textContent = formatNumber(value, useGrouping);
                        el.dataset._countup_done = '1';
                        observer.unobserve(el);
                        return;
                    }

                    // Determine formatting (grouping) by presence of comma in original text
                    const useGrouping = /,/.test(raw);

                    // Apply a multiplier so the count-up is 2.5x slower (longer) than the original durations
                    const DURATION_MULTIPLIER = 2.5;
                    // Base durations (ms) depending on magnitude
                    const baseDuration = value < 1000 ? 420 : (value < 10000 ? 600 : 900);
                    const duration = Math.round(baseDuration * DURATION_MULTIPLIER);

                    // Start from 0 for dramatic effect unless element already shows a smaller number
                    const startFrom = 0;

                    animateValue(el, startFrom, value, duration, useGrouping);
                    el.dataset._countup_done = '1';
                    observer.unobserve(el);
                });
            }, { threshold: 0.45 });

            candidates.forEach(el => {
                try { observer.observe(el); } catch(e) { /* ignore */ }
            });
        }catch(e){ console.warn('countup-site init error', e); }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();

})();
