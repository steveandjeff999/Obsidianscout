"""
Database initialization utilities for the FRC Scouting Platform.
Handles automatic database setup and seeding with default data.
"""

import os
import json
from datetime import datetime, date
from app import db
from app.models import User, Role, Team, Event, Match

def initialize_database():
    """Initialize database with all required tables and default data"""
    print("Initializing database...")
    
    # Create all database tables
    db.create_all()
    
    # Initialize authentication system
    init_auth_system()
    
    # Initialize default configuration files
    init_default_configs()
    
    # Optionally seed with sample data
    if should_seed_sample_data():
        seed_sample_data()
    
    print("Database initialization complete!")

def init_auth_system():
    """Initialize the authentication system with roles and admin user"""
    print("Setting up authentication system...")
    
    # Create roles
    roles_data = [
        {
            'name': 'superadmin',
            'description': 'System-wide user management across all teams'
        },
        {
            'name': 'admin',
            'description': 'Full system access including user management and configuration'
        },
        {
            'name': 'analytics', 
            'description': 'Access to data analysis, visualizations, and reporting features'
        },
        {
            'name': 'scout',
            'description': 'Limited access for scouting data entry only'
        }
    ]
    
    created_roles = {}
    for role_data in roles_data:
        role = Role.query.filter_by(name=role_data['name']).first()
        if not role:
            role = Role(name=role_data['name'], description=role_data['description'])
            db.session.add(role)
            print(f"Created role: {role_data['name']}")
        else:
            print(f"Role already exists: {role_data['name']}")
        
        created_roles[role_data['name']] = role
    
    # Commit roles first
    db.session.commit()
    
    # Create admin user: admin with password password
    admin_username = 'admin'
    admin_password = 'password'
    
    admin_user = User.query.filter_by(username=admin_username).first()
    if not admin_user:
        admin_user = User(username=admin_username)
        admin_user.set_password(admin_password)
        
        # Add admin role
        admin_role = Role.query.filter_by(name='admin').first()
        if admin_role:
            admin_user.roles.append(admin_role)
        
        db.session.add(admin_user)
        db.session.commit()
        
        print(f"Created admin user: {admin_username}")
        print(f"Admin password: {admin_password}")
        print("=" * 50)
        print("IMPORTANT: Change the admin password after first login!")
        print("=" * 50)
    else:
        print(f"Admin user already exists: {admin_username}")
    
    # Check for super admin (created by separate script for security)
    superadmin_user = User.query.filter_by(username='superadmin').first()
    if superadmin_user:
        print("Super admin user exists")
    else:
        print("Super admin not found - run init_superadmin.py to create")

def init_default_configs():
    """Initialize default configuration files if they don't exist"""
    print("Checking configuration files...")
    
    # Check if pit_config.json exists
    pit_config_path = os.path.join(os.getcwd(), 'config', 'pit_config.json')
    if not os.path.exists(pit_config_path):
        print("Creating default pit scouting configuration...")
        create_default_pit_config(pit_config_path)
    
    # Check if game_config.json exists
    game_config_path = os.path.join(os.getcwd(), 'config', 'game_config.json')
    if not os.path.exists(game_config_path):
        print("Creating default game configuration...")
        create_default_game_config(game_config_path)

def create_default_pit_config(config_path):
    """Create default pit scouting configuration"""
    default_config = {
        "pit_scouting": {
            "title": "Pit Scouting",
            "description": "Collect detailed information about teams and their robots",
            "sections": [
                {
                    "id": "team_info",
                    "name": "Team Information",
                    "elements": [
                        {
                            "id": "team_number",
                            "perm_id": "team_number",
                            "name": "Team Number",
                            "type": "number",
                            "required": True,
                            "validation": {
                                "min": 1,
                                "max": 99999
                            }
                        },
                        {
                            "id": "team_name",
                            "perm_id": "team_name",
                            "name": "Team Name",
                            "type": "text",
                            "required": False
                        },
                        {
                            "id": "drive_team_experience",
                            "perm_id": "drive_team_experience",
                            "name": "Drive Team Experience",
                            "type": "select",
                            "options": [
                                {"value": "rookie", "label": "Rookie (0-1 years)"},
                                {"value": "experienced", "label": "Experienced (2-4 years)"},
                                {"value": "veteran", "label": "Veteran (5+ years)"}
                            ]
                        }
                    ]
                },
                {
                    "id": "robot_design",
                    "name": "Robot Design",
                    "elements": [
                        {
                            "id": "drivetrain_type",
                            "perm_id": "drivetrain_type",
                            "name": "Drivetrain Type",
                            "type": "select",
                            "options": [
                                {"value": "tank", "label": "Tank Drive"},
                                {"value": "mecanum", "label": "Mecanum Drive"},
                                {"value": "swerve", "label": "Swerve Drive"},
                                {"value": "other", "label": "Other"}
                            ]
                        },
                        {
                            "id": "autonomous_capability",
                            "perm_id": "autonomous_capability",
                            "name": "Autonomous Capability",
                            "type": "boolean"
                        },
                        {
                            "id": "notes",
                            "perm_id": "notes",
                            "name": "Additional Notes",
                            "type": "textarea"
                        }
                    ]
                }
            ]
        }
    }
    
    # Create config directory if it doesn't exist
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    with open(config_path, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    print(f"Created default pit scouting configuration at {config_path}")

def create_default_game_config(config_path):
    """Create default game configuration"""
    current_year = datetime.now().year
    default_config = {
        "season": current_year,
        "game_name": f"FRC {current_year} Game",
        "alliance_size": 3,
        "match_types": ["Practice", "Qualification", "Playoff"],
        "scouting_stations": 6,
        "preferred_api_source": "first",
        "api_settings": {
            "username": "",
            "auth_token": "",
            "base_url": "https://frc-api.firstinspires.org"
        },
        "tba_api_settings": {
            "auth_key": "",
            "base_url": "https://www.thebluealliance.com/api/v3"
        },
        "scoring_elements": [
            {
                "id": "auto_mobility",
                "perm_id": "auto_mobility",
                "name": "Auto Mobility",
                "type": "boolean",
                "phase": "autonomous",
                "points": 3
            },
            {
                "id": "teleop_speaker",
                "perm_id": "teleop_speaker",
                "name": "Teleop Speaker",
                "type": "number",
                "phase": "teleop",
                "points": 2
            },
            {
                "id": "endgame_climb",
                "perm_id": "endgame_climb",
                "name": "Endgame Climb",
                "type": "boolean",
                "phase": "endgame",
                "points": 4
            }
        ]
    }
    
    # Create config directory if it doesn't exist
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    with open(config_path, 'w') as f:
        json.dump(default_config, f, indent=2)
    
    print(f"Created default game configuration at {config_path}")

def should_seed_sample_data():
    """Check if we should seed with sample data (only if no teams exist)"""
    return Team.query.count() == 0

def seed_sample_data():
    """Add sample data to the database for testing"""
    print("Skipping sample data seeding - no sample data will be added")
    print("Sample data seeding complete!")

def check_database_health():
    """Check if database is properly initialized"""
    try:
        # Check if basic tables exist and have expected data
        user_count = User.query.count()
        role_count = Role.query.count()
        
        if user_count == 0:
            print("Warning: No users found in database")
            return False
        
        if role_count == 0:
            print("Warning: No roles found in database")
            return False
        
        # Check if admin user exists
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            print("Warning: Admin user not found")
            return False
        
        print(f"Database health check passed: {user_count} users, {role_count} roles")
        return True
        
    except Exception as e:
        print(f"Database health check failed: {e}")
        return False

if __name__ == '__main__':
    # This allows the module to be run directly for testing
    from app import create_app
    app = create_app()
    with app.app_context():
        initialize_database()
