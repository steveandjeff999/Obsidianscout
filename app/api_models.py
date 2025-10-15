"""
API Key Models for separate apis.db database
This module contains all models for API key management and usage tracking.
"""
from datetime import datetime, timezone, timedelta
from flask import current_app
from flask_sqlalchemy import SQLAlchemy
import secrets
import string
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float, JSON
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os

# Create a separate database for API keys
Base = declarative_base()

class ApiKey(Base):
    """Model for API Keys stored in apis.db"""
    __tablename__ = 'api_keys'
    
    id = Column(Integer, primary_key=True)
    key_hash = Column(String(128), unique=True, nullable=False, index=True)  # SHA-256 hash of the key
    key_prefix = Column(String(8), nullable=False)  # First 8 characters for identification
    name = Column(String(100), nullable=False)  # Human-readable name for the key
    description = Column(Text, nullable=True)  # Optional description
    team_number = Column(Integer, nullable=False, index=True)  # Associated team number
    created_by = Column(String(80), nullable=False)  # Username who created it
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Permissions and limitations
    permissions = Column(JSON, default=dict)  # JSON object for permissions
    rate_limit_per_hour = Column(Integer, default=1000)  # API calls per hour
    
    # Usage statistics
    total_requests = Column(Integer, default=0)
    successful_requests = Column(Integer, default=0)
    failed_requests = Column(Integer, default=0)
    
    def __repr__(self):
        return f'<ApiKey {self.key_prefix}... for Team {self.team_number}>'
    
    @staticmethod
    def generate_api_key():
        """Generate a secure API key"""
        # Generate a random 32-character string
        alphabet = string.ascii_letters + string.digits
        key = ''.join(secrets.choice(alphabet) for _ in range(32))
        return f"sk_live_{key}"
    
    @staticmethod
    def hash_key(key):
        """Hash an API key for secure storage"""
        import hashlib
        return hashlib.sha256(key.encode()).hexdigest()
    
    @staticmethod
    def get_prefix(key):
        """Get the first 8 characters of the key for identification"""
        return key[:8] if len(key) >= 8 else key
    
    def to_dict(self, include_stats=True):
        """Convert to dictionary for API responses"""
        data = {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'key_prefix': self.key_prefix,
            'team_number': self.team_number,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_active': self.is_active,
            'permissions': self.permissions,
            'rate_limit_per_hour': self.rate_limit_per_hour
        }
        
        if include_stats:
            data.update({
                'total_requests': self.total_requests,
                'successful_requests': self.successful_requests,
                'failed_requests': self.failed_requests
            })
        
        return data


class ApiUsage(Base):
    """Model for tracking API usage stored in apis.db"""
    __tablename__ = 'api_usage'
    
    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, nullable=False, index=True)  # Reference to ApiKey
    endpoint = Column(String(200), nullable=False)
    method = Column(String(10), nullable=False)  # GET, POST, etc.
    status_code = Column(Integer, nullable=False)
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(Text, nullable=True)
    request_size = Column(Integer, default=0)  # Request body size in bytes
    response_size = Column(Integer, default=0)  # Response size in bytes
    response_time_ms = Column(Float, default=0)  # Response time in milliseconds
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    error_message = Column(Text, nullable=True)  # For failed requests
    
    def __repr__(self):
        return f'<ApiUsage {self.method} {self.endpoint} - {self.status_code}>'
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'api_key_id': self.api_key_id,
            'endpoint': self.endpoint,
            'method': self.method,
            'status_code': self.status_code,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'request_size': self.request_size,
            'response_size': self.response_size,
            'response_time_ms': self.response_time_ms,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'error_message': self.error_message
        }


class ApiRateLimit(Base):
    """Model for tracking rate limits stored in apis.db"""
    __tablename__ = 'api_rate_limits'
    
    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, nullable=False, index=True)  # Reference to ApiKey
    window_start = Column(DateTime, nullable=False, index=True)  # Start of the time window
    window_duration = Column(Integer, default=3600)  # Window duration in seconds (default 1 hour)
    request_count = Column(Integer, default=0)  # Requests made in this window
    
    def __repr__(self):
        return f'<ApiRateLimit Key {self.api_key_id} - {self.request_count} requests>'


class ApiDatabase:
    """Utility class to manage the separate APIs database"""
    
    def __init__(self, app=None):
        self.engine = None
        self.Session = None
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize the API database with the Flask app"""
        # Create the apis.db path
        apis_db_path = os.path.join(app.instance_path, 'apis.db')
        
        # Ensure the instance directory exists
        os.makedirs(app.instance_path, exist_ok=True)
        
        # Create SQLAlchemy engine for the APIs database
        self.engine = create_engine(f'sqlite:///{apis_db_path}', echo=False)
        self.Session = sessionmaker(bind=self.engine)
        
        # Create all tables
        Base.metadata.create_all(self.engine)
        
        # Store the database instance on the app
        app.api_db = self
    
    def get_session(self):
        """Get a database session"""
        return self.Session()
    
    def close_session(self, session):
        """Close a database session"""
        session.close()


# Initialize the API database instance
api_db = ApiDatabase()


def get_api_key_by_hash(key_hash):
    """Get an API key by its hash"""
    session = api_db.get_session()
    try:
        return session.query(ApiKey).filter_by(key_hash=key_hash, is_active=True).first()
    finally:
        api_db.close_session(session)


def get_team_api_keys(team_number):
    """Get all API keys for a team"""
    session = api_db.get_session()
    try:
        return session.query(ApiKey).filter_by(team_number=team_number).order_by(ApiKey.created_at.desc()).all()
    finally:
        api_db.close_session(session)


def count_team_api_keys(team_number):
    """Count active API keys for a team"""
    session = api_db.get_session()
    try:
        return session.query(ApiKey).filter_by(team_number=team_number, is_active=True).count()
    finally:
        api_db.close_session(session)


def create_api_key(name, team_number, created_by, description=None, permissions=None, rate_limit=1000, expires_days=None):
    """Create a new API key"""
    # Check if team already has 5 keys
    if count_team_api_keys(team_number) >= 5:
        raise ValueError("Team already has the maximum of 5 API keys")
    
    # Generate the key and hash it
    key = ApiKey.generate_api_key()
    key_hash = ApiKey.hash_key(key)
    key_prefix = ApiKey.get_prefix(key)
    
    # Set expiration if specified
    expires_at = None
    if expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
    
    # Create the API key record
    api_key = ApiKey(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        description=description,
        team_number=team_number,
        created_by=created_by,
        permissions=permissions or {},
        rate_limit_per_hour=rate_limit,
        expires_at=expires_at
    )
    
    session = api_db.get_session()
    try:
        session.add(api_key)
        session.commit()
        
        # Return both the key (only shown once) and the record
        result = api_key.to_dict()
        result['key'] = key  # Only returned on creation
        return result
    finally:
        api_db.close_session(session)


def deactivate_api_key(api_key_id, team_number):
    """Deactivate an API key (soft delete)"""
    session = api_db.get_session()
    try:
        api_key = session.query(ApiKey).filter_by(id=api_key_id, team_number=team_number).first()
        if not api_key:
            return False
        
        api_key.is_active = False
        session.commit()
        return True
    finally:
        api_db.close_session(session)


def reactivate_api_key(api_key_id, team_number):
    """Reactivate a previously deactivated API key"""
    session = api_db.get_session()
    try:
        api_key = session.query(ApiKey).filter_by(id=api_key_id, team_number=team_number).first()
        if not api_key:
            return False

        api_key.is_active = True
        session.commit()
        return True
    finally:
        api_db.close_session(session)


def delete_api_key_permanently(api_key_id, team_number):
    """Permanently delete an API key record from the apis.db database."""
    session = api_db.get_session()
    try:
        api_key = session.query(ApiKey).filter_by(id=api_key_id, team_number=team_number).first()
        if not api_key:
            return False

        session.delete(api_key)
        session.commit()
        return True
    finally:
        api_db.close_session(session)


def record_api_usage(api_key_id, endpoint, method, status_code, ip_address=None, user_agent=None, 
                    request_size=0, response_size=0, response_time_ms=0, error_message=None):
    """Record API usage for analytics and monitoring"""
    usage_record = ApiUsage(
        api_key_id=api_key_id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        ip_address=ip_address,
        user_agent=user_agent,
        request_size=request_size,
        response_size=response_size,
        response_time_ms=response_time_ms,
        error_message=error_message
    )
    
    session = api_db.get_session()
    try:
        session.add(usage_record)
        
        # Update API key statistics
        api_key = session.query(ApiKey).filter_by(id=api_key_id).first()
        if api_key:
            api_key.total_requests += 1
            api_key.last_used_at = datetime.now(timezone.utc)
            if 200 <= status_code < 300:
                api_key.successful_requests += 1
            else:
                api_key.failed_requests += 1
        
        session.commit()
    finally:
        api_db.close_session(session)


def check_rate_limit(api_key_id, rate_limit_per_hour):
    """Check if an API key has exceeded its rate limit"""
    current_time = datetime.now(timezone.utc)
    window_start = current_time.replace(minute=0, second=0, microsecond=0)
    
    session = api_db.get_session()
    try:
        # Get or create rate limit record for this hour
        rate_limit_record = session.query(ApiRateLimit).filter_by(
            api_key_id=api_key_id, 
            window_start=window_start
        ).first()
        
        if not rate_limit_record:
            rate_limit_record = ApiRateLimit(
                api_key_id=api_key_id,
                window_start=window_start,
                request_count=0
            )
            session.add(rate_limit_record)
        
        # Check if rate limit is exceeded
        if rate_limit_record.request_count >= rate_limit_per_hour:
            return False, rate_limit_record.request_count
        
        # Increment the count
        rate_limit_record.request_count += 1
        session.commit()
        
        return True, rate_limit_record.request_count
    finally:
        api_db.close_session(session)


def get_api_usage_stats(api_key_id, days=30):
    """Get usage statistics for an API key"""
    start_date = datetime.now(timezone.utc) - timedelta(days=days)
    
    session = api_db.get_session()
    try:
        usage_records = session.query(ApiUsage).filter(
            ApiUsage.api_key_id == api_key_id,
            ApiUsage.timestamp >= start_date
        ).all()
        
        return [record.to_dict() for record in usage_records]
    finally:
        api_db.close_session(session)


def cleanup_old_usage_records(days_to_keep=90):
    """Clean up old usage records to prevent database bloat"""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
    
    session = api_db.get_session()
    try:
        deleted_count = session.query(ApiUsage).filter(ApiUsage.timestamp < cutoff_date).delete()
        session.commit()
        return deleted_count
    finally:
        api_db.close_session(session)
