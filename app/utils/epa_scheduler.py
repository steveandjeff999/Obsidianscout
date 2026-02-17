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

logger = logging.getLogger(__name__)

# Default interval: refresh every 15 minutes
_DEFAULT_REFRESH_INTERVAL = 900  # seconds


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
        # Wait a short period after startup so the app is fully ready
        time.sleep(30)
        while self.running:
            try:
                self._refresh()
            except Exception:
                logger.exception("EPA refresh cycle failed")
            # Sleep in small increments so stop() doesn't hang
            for _ in range(int(self.refresh_interval)):
                if not self.running:
                    return
                time.sleep(1)

    # ------------------------------------------------------------------
    def _refresh(self):
        """Refresh EPA data for every team currently in the database."""
        if not self.app:
            return

        with self.app.app_context():
            # Only run if EPA is actually enabled for at least one scouting team
            try:
                from app.models import ScoutingTeamSettings
                enabled = ScoutingTeamSettings.query.filter(
                    ScoutingTeamSettings.epa_source != 'scouted_only'
                ).first()
                if not enabled:
                    logger.debug("EPA refresh skipped — no team has EPA enabled")
                    return
            except Exception:
                return

            # Gather all distinct team numbers in the database
            try:
                from app.models import Team
                team_numbers = [
                    r[0] for r in
                    Team.query.with_entities(Team.team_number).distinct().all()
                ]
            except Exception:
                logger.exception("EPA refresh: failed to query teams")
                return

            if not team_numbers:
                return

            logger.info(
                "EPA refresh: updating %d teams…", len(team_numbers)
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
            for tn in team_numbers:
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
