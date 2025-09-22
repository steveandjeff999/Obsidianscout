#!/usr/bin/env python3
"""
Login Attempt Management CLI
Command line interface for managing login attempts and brute force protection
"""
import argparse
import sys
from datetime import datetime, timedelta

def show_login_stats():
    """Show current login attempt statistics"""
    try:
        from app import create_app
        from app.models import LoginAttempt, db
        
        app = create_app()
        
        with app.app_context():
            print("📊 LOGIN ATTEMPT STATISTICS")
            print("=" * 50)
            
            # Overall stats
            total_attempts = LoginAttempt.query.count()
            failed_attempts = LoginAttempt.query.filter_by(success=False).count()
            successful_attempts = LoginAttempt.query.filter_by(success=True).count()
            
            print(f"Total login attempts: {total_attempts}")
            print(f"Failed attempts: {failed_attempts}")
            print(f"Successful attempts: {successful_attempts}")
            
            if total_attempts > 0:
                success_rate = (successful_attempts / total_attempts) * 100
                print(f"Success rate: {success_rate:.1f}%")
            
            # Recent activity (last 24 hours)
            recent_cutoff = datetime.utcnow() - timedelta(hours=24)
            recent_total = LoginAttempt.query.filter(LoginAttempt.attempt_time >= recent_cutoff).count()
            recent_failed = LoginAttempt.query.filter(
                LoginAttempt.attempt_time >= recent_cutoff,
                LoginAttempt.success == False
            ).count()
            
            print(f"\nLast 24 hours:")
            print(f"Total attempts: {recent_total}")
            print(f"Failed attempts: {recent_failed}")
            
            # Currently blocked users/IPs
            block_cutoff = datetime.utcnow() - timedelta(minutes=15)
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
            
            print(f"\nCurrently blocked (10+ failures in 15 minutes):")
            if blocked_query:
                for ip, username, count in blocked_query:
                    print(f"   {username or 'unknown'} from {ip}: {count} failures")
            else:
                print("   No users/IPs currently blocked")
            
            # Top failed usernames
            print(f"\nTop failed login attempts by username:")
            top_failed = db.session.query(
                LoginAttempt.username,
                db.func.count(LoginAttempt.id).label('count')
            ).filter(
                LoginAttempt.success == False
            ).group_by(LoginAttempt.username).order_by(
                db.func.count(LoginAttempt.id).desc()
            ).limit(5).all()
            
            for username, count in top_failed:
                print(f"   {username or 'unknown'}: {count} failures")
                
    except Exception as e:
        print(f"❌ Error getting login stats: {e}")

def cleanup_failed_attempts(minutes_old=10, username=None, ip_address=None):
    """Clean up failed login attempts"""
    try:
        from app import create_app
        from app.models import LoginAttempt, db
        
        app = create_app()
        
        with app.app_context():
            if username:
                print(f"🧹 Clearing failed attempts for user: {username}")
                deleted_count = LoginAttempt.query.filter(
                    LoginAttempt.username == username,
                    LoginAttempt.success == False
                ).delete()
            elif ip_address:
                print(f"🧹 Clearing failed attempts for IP: {ip_address}")
                deleted_count = LoginAttempt.query.filter(
                    LoginAttempt.ip_address == ip_address,
                    LoginAttempt.success == False
                ).delete()
            else:
                print(f"🧹 Clearing failed attempts older than {minutes_old} minutes")
                cutoff_time = datetime.utcnow() - timedelta(minutes=minutes_old)
                deleted_count = LoginAttempt.query.filter(
                    LoginAttempt.success == False,
                    LoginAttempt.attempt_time < cutoff_time
                ).delete()
            
            db.session.commit()
            print(f"✅ Cleared {deleted_count} failed login attempts")
            
    except Exception as e:
        print(f"❌ Error cleaning up failed attempts: {e}")

def test_brute_force_status():
    """Test current brute force protection status"""
    try:
        from app import create_app
        from app.utils.brute_force_protection import get_login_status
        
        app = create_app()
        
        with app.app_context():
            # Can't test without request context, but we can check the database directly
            print("🛡️ BRUTE FORCE PROTECTION STATUS")
            print("=" * 50)
            
            from app.models import LoginAttempt, db
            from datetime import datetime, timedelta
            
            # Check recent activity that would trigger blocks
            cutoff_time = datetime.utcnow() - timedelta(minutes=15)
            
            suspicious_activity = db.session.query(
                LoginAttempt.ip_address,
                LoginAttempt.username,
                db.func.count(LoginAttempt.id).label('count'),
                db.func.max(LoginAttempt.attempt_time).label('latest')
            ).filter(
                LoginAttempt.success == False,
                LoginAttempt.attempt_time >= cutoff_time
            ).group_by(
                LoginAttempt.ip_address,
                LoginAttempt.username
            ).order_by(db.func.count(LoginAttempt.id).desc()).all()
            
            print("Recent failed login activity (last 15 minutes):")
            if suspicious_activity:
                for ip, username, count, latest in suspicious_activity:
                    status = "🔒 BLOCKED" if count >= 10 else f"⚠️ {10-count} attempts remaining"
                    print(f"   {username or 'unknown'} from {ip}: {count} failures - {status}")
                    print(f"      Latest attempt: {latest}")
            else:
                print("   No recent failed login activity")
                
            print(f"\nBrute force protection settings:")
            print(f"   Max attempts before block: 10")
            print(f"   Lockout duration: 15 minutes")
            print(f"   Auto cleanup: Every 10 minutes")
                
    except Exception as e:
        print(f"❌ Error checking brute force status: {e}")

def main():
    parser = argparse.ArgumentParser(description='Manage login attempts and brute force protection')
    parser.add_argument('action', choices=['stats', 'cleanup', 'status', 'clear-user', 'clear-ip'], 
                       help='Action to perform')
    parser.add_argument('--username', help='Username for user-specific operations')
    parser.add_argument('--ip', help='IP address for IP-specific operations')
    parser.add_argument('--minutes', type=int, default=10, 
                       help='Minutes old for cleanup (default: 10)')
    
    args = parser.parse_args()
    
    if args.action == 'stats':
        show_login_stats()
    elif args.action == 'cleanup':
        cleanup_failed_attempts(minutes_old=args.minutes)
    elif args.action == 'status':
        test_brute_force_status()
    elif args.action == 'clear-user':
        if not args.username:
            print("❌ --username is required for clear-user action")
            sys.exit(1)
        cleanup_failed_attempts(username=args.username)
    elif args.action == 'clear-ip':
        if not args.ip:
            print("❌ --ip is required for clear-ip action")
            sys.exit(1)
        cleanup_failed_attempts(ip_address=args.ip)

if __name__ == '__main__':
    main()
