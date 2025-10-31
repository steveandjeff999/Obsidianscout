"""
API System Initialization
Initializes the API key system, database, and registers routes
"""
from flask import Flask
from app.api_models import api_db


def init_api_system(app: Flask):
    """Initialize the API key system with the Flask app"""
    
    # Initialize the API database
    api_db.init_app(app)
    
    # Register API key management routes
    from app.routes.api_keys import bp as api_keys_bp
    app.register_blueprint(api_keys_bp)
    
    # Register main API v1 routes
    from app.routes.api_v1 import bp as api_v1_bp
    app.register_blueprint(api_v1_bp)
    
    print(" API key system initialized successfully")
    print("   - API key management: /api/keys/")
    print("   - API v1 endpoints: /api/v1/")
    print("   - API database: apis.db")