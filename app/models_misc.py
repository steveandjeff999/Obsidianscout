"""
Notification system models stored in misc.db database
"""
from datetime import datetime, timezone
from app import db

class NotificationSubscription(db.Model):
    """User subscriptions for different notification types"""
    __bind_key__ = 'misc'
    __tablename__ = 'notification_subscription'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)  # References User.id from users.db
    scouting_team_number = db.Column(db.Integer, nullable=True, index=True)
    
    # Notification type and configuration
    notification_type = db.Column(db.String(50), nullable=False)  # 'match_strategy', 'match_reminder', 'alliance_update', etc.
    target_team_number = db.Column(db.Integer, nullable=True, index=True)  # Team number to track (e.g., for match strategy)
    event_code = db.Column(db.String(20), nullable=True)  # Event code to monitor
    
    # Delivery preferences
    email_enabled = db.Column(db.Boolean, default=True, nullable=False)
    push_enabled = db.Column(db.Boolean, default=True, nullable=False)
    
    # Timing configuration
    minutes_before = db.Column(db.Integer, default=20, nullable=False)  # Minutes before match to notify
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<NotificationSubscription user={self.user_id} type={self.notification_type} team={self.target_team_number}>'


class DeviceToken(db.Model):
    """Push notification device tokens for each user device"""
    __bind_key__ = 'misc'
    __tablename__ = 'device_token'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)  # References User.id from users.db
    
    # Device identification
    endpoint = db.Column(db.Text, nullable=False, unique=True)  # Web Push endpoint URL
    p256dh_key = db.Column(db.Text, nullable=False)  # Encryption key
    auth_key = db.Column(db.Text, nullable=False)  # Auth secret
    
    # Device metadata
    user_agent = db.Column(db.String(500), nullable=True)
    device_name = db.Column(db.String(100), nullable=True)  # User-friendly name
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    last_success = db.Column(db.DateTime, nullable=True)  # Last successful push
    failure_count = db.Column(db.Integer, default=0, nullable=False)  # Track failures to remove dead endpoints
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<DeviceToken user={self.user_id} device={self.device_name}>'


class NotificationLog(db.Model):
    """Log of sent notifications for history and debugging"""
    __bind_key__ = 'misc'
    __tablename__ = 'notification_log'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    subscription_id = db.Column(db.Integer, nullable=True)  # References NotificationSubscription.id
    
    # Notification details
    notification_type = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    
    # Match/event context
    match_id = db.Column(db.Integer, nullable=True)  # References Match.id from main DB
    team_number = db.Column(db.Integer, nullable=True, index=True)
    event_code = db.Column(db.String(20), nullable=True)
    
    # Delivery status
    email_sent = db.Column(db.Boolean, default=False)
    email_error = db.Column(db.Text, nullable=True)
    push_sent_count = db.Column(db.Integer, default=0)  # Number of devices successfully notified
    push_failed_count = db.Column(db.Integer, default=0)
    push_error = db.Column(db.Text, nullable=True)
    
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    
    def __repr__(self):
        return f'<NotificationLog user={self.user_id} type={self.notification_type} sent={self.sent_at}>'


class NotificationQueue(db.Model):
    """Queue for pending notifications to be sent"""
    __bind_key__ = 'misc'
    __tablename__ = 'notification_queue'
    
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(db.Integer, nullable=False, index=True)
    match_id = db.Column(db.Integer, nullable=False, index=True)
    
    # Scheduled delivery time
    scheduled_for = db.Column(db.DateTime, nullable=False, index=True)
    
    # Status tracking
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)  # 'pending', 'sent', 'failed', 'cancelled'
    attempts = db.Column(db.Integer, default=0, nullable=False)
    last_attempt = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<NotificationQueue match={self.match_id} scheduled={self.scheduled_for} status={self.status}>'
