"""
Brute Force Protection Utilities
Provides IP-based and user-based rate limiting for login attempts
"""
from datetime import datetime, timedelta
from flask import request, current_app
from app.models import LoginAttempt
import logging

logger = logging.getLogger(__name__)


class BruteForceProtection:
    """Handles brute force protection for authentication"""
    
    def __init__(self, max_attempts=10, lockout_minutes=15, cleanup_days=30):
        self.max_attempts = max_attempts
        self.lockout_minutes = lockout_minutes
        self.cleanup_days = cleanup_days
    
    def get_client_ip(self):
        """Get the real client IP address, handling proxies"""
        # Check for X-Forwarded-For header (from proxy/load balancer)
        if request.headers.get('X-Forwarded-For'):
            ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
        # Check for X-Real-IP header
        elif request.headers.get('X-Real-IP'):
            ip = request.headers.get('X-Real-IP')
        # Fall back to remote_addr
        else:
            ip = request.remote_addr
        
        return ip or '127.0.0.1'  # Fallback to localhost if no IP found
    
    def get_user_agent(self):
        """Get the user agent string"""
        return request.headers.get('User-Agent', '')[:500]  # Limit to 500 chars
    
    def is_blocked(self, username=None):
        """Check if the current request should be blocked"""
        ip_address = self.get_client_ip()
        
        try:
            return LoginAttempt.is_blocked(
                ip_address=ip_address,
                username=username,
                max_attempts=self.max_attempts,
                lockout_minutes=self.lockout_minutes
            )
        except Exception as e:
            logger.error(f"Error checking brute force protection: {e}")
            # If there's an error, err on the side of caution but allow login
            return False
    
    def record_failed_attempt(self, username=None, team_number=None):
        """Record a failed login attempt"""
        ip_address = self.get_client_ip()
        user_agent = self.get_user_agent()
        
        try:
            LoginAttempt.record_attempt(
                ip_address=ip_address,
                username=username,
                team_number=team_number,
                success=False,
                user_agent=user_agent
            )
            
            logger.warning(
                f"Failed login attempt from {ip_address} for user '{username}' "
                f"(team {team_number})"
            )
            
        except Exception as e:
            logger.error(f"Error recording failed login attempt: {e}")
    
    def record_successful_attempt(self, username=None, team_number=None):
        """Record a successful login attempt and clear failed attempts"""
        ip_address = self.get_client_ip()
        user_agent = self.get_user_agent()
        
        try:
            # Record the successful attempt
            LoginAttempt.record_attempt(
                ip_address=ip_address,
                username=username,
                team_number=team_number,
                success=True,
                user_agent=user_agent
            )
            
            # Clear previous failed attempts for this IP/username
            LoginAttempt.clear_successful_attempts(ip_address, username)
            
            logger.info(f"Successful login from {ip_address} for user '{username}'")
            
        except Exception as e:
            logger.error(f"Error recording successful login attempt: {e}")
    
    def get_remaining_attempts(self, username=None):
        """Get the number of remaining attempts before lockout"""
        ip_address = self.get_client_ip()
        
        try:
            failed_count = LoginAttempt.get_failed_attempts_count(
                ip_address=ip_address,
                username=username,
                since_minutes=self.lockout_minutes
            )
            
            return max(0, self.max_attempts - failed_count)
            
        except Exception as e:
            logger.error(f"Error getting remaining attempts: {e}")
            return self.max_attempts  # Default to max attempts if error
    
    def get_lockout_time_remaining(self, username=None):
        """Get the time remaining until lockout expires (in minutes)"""
        ip_address = self.get_client_ip()
        
        try:
            # Get the most recent failed attempt within lockout period
            cutoff_time = datetime.utcnow() - timedelta(minutes=self.lockout_minutes)
            
            query = LoginAttempt.query.filter(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= cutoff_time
            )
            
            if username:
                query = query.filter(LoginAttempt.username == username)
            
            latest_attempt = query.order_by(LoginAttempt.attempt_time.desc()).first()
            
            if latest_attempt:
                unlock_time = latest_attempt.attempt_time + timedelta(minutes=self.lockout_minutes)
                remaining = unlock_time - datetime.utcnow()
                
                if remaining.total_seconds() > 0:
                    return int(remaining.total_seconds() / 60)  # Return minutes
            
            return 0
            
        except Exception as e:
            logger.error(f"Error getting lockout time remaining: {e}")
            return 0
    
    def cleanup_old_attempts(self):
        """Clean up old login attempts"""
        try:
            deleted_count = LoginAttempt.cleanup_old_attempts(self.cleanup_days)
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old login attempts")
            return deleted_count
        except Exception as e:
            logger.error(f"Error cleaning up old login attempts: {e}")
            return 0


# Global instance
brute_force_protection = BruteForceProtection()


def is_login_blocked(username=None):
    """Check if login is currently blocked for the requesting IP/user"""
    return brute_force_protection.is_blocked(username)


def record_login_attempt(username=None, team_number=None, success=False):
    """Record a login attempt (success or failure)"""
    if success:
        brute_force_protection.record_successful_attempt(username, team_number)
    else:
        brute_force_protection.record_failed_attempt(username, team_number)


def get_login_status(username=None):
    """Get current login status including remaining attempts and lockout info"""
    remaining_attempts = brute_force_protection.get_remaining_attempts(username)
    lockout_minutes = brute_force_protection.get_lockout_time_remaining(username)
    is_blocked = brute_force_protection.is_blocked(username)
    
    return {
        'is_blocked': is_blocked,
        'remaining_attempts': remaining_attempts,
        'lockout_minutes_remaining': lockout_minutes,
        'max_attempts': brute_force_protection.max_attempts,
        'lockout_duration_minutes': brute_force_protection.lockout_minutes
    }
