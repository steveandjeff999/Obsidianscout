document.addEventListener('DOMContentLoaded', function() {
  const runBtn = document.getElementById('run-sim');
  const redHiddenSelect = document.getElementById('red_teams');
  const blueHiddenSelect = document.getElementById('blue_teams');
  // Note: n-sim and seed controls removed from UI intentionally; server uses defaults
  const eventSelect = document.getElementById('event-select');
  const resultsDiv = document.getElementById('sim-results');

  function getSelectedValuesFromHidden(hidden) {
    return Array.from(hidden.options).filter(o => o.selected).map(o => o.value);
  }

  function initAllianceSelector(prefix, hiddenSelect) {
    const searchInput = document.getElementById('team-search-input-' + prefix);
    const clearSearchBtn = document.getElementById('clear-search-' + prefix);
    const selectAllBtn = document.getElementById('select-all-' + prefix);
    const clearBtn = document.getElementById('clear-' + prefix);
    const pillsContainer = document.getElementById('selected-pills-' + prefix);
    const listContainer = document.getElementById('team-list-items-' + prefix);
    if (!listContainer) return;

    // Populate hidden select options if empty
    if (hiddenSelect && hiddenSelect.options.length === 0 && Array.isArray(allTeamsData)) {
      allTeamsData.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.teamNumber;
        opt.text = t.displayText;
        hiddenSelect.appendChild(opt);
      });
    }

    // Checkbox change handling
    listContainer.querySelectorAll('.team-checkbox').forEach(cb => {
      cb.addEventListener('change', function() {
        // Enforce max per alliance
        const checkedCount = Array.from(listContainer.querySelectorAll('.team-checkbox:checked')).length;
        // no limit enforced here - users may select as many teams as they'd like
        updateSelection();
      });
    });

    // List item click toggles checkbox
    listContainer.querySelectorAll('.team-list-item').forEach(item => {
      item.addEventListener('click', function(e) {
        if (e.target.classList.contains('team-checkbox') || e.target.tagName === 'BUTTON' || e.target.closest('button')) return;
        e.preventDefault();
        const cb = this.querySelector('.team-checkbox');
        if (cb) {
          cb.checked = !cb.checked;
          const checkedCount = Array.from(listContainer.querySelectorAll('.team-checkbox:checked')).length;
          // no limit enforced here either
          updateSelection();
        }
      });
    });

    // Search filtering
    searchInput?.addEventListener('input', function() {
      const q = (this.value || '').trim().toLowerCase();
      listContainer.querySelectorAll('.team-list-item').forEach(item => {
        const number = item.dataset.teamNumber || '';
        const name = (item.dataset.teamName || '').toLowerCase();
        const matches = !q || number.includes(q) || name.includes(q);
        item.classList.toggle('hidden', !matches);
      });
    });
    clearSearchBtn?.addEventListener('click', function() { searchInput.value = ''; searchInput.dispatchEvent(new Event('input')); searchInput.focus(); });

    // Quick actions
    selectAllBtn?.addEventListener('click', function() {
      const visible = Array.from(listContainer.querySelectorAll('.team-list-item:not(.hidden) .team-checkbox'));
      visible.forEach(cb => cb.checked = true);
      updateSelection();
    });
    clearBtn?.addEventListener('click', function() {
      listContainer.querySelectorAll('.team-checkbox').forEach(cb => cb.checked = false);
      updateSelection();
    });

    function updateSelection() {
      // Sync hidden select with checked checkboxes
      const checked = Array.from(listContainer.querySelectorAll('.team-checkbox:checked')).map(cb => cb.value);
      Array.from(hiddenSelect.options).forEach(opt => { opt.selected = checked.includes(opt.value.toString()); });

      // Render pills
      const teams = Array.from(listContainer.querySelectorAll('.team-checkbox:checked')).map(cb => {
        const item = cb.closest('.team-list-item');
        return { number: cb.value, name: item.dataset.teamName };
      });
      pillsContainer.innerHTML = '';
      if (teams.length === 0) {
        pillsContainer.innerHTML = '<div class="text-muted small">No teams selected</div>';
      }
      teams.forEach(t => {
        const pill = document.createElement('span');
        pill.className = 'selected-team-pill';
        pill.innerHTML = `<strong>${t.number}</strong> <span class="ms-1">${t.name}</span> <button class="btn btn-sm btn-link remove-team" data-team="${t.number}" title="Remove team"><i class="fas fa-times"></i></button>`;
        pillsContainer.appendChild(pill);
        pill.querySelector('.remove-team').addEventListener('click', function() {
          const num = this.dataset.team;
          const cb = listContainer.querySelector(`.team-checkbox[value="${num}"]`);
          if (cb) { cb.checked = false; updateSelection(); }
        });
      });
    }

    // Initialize
    updateSelection();
  }

  // Initialize selectors after DOM load
  initAllianceSelector('red', redHiddenSelect);
  initAllianceSelector('blue', blueHiddenSelect);

  runBtn.addEventListener('click', async function() {
    const red = getSelectedValuesFromHidden(redHiddenSelect);
    const blue = getSelectedValuesFromHidden(blueHiddenSelect);
    // Server will use default simulation parameters; client no longer sends seed or count
    const n = undefined; // intentionally undefined — server default used
    const seed = undefined;
    const eventId = eventSelect.value || null;

    if (red.length === 0 || blue.length === 0) {
      resultsDiv.innerHTML = '<div class="alert alert-warning">Select at least one team per alliance</div>';
      return;
    }
    // allow any number of teams per alliance (no client-side limit)
    // Check for duplicate teams between alliances and display a non-blocking warning
    const overlap = red.filter(x => blue.includes(x));
      const formatOverlap = (arr) => {
        if (!arr || arr.length === 0) return '';
        if (arr.length <= 8) return arr.join(', ');
        const first = arr.slice(0, 8).join(', ');
        return `${first} and ${arr.length - 8} more`;
      };
      if (overlap.length > 0) {
        const shortList = formatOverlap(overlap);
        const warnHtml = `<div class="alert alert-warning">Warning: Team ${shortList} selected in both alliances. Simulation will proceed.</div>`;
      resultsDiv.innerHTML = warnHtml + '<div class="spinner-border text-primary" role="status"><span class="sr-only">Loading...</span></div> Running simulation...';
    }

    const payload = { red, blue, event_id: eventId };
    try {
      // Attach CSRF token if available
      const headers = { 'Content-Type': 'application/json' };
      const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
      if (csrfToken) headers['X-CSRFToken'] = csrfToken;
      const res = await fetch('/simulations/run', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (!data.ok) {
        resultsDiv.innerHTML = `<div class="alert alert-danger">Simulation failed: ${data.error || 'unknown error'}</div>`;
        return;
      }

      const redScore = Number(data.red.expected_score).toFixed(1);
      const blueScore = Number(data.blue.expected_score).toFixed(1);
      const redProb = (data.red.win_prob * 100).toFixed(1);
      const blueProb = (data.blue.win_prob * 100).toFixed(1);
      const tieProb = (data.tie_prob * 100).toFixed(1);
      const winner = data.predicted_winner;
      // If server reports overlap_teams (additional check), show a warning banner above the results
      if (data.overlap_teams && data.overlap_teams.length > 0) {
        const shortList = formatOverlap(data.overlap_teams);
        const warn = `<div class="alert alert-warning">Warning: Team ${shortList} selected in both alliances.</div>`;
        resultsDiv.innerHTML = warn;
      } else {
        resultsDiv.innerHTML = '';
      }

      resultsDiv.innerHTML += `
        <div class="row">
          <div class="col-md-6">
            <div class="card">
              <div class="card-body">
                <h6>Red Alliance</h6>
                <p>Expected score: <strong>${redScore}</strong></p>
                <p>Win probability: <strong>${redProb}%</strong></p>
              </div>
            </div>
          </div>
          <div class="col-md-6">
            <div class="card">
              <div class="card-body">
                <h6>Blue Alliance</h6>
                <p>Expected score: <strong>${blueScore}</strong></p>
                <p>Win probability: <strong>${blueProb}%</strong></p>
              </div>
            </div>
          </div>
        </div>
        <div class="mt-2">
          <p>Tie probability: <strong>${tieProb}%</strong></p>
          <p>Predicted winner: <strong>${winner.toUpperCase()}</strong></p>
        </div>
      `;
    } catch (err) {
      console.error(err);
      resultsDiv.innerHTML = `<div class="alert alert-danger">Error running simulation: ${err}</div>`;
    }
  });
});
