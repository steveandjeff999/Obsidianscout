"""
EPA (Statbotics) Data Refresh Scheduler
Periodically refreshes cached Statbotics EPA data for all teams so the
values stay up-to-date without the user ever hitting a slow API call.

Follows the same daemon-thread scheduler pattern used by
``catchup_scheduler.py``.
"""
import threading
import time
import logging
from datetime import datetime, timezone

from app import db

logger = logging.getLogger(__name__)

# Default interval: refresh every 10 minutes
_DEFAULT_REFRESH_INTERVAL = 600  # seconds


class EPARefreshScheduler:
    """Background thread that periodically refreshes Statbotics EPA data."""

    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.thread = None
        self.refresh_interval = _DEFAULT_REFRESH_INTERVAL
        self.last_refresh = None

        if app:
            self.init_app(app)

    # ------------------------------------------------------------------
    def init_app(self, app):
        """Bind to a Flask app and start the refresh loop."""
        self.app = app
        self.start()

    # ------------------------------------------------------------------
    def start(self):
        if self.running:
            logger.debug("EPA refresh scheduler already running")
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info(
            "EPA refresh scheduler started (interval %ds)", self.refresh_interval
        )

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("EPA refresh scheduler stopped")

    # ------------------------------------------------------------------
    def _loop(self):
        # Brief startup delay so DB setup/migrations complete, then warm immediately.
        time.sleep(5)
        try:
            self._refresh()
        except Exception:
            logger.exception("EPA startup warm failed")

        while self.running:
            # Sleep in small increments so stop() doesn't hang
            for _ in range(int(self.refresh_interval)):
                if not self.running:
                    return
                time.sleep(1)
            try:
                self._refresh()
            except Exception:
                logger.exception("EPA refresh cycle failed")

    # ------------------------------------------------------------------
    def _refresh(self):
        """Refresh EPA data for teams attached to events in the active season year."""
        if not self.app:
            return

        with self.app.app_context():
            # Resolve the active season year from config when possible.
            try:
                from app.utils.config_manager import get_current_game_config
                cfg = get_current_game_config() or {}
                season_year = int(cfg.get('season') or cfg.get('year') or datetime.now(timezone.utc).year)
            except Exception:
                season_year = datetime.now(timezone.utc).year

            # Gather distinct team numbers from events in the active season.
            try:
                from app.models import Team, Event, Match, team_event
                team_numbers = {
                    int(r[0]) for r in (
                        db.session.query(Team.team_number)
                        .join(team_event, Team.id == team_event.c.team_id)
                        .join(Event, Event.id == team_event.c.event_id)
                        .filter(Event.year == int(season_year))
                        .distinct()
                        .all()
                    ) if r and r[0] is not None
                }

                # Supplement from match alliance strings for events where team_event links are incomplete.
                match_rows = (
                    db.session.query(Match.red_alliance, Match.blue_alliance)
                    .join(Event, Event.id == Match.event_id)
                    .filter(Event.year == int(season_year))
                    .all()
                )
                for red_alliance, blue_alliance in match_rows:
                    for side in (red_alliance, blue_alliance):
                        if not side:
                            continue
                        for token in str(side).split(','):
                            token = token.strip()
                            if token.isdigit():
                                team_numbers.add(int(token))
            except Exception:
                logger.exception("EPA refresh: failed to query teams from %s events", season_year)
                return

            if not team_numbers:
                logger.info("EPA refresh: no teams found for %s events", season_year)
                return

            logger.info(
                "EPA refresh: updating %d teams from %s events...",
                len(team_numbers),
                season_year,
            )

            from app.utils.statbotics_api_utils import (
                get_statbotics_team_epa,
                clear_epa_caches,
            )

            # Clear in-memory cache so fresh data is fetched from the API
            # (DB-level cache rows will be overwritten by the fetch loop)
            clear_epa_caches()

            updated = 0
            failed = 0
            for tn in sorted(team_numbers):
                try:
                    result = get_statbotics_team_epa(tn, use_cache=False)
                    if result:
                        updated += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                # Small sleep to avoid hammering the Statbotics API
                time.sleep(0.25)

            self.last_refresh = datetime.now(timezone.utc)
            logger.info(
                "EPA refresh complete: %d updated, %d no-data (of %d)",
                updated, failed, len(team_numbers),
            )


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------
epa_scheduler = EPARefreshScheduler()


def start_epa_scheduler(app):
    """Initialize and start the EPA refresh scheduler."""
    try:
        epa_scheduler.init_app(app)
    except Exception as e:
        logger.error("Failed to start EPA refresh scheduler: %s", e)


def stop_epa_scheduler():
    """Stop the EPA refresh scheduler."""
    try:
        epa_scheduler.stop()
    except Exception as e:
        logger.error("Failed to stop EPA refresh scheduler: %s", e)
