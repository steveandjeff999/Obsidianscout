"""
Schedule Offset Scheduler
=========================
Runs every 15 minutes in a background daemon thread.

For every active event it:
  1. Calls ScheduleAdjuster.analyze_schedule_variance() which uses
     locally-stored actual_times first, then falls back to the remote
     FIRST/TBA APIs only when needed.
  2. Writes the computed offset (minutes) + a timestamp to the Event row
     so the live-strategy page can apply a stable, locally-authoritative
     correction without chasing a moving schedule on every poll.

Important design decisions
--------------------------
* The offset is computed from *locally-recorded* actual_times wherever
  possible.  Remote API data is only a fallback when no local actuals
  exist yet.  This means a slow API sync cannot push the schedule
  forward unexpectedly.
* The offset is written to event.schedule_offset / event.offset_updated_at
  at most once per 15-minute window.  Front-end polls can remain at
  30 s without hitting external APIs.
* The scheduler intentionally does NOT call adjust_future_match_times()
  (which mutates predicted_time in the DB).  We let the front-end apply
  the offset client-side so the raw predicted_time stays immutable – this
  prevents the "schedule keeps getting pushed back" problem.
"""

import threading
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_REFRESH_INTERVAL_SECONDS = 900   # 15 minutes
_STARTUP_DELAY_SECONDS    = 45    # give the app time to finish booting


class ScheduleOffsetScheduler:
    """Background daemon that keeps event.schedule_offset fresh."""

    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.thread = None
        self._interval = _REFRESH_INTERVAL_SECONDS

        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.start()

    # ------------------------------------------------------------------
    def start(self):
        if self.running:
            logger.debug("Schedule-offset scheduler already running")
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info(
            "Schedule-offset scheduler started (interval %ds)", self._interval
        )

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Schedule-offset scheduler stopped")

    # ------------------------------------------------------------------
    def _loop(self):
        time.sleep(_STARTUP_DELAY_SECONDS)
        while self.running:
            try:
                self._refresh()
            except Exception:
                logger.exception("Schedule-offset refresh cycle failed")
            # Sleep in 1-second ticks so stop() doesn't block
            for _ in range(self._interval):
                if not self.running:
                    return
                time.sleep(1)

    # ------------------------------------------------------------------
    def _refresh(self):
        if not self.app:
            return

        with self.app.app_context():
            try:
                self._run_refresh()
            except Exception:
                logger.exception("Error inside schedule-offset refresh")

    def _run_refresh(self):
        from app import db
        from app.models import Event, Match
        from app.utils.config_manager import load_game_config
        from app.utils.schedule_adjuster import ScheduleAdjuster

        try:
            from app.models import User
            team_numbers = set()
            for rec in User.query.with_entities(User.scouting_team_number).filter(
                User.scouting_team_number.isnot(None)
            ).distinct().all():
                if rec[0] is not None:
                    team_numbers.add(rec[0])
        except Exception:
            team_numbers = set()

        if not team_numbers:
            logger.debug("Schedule-offset scheduler: no scouting teams found")
            return

        for team_number in sorted(team_numbers):
            try:
                game_config = load_game_config(team_number=team_number)
                event_code = game_config.get('current_event_code')
                season = game_config.get('season', 2026)
                if not event_code:
                    continue

                # DB stores codes like "2026OKTU"; config may store bare "OKTU"
                if not (len(event_code) > 4 and event_code[:4].isdigit()):
                    event_code_db = f"{season}{event_code}"
                else:
                    event_code_db = event_code

                event = Event.query.filter_by(
                    code=event_code_db,
                    scouting_team_number=team_number
                ).first()

                if not event:
                    logger.debug(
                        "Schedule-offset: event %s / team %s not found in DB",
                        event_code_db, team_number
                    )
                    continue

                # --- Compute offset using LOCAL actuals primarily ---
                # Build a lightweight offset from matches that already have
                # both scheduled_time and actual_time in the local DB.
                # This deliberately avoids hitting external APIs unless
                # there are genuinely no local actuals yet.
                local_offset = self._compute_local_offset(event, team_number)

                if local_offset is not None:
                    offset_minutes = local_offset
                    logger.info(
                        "Schedule-offset (local) team=%s event=%s  offset=%+.1f min",
                        team_number, event_code_db, offset_minutes
                    )
                else:
                    # No local actuals – fall back to ScheduleAdjuster (may hit API)
                    adjuster = ScheduleAdjuster(event, team_number)
                    analysis = adjuster.analyze_schedule_variance()
                    offset_minutes = analysis.get('recent_offset_minutes', 0)
                    confidence = analysis.get('confidence', 0.0)
                    logger.info(
                        "Schedule-offset (API fallback) team=%s event=%s  "
                        "offset=%+.1f min  confidence=%.0f%%",
                        team_number, event_code_db, offset_minutes, confidence * 100
                    )

                # Write to DB – keep the raw predicted_times untouched
                event.schedule_offset = int(round(offset_minutes))
                event.offset_updated_at = datetime.now(timezone.utc)
                db.session.commit()

            except Exception:
                logger.exception(
                    "Schedule-offset: error processing team %s", team_number
                )
                try:
                    db.session.rollback()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    @staticmethod
    def _compute_local_offset(event, scouting_team_number):
        """
        Compute schedule offset purely from locally-stored match times.

        Returns offset in minutes (positive = event running late) or
        None if there are not enough local actuals to be meaningful.
        """
        from app.models import Match
        from datetime import timezone

        matches = Match.query.filter_by(
            event_id=event.id,
            scouting_team_number=scouting_team_number
        ).filter(
            Match.scheduled_time.isnot(None),
            Match.actual_time.isnot(None)
        ).order_by(Match.match_type, Match.match_number).all()

        if len(matches) < 1:
            return None   # not enough local data

        delays = []
        for m in matches:
            sched = m.scheduled_time
            actual = m.actual_time
            # Make naive datetimes timezone-aware (stored as UTC)
            if sched.tzinfo is None:
                from datetime import timezone as _tz
                sched = sched.replace(tzinfo=_tz.utc)
            if actual.tzinfo is None:
                from datetime import timezone as _tz
                actual = actual.replace(tzinfo=_tz.utc)
            delay_min = (actual - sched).total_seconds() / 60.0
            # Ignore outliers (data errors)
            if abs(delay_min) <= 90:
                delays.append(delay_min)

        if not delays:
            return None

        # Weight recent matches more heavily (last 3 count extra)
        recent = delays[-3:]
        if len(delays) >= 3:
            # Blend: 60% recent, 40% overall average
            overall_avg = sum(delays) / len(delays)
            recent_avg  = sum(recent) / len(recent)
            return recent_avg * 0.6 + overall_avg * 0.4
        else:
            return sum(delays) / len(delays)


# ---------------------------------------------------------------------------
# Module-level convenience entry point (mirrors epa_scheduler pattern)
# ---------------------------------------------------------------------------
_scheduler_instance = None


def start_schedule_offset_scheduler(app):
    global _scheduler_instance
    if _scheduler_instance is not None and _scheduler_instance.running:
        logger.debug("Schedule-offset scheduler already started")
        return _scheduler_instance
    _scheduler_instance = ScheduleOffsetScheduler(app)
    return _scheduler_instance
