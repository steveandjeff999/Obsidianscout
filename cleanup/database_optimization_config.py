
# Optimized Database Configuration for SQLite
# Add these settings to your app configuration

SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 1,
    'pool_timeout': 30,
    'pool_recycle': 3600,
    'max_overflow': 0,
    'connect_args': {
        'timeout': 30,
        'isolation_level': None,
        'check_same_thread': False  # Allow multi-threading
    }
}

# Performance settings
SQLALCHEMY_TRACK_MODIFICATIONS = False
SQLALCHEMY_RECORD_QUERIES = False

# SQLite-specific optimizations (applied via PRAGMA statements):
# - journal_mode = WAL (Write-Ahead Logging)
# - synchronous = NORMAL (Balance performance/safety)  
# - cache_size = -64000 (64MB cache)
# - busy_timeout = 30000 (30 second timeout)
# - temp_store = MEMORY (In-memory temporary storage)
