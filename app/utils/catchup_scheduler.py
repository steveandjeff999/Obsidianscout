"""
Catch-up Sync Scheduler
Automatically runs catch-up synchronization for offline servers
"""
import threading
import time
import logging
from datetime import datetime, timezone, timedelta
from flask import current_app

logger = logging.getLogger(__name__)


class CatchupSyncScheduler:
    """
    Scheduler for automatic catch-up synchronization
    Runs in background thread to detect and sync offline servers
    """
    
    def __init__(self, app=None):
        self.app = app
        self.running = False
        self.thread = None
        self.check_interval = 300  # Check every 5 minutes by default
        self.last_check = None
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize the scheduler with Flask app"""
        self.app = app
        
        # Load configuration
        with app.app_context():
            try:
                from app.models import SyncConfig
                self.check_interval = SyncConfig.get_value('catchup_check_interval', 300)
                enabled = SyncConfig.get_value('catchup_scheduler_enabled', True)
                
                if enabled:
                    self.start()
                    
            except Exception as e:
                logger.warning(f"Could not load catch-up scheduler configuration: {e}")
                # Start with defaults
                self.start()
    
    def start(self):
        """Start the catch-up scheduler"""
        if self.running:
            logger.warning("Catch-up scheduler is already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.thread.start()
        logger.info(f"🔄 Catch-up scheduler started (check interval: {self.check_interval}s)")
    
    def stop(self):
        """Stop the catch-up scheduler"""
        if not self.running:
            return
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info("🛑 Catch-up scheduler stopped")
    
    def _scheduler_loop(self):
        """Main scheduler loop"""
        logger.info("🔄 Catch-up scheduler loop started")
        
        while self.running:
            try:
                # Check if we should run catch-up
                if self._should_run_catchup():
                    self._run_catchup_scan()
                
                # Sleep for check interval
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"❌ Error in catch-up scheduler loop: {e}")
                # Wait a bit before retrying
                time.sleep(60)
    
    def _should_run_catchup(self) -> bool:
        """
        Determine if we should run catch-up scan now
        """
        # Always run if this is the first check
        if self.last_check is None:
            return True
        
        # Check if enough time has passed since last check
        time_since_last = datetime.now(timezone.utc) - self.last_check
        return time_since_last.total_seconds() >= self.check_interval
    
    def _run_catchup_scan(self):
        """
        Run catch-up synchronization scan
        """
        self.last_check = datetime.now(timezone.utc)
        
        try:
            logger.info("🔍 Running scheduled catch-up scan...")
            
            with self.app.app_context():
                from app.utils.catchup_sync import catchup_sync_manager
                
                # Run automatic catch-up
                results = catchup_sync_manager.run_automatic_catchup()
                
                if results:
                    logger.info(f"✅ Catch-up scan completed: {len(results)} servers processed")
                    
                    # Log summary of results
                    success_count = sum(1 for r in results if r['success'])
                    failed_count = len(results) - success_count
                    
                    if success_count > 0:
                        logger.info(f"   🎯 {success_count} servers successfully caught up")
                    if failed_count > 0:
                        logger.warning(f"   ⚠️  {failed_count} servers failed catch-up")
                    
                    # Log detailed results for failed servers
                    for result in results:
                        if not result['success']:
                            server_name = result['server_name']
                            error_count = len(result['errors'])
                            logger.warning(f"   ❌ {server_name}: {error_count} errors")
                else:
                    logger.debug("ℹ️  All servers are up to date")
        
        except Exception as e:
            logger.error(f"❌ Catch-up scan failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())


# Global scheduler instance
catchup_scheduler = CatchupSyncScheduler()


def start_catchup_scheduler(app):
    """Start the catch-up scheduler for the given app"""
    try:
        catchup_scheduler.init_app(app)
        logger.info("✅ Catch-up scheduler initialized")
    except Exception as e:
        logger.error(f"❌ Failed to start catch-up scheduler: {e}")


def stop_catchup_scheduler():
    """Stop the catch-up scheduler"""
    try:
        catchup_scheduler.stop()
        logger.info("✅ Catch-up scheduler stopped")
    except Exception as e:
        logger.error(f"❌ Failed to stop catch-up scheduler: {e}")
