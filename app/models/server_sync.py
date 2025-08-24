"""
Multi-Server Synchronization Models
Handles sync configuration and tracking for multiple scouting servers
"""
from datetime import datetime
from app import db
from app.utils.concurrent_models import ConcurrentModelMixin
import json


class SyncServer(ConcurrentModelMixin, db.Model):
    """Model for tracking sync servers in the network"""
    __tablename__ = 'sync_servers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # Friendly name for the server
    host = db.Column(db.String(255), nullable=False)  # IP address or domain
    port = db.Column(db.Integer, default=5000)
    protocol = db.Column(db.String(10), default='https')  # http or https
    is_active = db.Column(db.Boolean, default=True)
    is_primary = db.Column(db.Boolean, default=False)  # One server is designated as primary
    last_sync = db.Column(db.DateTime, nullable=True)
    last_ping = db.Column(db.DateTime, nullable=True)
    sync_priority = db.Column(db.Integer, default=1)  # 1 = highest priority
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    # Server metadata
    server_version = db.Column(db.String(50), nullable=True)
    server_id = db.Column(db.String(100), nullable=True)  # Unique server identifier
    
    # Sync settings
    sync_enabled = db.Column(db.Boolean, default=True)
    sync_database = db.Column(db.Boolean, default=True)
    sync_instance_files = db.Column(db.Boolean, default=True)
    sync_config_files = db.Column(db.Boolean, default=True)
    sync_uploads = db.Column(db.Boolean, default=True)
    
    # Connection tracking
    connection_timeout = db.Column(db.Integer, default=30)
    retry_attempts = db.Column(db.Integer, default=3)
    last_error = db.Column(db.Text, nullable=True)
    error_count = db.Column(db.Integer, default=0)
    
    @property
    def base_url(self):
        """Get the full base URL for this server"""
        return f"{self.protocol}://{self.host}:{self.port}"
    
    @property
    def is_healthy(self):
        """Check if server is considered healthy"""
        if not self.is_active:
            return False
        if self.error_count > 10:  # Too many errors
            return False
        if self.last_ping:
            # If we haven't pinged in 5 minutes, consider unhealthy
            time_since_ping = datetime.utcnow() - self.last_ping
            if time_since_ping.total_seconds() > 300:
                return False
        return True
    
    def update_ping(self, success=True, error_message=None):
        """Update last ping time and error tracking"""
        self.last_ping = datetime.utcnow()
        if success:
            self.error_count = max(0, self.error_count - 1)  # Decrease error count on success
            self.last_error = None
        else:
            self.error_count += 1
            self.last_error = error_message
        db.session.commit()
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'protocol': self.protocol,
            'base_url': self.base_url,
            'is_active': self.is_active,
            'is_primary': self.is_primary,
            'is_healthy': self.is_healthy,
            'last_sync': self.last_sync.isoformat() if self.last_sync else None,
            'last_ping': self.last_ping.isoformat() if self.last_ping else None,
            'sync_priority': self.sync_priority,
            'server_version': self.server_version,
            'server_id': self.server_id,
            'sync_settings': {
                'sync_enabled': self.sync_enabled,
                'sync_database': self.sync_database,
                'sync_instance_files': self.sync_instance_files,
                'sync_config_files': self.sync_config_files,
                'sync_uploads': self.sync_uploads
            },
            'error_count': self.error_count,
            'last_error': self.last_error
        }


class SyncLog(ConcurrentModelMixin, db.Model):
    """Model for tracking sync operations"""
    __tablename__ = 'sync_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    server_id = db.Column(db.Integer, db.ForeignKey('sync_servers.id'), nullable=False)
    sync_type = db.Column(db.String(50), nullable=False)  # 'database', 'files', 'config', 'full'
    direction = db.Column(db.String(10), nullable=False)  # 'push', 'pull', 'bidirectional'
    status = db.Column(db.String(20), nullable=False)  # 'pending', 'in_progress', 'completed', 'failed'
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    # Sync details
    items_synced = db.Column(db.Integer, default=0)
    total_items = db.Column(db.Integer, default=0)
    bytes_transferred = db.Column(db.BigInteger, default=0)
    sync_details = db.Column(db.Text, nullable=True)  # JSON with detailed info
    
    # Relationship
    server = db.relationship('SyncServer', backref=db.backref('sync_logs', lazy=True))
    
    @property
    def duration(self):
        """Get sync duration in seconds"""
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    @property
    def progress_percentage(self):
        """Get sync progress as percentage"""
        if self.total_items > 0:
            return min(100, (self.items_synced / self.total_items) * 100)
        return 0
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'server_id': self.server_id,
            'server_name': self.server.name if self.server else None,
            'sync_type': self.sync_type,
            'direction': self.direction,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration': self.duration,
            'progress_percentage': self.progress_percentage,
            'items_synced': self.items_synced,
            'total_items': self.total_items,
            'bytes_transferred': self.bytes_transferred,
            'error_message': self.error_message,
            'sync_details': json.loads(self.sync_details) if self.sync_details else None
        }


class FileChecksum(ConcurrentModelMixin, db.Model):
    """Model for tracking file checksums to detect changes"""
    __tablename__ = 'file_checksums'
    
    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(db.String(500), nullable=False, index=True)
    checksum = db.Column(db.String(64), nullable=False)  # SHA256 hash
    file_size = db.Column(db.BigInteger, nullable=False)
    last_modified = db.Column(db.DateTime, nullable=False)
    last_checked = db.Column(db.DateTime, default=datetime.utcnow)
    sync_status = db.Column(db.String(20), default='synced')  # 'synced', 'modified', 'new', 'deleted'
    
    @classmethod
    def get_or_create(cls, file_path, checksum, file_size, last_modified):
        """Get existing checksum record or create new one"""
        existing = cls.query.filter_by(file_path=file_path).first()
        if existing:
            # Update existing record
            if existing.checksum != checksum:
                existing.sync_status = 'modified'
            existing.checksum = checksum
            existing.file_size = file_size
            existing.last_modified = last_modified
            existing.last_checked = datetime.utcnow()
            return existing
        else:
            # Create new record
            new_record = cls(
                file_path=file_path,
                checksum=checksum,
                file_size=file_size,
                last_modified=last_modified,
                sync_status='new'
            )
            db.session.add(new_record)
            return new_record
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'file_path': self.file_path,
            'checksum': self.checksum,
            'file_size': self.file_size,
            'last_modified': self.last_modified.isoformat() if self.last_modified else None,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'sync_status': self.sync_status
        }


class SyncConfig(ConcurrentModelMixin, db.Model):
    """Model for storing sync configuration"""
    __tablename__ = 'sync_config'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), nullable=False, unique=True)
    value = db.Column(db.Text, nullable=True)
    data_type = db.Column(db.String(20), default='string')  # 'string', 'integer', 'boolean', 'json'
    description = db.Column(db.String(255), nullable=True)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    @classmethod
    def get_value(cls, key, default=None):
        """Get configuration value by key"""
        config = cls.query.filter_by(key=key).first()
        if not config:
            return default
        
        if config.data_type == 'boolean':
            return config.value.lower() in ('true', '1', 'yes')
        elif config.data_type == 'integer':
            try:
                return int(config.value)
            except (ValueError, TypeError):
                return default
        elif config.data_type == 'json':
            try:
                return json.loads(config.value)
            except (ValueError, TypeError):
                return default
        else:
            return config.value
    
    @classmethod
    def set_value(cls, key, value, data_type='string', description=None, user_id=None):
        """Set configuration value"""
        config = cls.query.filter_by(key=key).first()
        if not config:
            config = cls(key=key)
            db.session.add(config)
        
        if data_type == 'json':
            config.value = json.dumps(value)
        else:
            config.value = str(value)
        
        config.data_type = data_type
        if description:
            config.description = description
        config.last_updated = datetime.utcnow()
        config.updated_by = user_id
        
        db.session.commit()
        return config
