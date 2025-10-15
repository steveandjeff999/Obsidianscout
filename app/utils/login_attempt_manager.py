#!/usr/bin/env python3
"""
Enhanced Login Attempt Management
Provides automatic cleanup and better control over failed login attempts
"""
import threading
import time
from datetime import datetime, timezone, timedelta
from flask import current_app
from app.models import LoginAttempt, db
import logging

logger = logging.getLogger(__name__)

class LoginAttemptManager:
    """Enhanced management of login attempts with automatic cleanup"""
    
    def __init__(self, cleanup_interval_minutes=10, lockout_duration_minutes=15):
        self.cleanup_interval = cleanup_interval_minutes * 60  # Convert to seconds
        self.lockout_duration = lockout_duration_minutes
        self.running = False
        self.cleanup_thread = None
        
    def start_automatic_cleanup(self, app):
        """Start the automatic cleanup thread"""
        if self.running:
            return
            
        self.running = True
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_worker, 
            args=(app,), 
            daemon=True
        )
        self.cleanup_thread.start()
        logger.info(f"Started automatic failed login cleanup (every {self.cleanup_interval//60} minutes)")
        
    def stop_automatic_cleanup(self):
        """Stop the automatic cleanup thread"""
        self.running = False
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=5)
            
    def _cleanup_worker(self, app):
        """Worker thread for automatic cleanup"""
        while self.running:
            try:
                time.sleep(self.cleanup_interval)
                
                if not self.running:
                    break
                    
                with app.app_context():
                    self.cleanup_old_failed_attempts()
                    
            except Exception as e:
                logger.error(f"Error in login attempt cleanup worker: {e}")
                time.sleep(60)  # Wait a minute before retrying
                
    def cleanup_old_failed_attempts(self, minutes_old=None):
        """Clean up old failed login attempts"""
        try:
            if minutes_old is None:
                minutes_old = self.cleanup_interval // 60
                
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
            
            # Count how many we're about to delete
            count_query = LoginAttempt.query.filter(
                LoginAttempt.success == False,
                LoginAttempt.attempt_time < cutoff_time
            )
            count_to_delete = count_query.count()
            
            if count_to_delete > 0:
                # Delete old failed attempts
                deleted_count = count_query.delete()
                db.session.commit()
                
                logger.info(f"Cleaned up {deleted_count} failed login attempts older than {minutes_old} minutes")
                print(f"Cleared {deleted_count} old failed login attempts (older than {minutes_old} minutes)")
                
                return deleted_count
            else:
                logger.debug("No old failed login attempts to clean up")
                return 0
                
        except Exception as e:
            logger.error(f"Error cleaning up failed login attempts: {e}")
            db.session.rollback()
            return 0
            
    def clear_attempts_for_user(self, username):
        """Clear all failed attempts for a specific user"""
        try:
            deleted_count = LoginAttempt.query.filter(
                LoginAttempt.username == username,
                LoginAttempt.success == False
            ).delete()
            
            db.session.commit()
            logger.info(f"Cleared {deleted_count} failed login attempts for user: {username}")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error clearing attempts for user {username}: {e}")
            db.session.rollback()
            return 0
            
    def clear_attempts_for_ip(self, ip_address):
        """Clear all failed attempts for a specific IP address"""
        try:
            deleted_count = LoginAttempt.query.filter(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success == False
            ).delete()
            
            db.session.commit()
            logger.info(f"Cleared {deleted_count} failed login attempts for IP: {ip_address}")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error clearing attempts for IP {ip_address}: {e}")
            db.session.rollback()
            return 0
            
    def get_cleanup_stats(self):
        """Get statistics about login attempts and cleanup"""
        try:
            total_attempts = LoginAttempt.query.count()
            failed_attempts = LoginAttempt.query.filter_by(success=False).count()
            successful_attempts = LoginAttempt.query.filter_by(success=True).count()
            
            # Recent failed attempts (last hour)
            recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
            recent_failed = LoginAttempt.query.filter(
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= recent_cutoff
            ).count()
            
            # Currently blocked IPs/users (last 15 minutes with 10+ failures)
            block_cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.lockout_duration)
            blocked_query = db.session.query(
                LoginAttempt.ip_address,
                LoginAttempt.username,
                db.func.count(LoginAttempt.id).label('count')
            ).filter(
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= block_cutoff
            ).group_by(
                LoginAttempt.ip_address, 
                LoginAttempt.username
            ).having(
                db.func.count(LoginAttempt.id) >= 10
            ).all()
            
            return {
                'total_attempts': total_attempts,
                'failed_attempts': failed_attempts,
                'successful_attempts': successful_attempts,
                'recent_failed_attempts': recent_failed,
                'currently_blocked_count': len(blocked_query),
                'blocked_entries': blocked_query,
                'cleanup_interval_minutes': self.cleanup_interval // 60,
                'lockout_duration_minutes': self.lockout_duration
            }
            
        except Exception as e:
            logger.error(f"Error getting cleanup stats: {e}")
            return {}

# Global instance
login_attempt_manager = LoginAttemptManager()

def start_login_cleanup(app, interval_minutes=10):
    """Start automatic login attempt cleanup"""
    global login_attempt_manager
    login_attempt_manager = LoginAttemptManager(cleanup_interval_minutes=interval_minutes)
    login_attempt_manager.start_automatic_cleanup(app)

def stop_login_cleanup():
    """Stop automatic login attempt cleanup"""
    global login_attempt_manager
    login_attempt_manager.stop_automatic_cleanup()

def manual_cleanup(minutes_old=10):
    """Manually trigger cleanup of old failed attempts"""
    global login_attempt_manager
    return login_attempt_manager.cleanup_old_failed_attempts(minutes_old)

def clear_user_attempts(username):
    """Clear all failed attempts for a specific user"""
    global login_attempt_manager
    return login_attempt_manager.clear_attempts_for_user(username)

def get_login_stats():
    """Get login attempt statistics"""
    global login_attempt_manager
    return login_attempt_manager.get_cleanup_stats()
