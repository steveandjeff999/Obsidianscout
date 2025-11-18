Simulations Feature
===================

This feature adds a "Match Simulator" to the analytics area of the app. Teams with analytics permissions can assemble alliances using teams from the database and run a Monte Carlo simulation to estimate expected scores and win probabilities.

Usage
-----
- Navigate to Analytics -> Simulations (requires admin or analytics role).
- Select Red/Blue alliance teams (multi-select). Optionally select an event to use event-scoped data.
- Set the number of simulations (default 3000) and an optional random seed.
- Click "Run Simulation" to get expected scores and probabilities.

Implementation details
----------------------
- Frontend: `app/templates/simulations/index.html`, `app/static/js/simulations.js`
- UI Improvements: Modern team selection using a searchable, filterable, and event-aware team list similar to the `/graphs` dashboard. Supports quick actions, per-alliance selection, and a visual pill-based summary.
- Overlapping selections allowed: The simulator allows the same team to be present in both alliances to facilitate hypothetical scenarios. A non-blocking warning is shown when duplicates are selected, and the server response includes an `overlap_teams` key with the overlapping list.
- The UI has been simplified: the seed and simulations count controls were removed; the server uses a default simulation count.
- Backend: new blueprint in `app/routes/simulations.py` providing `GET /simulations/` and `POST /simulations/run`.
- The simulation uses existing analytics logic in `app/utils/analysis.py`, specifically `_simulate_match_outcomes()` and `calculate_team_metrics()`.

Notes
-----
- The simulator uses the configured total metric (from game_config data_analysis key_metrics) when available, otherwise falls back to `tot`.
- Future improvements: allow direct manual/fake team metrics, custom formula selection, alliance synergy tuning, or cache computed metrics for faster repeated simulations.
