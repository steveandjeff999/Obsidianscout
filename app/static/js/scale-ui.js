// Scale UI widget: adjusts --ui-scale and html font-size via data attribute
(function(){
    const STORAGE_KEY = 'obsidian_ui_scale_v1';
    const MIN = 0.8;
    const MAX = 1.6;
    const STEP = 0.05;

    function createWidget() {
        // Avoid adding multiple widgets
        if (document.getElementById('scaleUiWidget')) return null;

        const widget = document.createElement('div');
        widget.id = 'scaleUiWidget';
        widget.className = 'scale-ui-widget';
        widget.setAttribute('role','region');
        widget.setAttribute('aria-label','UI scale control');

        widget.innerHTML = `
            <span class="scale-icon"><i class="fas fa-text-height" aria-hidden="true"></i></span>
            <span class="scale-label">Size</span>
            <input type="range" min="${MIN}" max="${MAX}" step="${STEP}" value="1" id="scaleUiRange" aria-label="Resize UI scale">
            <button id="scaleUiReset" class="btn btn-sm btn-outline-secondary" title="Reset scale">Reset</button>
        `;

        document.body.appendChild(widget);
        if (window.__scaleUiDebug) console.debug('scale-ui: widget created');
        return widget;
    }

    // Apply scale to the nearest .card ancestor of each .counter-container
    let __currentScale = 1;
    function ensureOriginalSize(el) {
        // Store original width/height (without transforms) for spacing calculations
        if (el.dataset.origHeight && el.dataset.origWidth) return;
        const prev = el.style.transform || '';
        try {
            // Temporarily remove transform to measure natural size
            el.style.transform = 'none';
            const r = el.getBoundingClientRect();
            el.dataset.origHeight = String(r.height);
            el.dataset.origWidth = String(r.width);
        } catch (e) {
            // ignore measurement errors
        } finally {
            el.style.transform = prev;
        }
    }

    function clearSpacing(el) {
        el.style.marginBottom = '';
        el.style.marginRight = '';
    }

    function applyScale(scale) {
        // clamp
        scale = Math.max(MIN, Math.min(MAX, Number(scale)));
        if (window.__scaleUiDebug) console.debug('scale-ui: applyScale start', scale);
        try {
            // Find all counter containers and their nearest .card parent
            const counters = Array.from(document.querySelectorAll('.counter-container'));
            const cards = new Set();

            counters.forEach(c => {
                const card = c.closest('.card');
                if (card) cards.add(card);
                else {
                    // If no card ancestor, scale the counter itself
                    cards.add(c);
                }
            });

            // Apply transform only to the counter element (.counter-container) and add padding-bottom to the card header
            cards.forEach(el => {
                const card = el.classList.contains('card') ? el : el.closest('.card');
                const counter = el.classList && el.classList.contains('counter-container') ? el : (card ? card.querySelector('.counter-container') : el);
                if (!counter) return; // nothing to scale here

                const header = card ? (card.querySelector('.card-header') || counter.parentElement) : counter.parentElement;

                // add helper class on card for styling if card exists
                if (card) card.classList.add('scale-target-card');

                // Ensure we have original measurements for counter
                ensureOriginalSize(counter);

                // Freeze layout width so transform doesn't change flow (prevents card expansion)
                try {
                    const origW = Number(counter.dataset.origWidth || 0);
                    if (origW > 0) {
                        // Keep the counter as a flex container so children (buttons + input)
                        // remain side-by-side. Previously we set inline-block which broke
                        // the flex layout and caused vertical stacking when scaled.
                        counter.style.boxSizing = 'border-box';
                        try {
                            const cs = window.getComputedStyle(counter);
                            if (!counter.style.display) counter.style.display = cs.display || 'flex';
                        } catch (e) {
                            // fallback to flex if computed style fails
                            if (!counter.style.display) counter.style.display = 'flex';
                        }
                        counter.style.width = origW + 'px';
                        counter.style.maxWidth = origW + 'px';
                        // Ensure children don't wrap into multiple lines when space is tight
                        counter.style.flexWrap = 'nowrap';
                    }
                } catch (e) { /* ignore */ }

                // Apply transform to the counter (visual only)
                counter.style.transformOrigin = counter.style.transformOrigin || 'left top';
                counter.style.willChange = 'transform';
                counter.style.transition = 'transform 120ms ease, margin 120ms ease';
                counter.style.transform = `scale(${scale})`;

                // After transform is applied, compute height delta and add padding-bottom to header to keep things from overlapping.
                try {
                    const origH = Number(counter.dataset.origHeight || 0);
                    window.requestAnimationFrame(() => {
                        const newRect = counter.getBoundingClientRect();
                        const deltaH = newRect.height - origH;

                        if (header) {
                            // store original padding-bottom if not stored
                            if (!header.dataset.origPaddingBottom) {
                                const cs = window.getComputedStyle(header);
                                header.dataset.origPaddingBottom = cs.paddingBottom || '0px';
                            }
                            const origPad = parseFloat(header.dataset.origPaddingBottom) || 0;
                            if (deltaH > 1) {
                                header.style.paddingBottom = (origPad + deltaH + 6) + 'px';
                            } else {
                                header.style.paddingBottom = header.dataset.origPaddingBottom || '';
                            }
                        } else {
                            // fallback: add margin-bottom to counter itself
                            if (deltaH > 2) counter.style.marginBottom = (deltaH + 8) + 'px'; else counter.style.marginBottom = '';
                        }
                    });
                } catch (e) { console.warn('Counter spacing calc failed', e); }

                // keep a data attribute at card level
                if (card) card.setAttribute('data-ui-scale', String(scale)); else counter.setAttribute('data-ui-scale', String(scale));
            });

            // Add helper class on body for large scales (if needed for extra spacing)
            if (scale > 1.25) document.body.classList.add('scale-lg'); else document.body.classList.remove('scale-lg');
        } catch (e) { console.warn('Could not apply UI scale to cards', e); }
        __currentScale = scale;
        if (window.__scaleUiDebug) console.debug('scale-ui: applyScale done', __currentScale);
    }

    // Adjust the grid min column width dynamically between a small and large value
    // based on the UI scale. When scale is MIN -> use 160px, when scale is MAX -> use 300px.
    // Made very small to fit mobile phones properly.
    function updateGridMinForScale(scale) {
        try {
            const minPx = 160;  // Very small for tight mobile fit
            const maxPx = 300;  // Reduced max for better mobile experience
            const t = (scale - MIN) / (MAX - MIN);
            const val = Math.round(minPx + (maxPx - minPx) * t);
            document.documentElement.style.setProperty('--scale-card-min', val + 'px');
            if (window.__scaleUiDebug) console.debug('scale-ui: updateGridMinForScale set', val+'px');
        } catch (e) { /* ignore */ }
    }

    // Compute explicit column count based on viewport width and scale.
    // Adjusted for mobile: 2 columns at 400px+ (was 600px+)
    // When scale is large, reduce columns to accommodate bigger cards.
    function computeColumnsForViewport(scale) {
        try {
            if (window.__scaleUiDebug) console.debug('scale-ui: computeColumnsForViewport (start) width=', window.innerWidth, 'scale=', scale);
            const w = window.innerWidth || document.documentElement.clientWidth || 0;
            let cols = 1;
            if (w >= 1600) cols = 5;
            else if (w >= 1200) cols = 4;
            else if (w >= 900) cols = 3;
            else if (w >= 400) cols = 2;  // Changed from 600 to 400 for mobile
            else cols = 1;

            // Reduce columns when scale gets large to accommodate bigger cards
            // At scale 1.2+, reduce by 1 column (max scale is 1.6)
            // At scale 1.4+, reduce by 2 columns
            if (scale >= 1.4) {
                cols = Math.max(1, cols - 2);
            } else if (scale >= 1.2) {
                cols = Math.max(1, cols - 1);
            }

            document.documentElement.style.setProperty('--scale-card-columns', String(Math.max(1, cols)));
            if (window.__scaleUiDebug) console.debug('scale-ui: computeColumnsForViewport set cols=', cols, 'after scale adjustment for scale=', scale);
        } catch (e) { /* ignore */ }
    }

    function loadStored() {
        try {
            const v = localStorage.getItem(STORAGE_KEY);
            return v ? Number(v) : null;
        } catch (e) { return null; }
    }

    function store(scale) {
        try { localStorage.setItem(STORAGE_KEY, String(scale)); } catch (e) {}
    }

    function init() {
        if (!document.body) return; // not ready

        const widget = createWidget();
        if (!widget) return;

        // Create responsive card grids: group siblings of .card into a container that uses min 400px columns
        function createCardGrids(){
            // Instead of moving nodes (which other scripts may undo), mark the
            // row parent with a class to make it a CSS grid in-place. This is
            // less intrusive and survives other scripts rearranging children.

            const allCards = Array.from(document.querySelectorAll('main .card, .container .card'));
            const parents = new Map();
            allCards.forEach(card => {
                // Find the nearest ancestor with a Bootstrap column class (class contains 'col-')
                let col = card.closest('[class*="col-"]');
                if (!col) col = card.parentElement; // fallback to direct parent
                if (!col || !col.parentElement) return;
                const rowParent = col.parentElement;
                if (!parents.has(rowParent)) parents.set(rowParent, new Set());
                parents.get(rowParent).add(col);
            });

            parents.forEach((colsSet, parent) => {
                const cols = Array.from(colsSet);
                if (cols.length < 2) return; // only group when helpful

                // If the parent is already marked as a grid, ensure children are marked and continue
                if (!parent.classList.contains('scale-card-grid-parent')) {
                    parent.classList.add('scale-card-grid-parent');
                }

                // Mark the column elements so CSS can reset Bootstrap widths inside the grid
                cols.forEach(c => c.classList.add('scale-card-col'));
            });
        }
    createCardGrids();
    if (window.__scaleUiDebug) console.debug('scale-ui: createCardGrids initial pass done');

        // Stabilizer: some other scripts (e.g., scripts.js) perform DOM updates
        // shortly after load which can remove/move our wrappers. Run a repeated
        // pass to ensure the grid wrapping and column count settle. Increase
        // duration to cover delayed script failures or reflows.
        // Stabilizer: run until DOM is idle (no mutations for idlePeriod) or
        // until maxRuns reached. This is more robust for pages where other
        // scripts continue to mutate the DOM after load.
        if (!window.__scaleGridStabilizer) {
            let runs = 0;
            const intervalMs = 200;
            const idlePeriod = 1000; // consider DOM idle after 1s with no mutations
            const maxDurationMs = 30000; // bail out after 30s
            let lastMutationAt = Date.now();

            // Helper to touch the lastMutationAt (used by mutation observer below)
            function noteMutation() { lastMutationAt = Date.now(); }

            // initial note so stabilizer doesn't stop immediately
            noteMutation();

            window.__scaleGridStabilizer = setInterval(() => {
                try {
                    if (window.__scaleUiDebug) console.debug('scale-ui: stabilizer run', runs, 'lastMutationAt=', lastMutationAt);
                    createCardGrids();
                    computeColumnsForViewport(__currentScale);
                    // also ensure spacing and scale are re-applied
                    recomputeSpacing();
                    applyScale(__currentScale);
                } catch (e) { if (window.__scaleUiDebug) console.debug('scale-ui: stabilizer error', e); }
                runs += 1;

                // Stop if we've seen no mutations for idlePeriod and we've run at least a few times
                const now = Date.now();
                if (runs > 3 && (now - lastMutationAt) > idlePeriod) {
                    clearInterval(window.__scaleGridStabilizer);
                    window.__scaleGridStabilizer = null;
                    if (window.__scaleUiDebug) console.debug('scale-ui: stabilizer stopped (idle) after', runs, 'runs');
                }

                // Stop if we've exceeded maxDurationMs
                if ((now - lastMutationAt) > maxDurationMs) {
                    clearInterval(window.__scaleGridStabilizer);
                    window.__scaleGridStabilizer = null;
                    if (window.__scaleUiDebug) console.debug('scale-ui: stabilizer stopped (timeout) after', runs, 'runs');
                }
            }, intervalMs);

            // expose noteMutation so MutationObserver can call it
            window.__scaleUiNoteMutation = noteMutation;
        }

        // Re-run grouping when DOM changes (use a MutationObserver with debounce)
        const gridObserver = new MutationObserver((mutationsList) => {
            // record that a mutation occurred so stabilizer stays alive
            try { if (window.__scaleUiNoteMutation) window.__scaleUiNoteMutation(); } catch(e){}

            // Use a short debounce so we react quickly to DOM changes performed
            // by other scripts but still avoid thrashing.
            clearTimeout(window.__scaleGridDebounce);
            window.__scaleGridDebounce = setTimeout(() => {
                try {
                    if (window.__scaleUiDebug) console.debug('scale-ui: mutation observed, reapplying grid, mutations=', mutationsList.length);
                    createCardGrids();
                    computeColumnsForViewport(__currentScale);
                    // Re-apply spacing and transforms after structural changes
                    recomputeSpacing();
                    applyScale(__currentScale);
                } catch(e){ if (window.__scaleUiDebug) console.debug('scale-ui: mutation handler error', e); }
            }, 75);
        });
        gridObserver.observe(document.body, { childList: true, subtree: true });

        // Also reflow grids on resize
        let gridResizeTimer = null;
        window.addEventListener('resize', () => { clearTimeout(gridResizeTimer); gridResizeTimer = setTimeout(createCardGrids, 200); });

        const range = document.getElementById('scaleUiRange');
        const reset = document.getElementById('scaleUiReset');

        // Load stored value
        const stored = loadStored();
        const initial = stored || 1;
        range.value = initial;
    applyScale(initial);
    updateGridMinForScale(initial);
    computeColumnsForViewport(initial);

        range.addEventListener('input', (e)=>{
            const v = e.target.value;
            applyScale(v);
            updateGridMinForScale(Number(v));
            computeColumnsForViewport(Number(v));
        });

        range.addEventListener('change', (e)=>{
            const v = e.target.value;
            store(v);
        });

        reset.addEventListener('click', (e)=>{
            e.preventDefault();
            const def = 1;
            range.value = def;
            applyScale(def);
            store(def);
            updateGridMinForScale(def);
            computeColumnsForViewport(def);
        });
        // Clear spacing and attributes on reset
        reset.addEventListener('click', function(){
            const cards = Array.from(document.querySelectorAll('.scale-target-card'));
            cards.forEach(card => {
                // clear only inline visual transforms and spacing, keep grid/parent classes
                card.style.transform = '';
                card.style.marginBottom = '';
                card.style.marginRight = '';
                card.removeAttribute('data-ui-scale');

                const counter = card.querySelector('.counter-container');
                if (counter) {
                    counter.style.transform = '';
                    counter.style.marginBottom = '';
                    counter.style.width = '';
                    counter.style.maxWidth = '';
                    counter.style.display = '';
                    counter.style.boxSizing = '';
                    counter.style.flexWrap = '';
                }

                const header = card.querySelector('.card-header');
                if (header) {
                    header.style.paddingBottom = header.dataset.origPaddingBottom || '';
                }
            });
            // Also clear stored value so next session is default
            try { localStorage.removeItem(STORAGE_KEY); } catch(e){}
        });

        // Recompute spacing for current scale (useful after layout changes)
        function recomputeSpacing() {
            const cards = Array.from(document.querySelectorAll('.scale-target-card'));
            cards.forEach(card => {
                const counter = card.querySelector('.counter-container');
                if (!counter) return;
                if (!counter.dataset.origHeight) ensureOriginalSize(counter);
                const origH = Number(counter.dataset.origHeight || 0);
                try {
                    const r = counter.getBoundingClientRect();
                    const deltaH = r.height - origH;
                    const header = card.querySelector('.card-header');
                    if (header) {
                        if (!header.dataset.origPaddingBottom) {
                            const cs = window.getComputedStyle(header);
                            header.dataset.origPaddingBottom = cs.paddingBottom || '0px';
                        }
                        const origPad = parseFloat(header.dataset.origPaddingBottom) || 0;
                        if (deltaH > 1) {
                            header.style.paddingBottom = (origPad + deltaH + 6) + 'px';
                        } else {
                            header.style.paddingBottom = header.dataset.origPaddingBottom || '';
                        }
                    } else {
                        if (deltaH > 2) counter.style.marginBottom = (deltaH + 8) + 'px'; else counter.style.marginBottom = '';
                    }
                } catch (e) {}
            });
        }

        // Recompute when window resized or when layout might change
        let resizeTimer = null;
        window.addEventListener('resize', function() {
            if (resizeTimer) clearTimeout(resizeTimer);
            resizeTimer = setTimeout(function(){ 
                recomputeSpacing(); 
                computeColumnsForViewport(__currentScale); 
            }, 150);
        });

        // Also recompute after images/fonts load which might affect layout
        window.addEventListener('load', function() { setTimeout(recomputeSpacing, 50); });

        // Accessibility: keyboard support
        range.addEventListener('keydown', (e)=>{
            let v = Number(range.value);
            if (e.key === 'ArrowRight' || e.key === 'ArrowUp') { v = Math.min(MAX, v + STEP); range.value = v; applyScale(v); store(v); e.preventDefault(); }
            if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') { v = Math.max(MIN, v - STEP); range.value = v; applyScale(v); store(v); e.preventDefault(); }
            if (e.key === 'Home') { range.value = MIN; applyScale(MIN); store(MIN); e.preventDefault(); }
            if (e.key === 'End') { range.value = MAX; applyScale(MAX); store(MAX); e.preventDefault(); }
        });

        // Hide widget on very small screens if space is tight (allow user to toggle later)
        function adaptVisibility(){
            if (window.innerWidth < 420) {
                widget.style.bottom = '74px'; // move up to avoid overlapping action buttons
            } else {
                widget.style.bottom = '12px';
            }
        }
        adaptVisibility();
        window.addEventListener('resize', adaptVisibility);
    }

    // Initialize after DOM ready
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
