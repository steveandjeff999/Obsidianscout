import os
import sys
import importlib
import inspect
import sqlite3
import json
import traceback
from flask import current_app
from app import db
from app.utils.config_manager import get_current_game_config
from app.models import User, Role, Team, Event, Match, ScoutingData

class SystemCheck:
    """
    Class to perform various system checks on the application.
    Used by administrators to verify the integrity of the system.
    """
    
    def __init__(self):
        self.results = {
            "database": {"status": "unknown", "details": []},
            "config": {"status": "unknown", "details": []},
            "routes": {"status": "unknown", "details": []},
            "models": {"status": "unknown", "details": []},
            "overall": {"status": "unknown", "summary": ""}
        }
    
    def check_database_integrity(self):
        """Check database integrity and connections"""
        try:
            # Test database connection
            db_uri = current_app.config['SQLALCHEMY_DATABASE_URI']
            self.results["database"]["details"].append({"name": "Database URI", "status": "pass", "message": "Database URI is configured."})
            
            # Check if database file exists (for SQLite)
            if 'sqlite:///' in db_uri:
                db_path = db_uri.replace('sqlite:///', '')
                if os.path.exists(db_path):
                    self.results["database"]["details"].append({"name": "Database File", "status": "pass", "message": f"Database file exists at {db_path}"})
                else:
                    self.results["database"]["details"].append({"name": "Database File", "status": "fail", "message": f"Database file does not exist at {db_path}"})
            
            # Test query execution
            user_count = User.query.count()
            self.results["database"]["details"].append({"name": "Query Execution", "status": "pass", "message": f"Database query executed successfully. User count: {user_count}"})
            
            # Check for admin users
            admin_role = Role.query.filter_by(name='admin').first()
            if admin_role:
                admin_count = len(admin_role.users)
                if admin_count > 0:
                    self.results["database"]["details"].append({"name": "Admin Users", "status": "pass", "message": f"Found {admin_count} admin users."})
                else:
                    self.results["database"]["details"].append({"name": "Admin Users", "status": "warn", "message": "No admin users found."})
            else:
                self.results["database"]["details"].append({"name": "Admin Role", "status": "fail", "message": "Admin role not found in the database."})
            
            # Check for integrity issues using direct SQLite connection for SQLite databases
            if 'sqlite:///' in db_uri:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                integrity_result = cursor.fetchone()[0]
                
                if integrity_result == "ok":
                    self.results["database"]["details"].append({"name": "Integrity Check", "status": "pass", "message": "SQLite integrity check passed."})
                else:
                    self.results["database"]["details"].append({"name": "Integrity Check", "status": "fail", "message": f"SQLite integrity check failed: {integrity_result}"})
                
                conn.close()
            
            # Set overall database status
            failures = sum(1 for item in self.results["database"]["details"] if item["status"] == "fail")
            warnings = sum(1 for item in self.results["database"]["details"] if item["status"] == "warn")
            
            if failures > 0:
                self.results["database"]["status"] = "fail"
            elif warnings > 0:
                self.results["database"]["status"] = "warn"
            else:
                self.results["database"]["status"] = "pass"
                
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            self.results["database"]["details"].append({"name": "Database Error", "status": "fail", "message": str(e)})
            self.results["database"]["status"] = "fail"
    
    def check_config_integrity(self):
        """Check configuration files and settings"""
        try:
            # Check if game config exists
            config_path = os.path.join(os.getcwd(), 'config', 'game_config.json')
            if os.path.exists(config_path):
                self.results["config"]["details"].append({"name": "Game Config", "status": "pass", "message": "Game configuration file exists."})
                
                # Try to parse game config
                game_config = None
                config_content = ""
                
                try:
                    with open(config_path, 'r') as f:
                        config_content = f.read()
                except Exception as e:
                    self.results["config"]["details"].append({
                        "name": "File Reading", 
                        "status": "fail", 
                        "message": f"Error reading game config file: {str(e)}"
                    })
                
                if config_content:
                    try:
                        game_config = json.loads(config_content)
                        self.results["config"]["details"].append({
                            "name": "JSON Validation", 
                            "status": "pass", 
                            "message": "Game configuration file is valid JSON."
                        })
                    except json.JSONDecodeError as e:
                        line_col = f"line {e.lineno}, column {e.colno}"
                        self.results["config"]["details"].append({
                            "name": "JSON Validation", 
                            "status": "fail", 
                            "message": f"Game configuration file has JSON syntax errors: {e.msg} at {line_col}"
                        })
                        
                        # Try to continue with syntax checking even if JSON is invalid
                        try:
                            # Check for unclosed brackets and braces
                            brackets = {'(': ')', '[': ']', '{': '}'}
                            stack = []
                            for i, char in enumerate(config_content):
                                if char in brackets.keys():
                                    stack.append(char)
                                elif char in brackets.values():
                                    if not stack or brackets[stack.pop()] != char:
                                        self.results["config"]["details"].append({
                                            "name": "JSON Structure", 
                                            "status": "fail", 
                                            "message": f"Mismatched bracket/brace at position {i}: '{char}'"
                                        })
                            
                            if stack:
                                unclosed = ''.join(stack)
                                self.results["config"]["details"].append({
                                    "name": "JSON Structure", 
                                    "status": "fail", 
                                    "message": f"Unclosed brackets/braces: {unclosed}"
                                })
                        except Exception as inner_e:
                            self.results["config"]["details"].append({
                                "name": "JSON Structure Analysis", 
                                "status": "fail", 
                                "message": f"Error analyzing JSON structure: {str(inner_e)}"
                            })
                        
                        # Create an empty config so we can continue with other checks
                        game_config = {}
                    # Check required keys in game config
                    required_keys = ['game_name', 'version', 'current_event_code']
                    missing_keys = [key for key in required_keys if key not in game_config]
                    
                    if missing_keys:
                        self.results["config"]["details"].append({
                            "name": "Game Config Structure", 
                            "status": "warn", 
                            "message": f"Missing required keys in game config: {', '.join(missing_keys)}"
                        })
                    else:
                        self.results["config"]["details"].append({
                            "name": "Game Config Structure", 
                            "status": "pass", 
                            "message": "Game configuration has all required keys."
                        })
                    
                    # Check core game configuration structure
                    required_sections = ['auto_period', 'teleop_period', 'endgame_period']
                    missing_sections = [section for section in required_sections if section not in game_config]
                    
                    if missing_sections:
                        self.results["config"]["details"].append({
                            "name": "Game Periods", 
                            "status": "fail", 
                            "message": f"Missing required game periods: {', '.join(missing_sections)}"
                        })
                    else:
                        # Check that each period has a duration and scoring elements
                        period_issues = []
                        for period in required_sections:
                            period_config = game_config.get(period, {})
                            if 'duration_seconds' not in period_config:
                                period_issues.append(f"{period} is missing duration_seconds")
                            if 'scoring_elements' not in period_config:
                                period_issues.append(f"{period} is missing scoring_elements")
                            elif not isinstance(period_config['scoring_elements'], list):
                                period_issues.append(f"{period} scoring_elements is not a list")
                            elif len(period_config['scoring_elements']) == 0:
                                period_issues.append(f"{period} has no scoring elements defined")
                            
                        if period_issues:
                            self.results["config"]["details"].append({
                                "name": "Game Period Structure", 
                                "status": "warn", 
                                "message": f"Issues with game periods: {', '.join(period_issues)}"
                            })
                        else:
                            self.results["config"]["details"].append({
                                "name": "Game Period Structure", 
                                "status": "pass", 
                                "message": "All game periods are properly configured."
                            })
                    
                    # Check scoring elements for unique IDs
                    all_element_ids = []
                    duplicate_ids = set()
                    
                    for period in required_sections:
                        if period in game_config and 'scoring_elements' in game_config[period]:
                            for element in game_config[period]['scoring_elements']:
                                if 'id' in element:
                                    if element['id'] in all_element_ids:
                                        duplicate_ids.add(element['id'])
                                    all_element_ids.append(element['id'])
                    
                    if duplicate_ids:
                        self.results["config"]["details"].append({
                            "name": "Scoring Element IDs", 
                            "status": "fail", 
                            "message": f"Duplicate scoring element IDs found: {', '.join(duplicate_ids)}"
                        })
                    else:
                        self.results["config"]["details"].append({
                            "name": "Scoring Element IDs", 
                            "status": "pass", 
                            "message": "All scoring element IDs are unique."
                        })
                    
                    # Check game pieces
                    if 'game_pieces' in game_config:
                        game_pieces = game_config['game_pieces']
                        if not isinstance(game_pieces, list):
                            self.results["config"]["details"].append({
                                "name": "Game Pieces", 
                                "status": "warn", 
                                "message": "Game pieces is not a list."
                            })
                        elif len(game_pieces) == 0:
                            self.results["config"]["details"].append({
                                "name": "Game Pieces", 
                                "status": "warn", 
                                "message": "No game pieces defined."
                            })
                        else:
                            piece_ids = []
                            piece_issues = []
                            for piece in game_pieces:
                                if 'id' not in piece:
                                    piece_issues.append("Game piece missing ID")
                                elif piece['id'] in piece_ids:
                                    piece_issues.append(f"Duplicate game piece ID: {piece['id']}")
                                else:
                                    piece_ids.append(piece['id'])
                                
                                if 'name' not in piece:
                                    piece_issues.append(f"Game piece {piece.get('id', 'unknown')} missing name")
                            
                            if piece_issues:
                                self.results["config"]["details"].append({
                                    "name": "Game Piece Validation", 
                                    "status": "warn", 
                                    "message": f"Issues with game pieces: {', '.join(piece_issues)}"
                                })
                            else:
                                self.results["config"]["details"].append({
                                    "name": "Game Piece Validation", 
                                    "status": "pass", 
                                    "message": f"All {len(game_pieces)} game pieces are properly configured."
                                })
                                
                            # Check that game piece references are valid
                            referenced_pieces = []
                            for period in ['auto_period', 'teleop_period', 'endgame_period']:
                                if period in game_config and 'scoring_elements' in game_config[period]:
                                    for element in game_config[period]['scoring_elements']:
                                        if 'game_piece_id' in element:
                                            referenced_pieces.append(element['game_piece_id'])
                            
                            invalid_references = [piece_id for piece_id in referenced_pieces if piece_id not in piece_ids]
                            if invalid_references:
                                self.results["config"]["details"].append({
                                    "name": "Game Piece References", 
                                    "status": "fail", 
                                    "message": f"Invalid game piece references found: {', '.join(invalid_references)}"
                                })
                            else:
                                self.results["config"]["details"].append({
                                    "name": "Game Piece References", 
                                    "status": "pass", 
                                    "message": "All game piece references are valid."
                                })
                    else:
                        self.results["config"]["details"].append({
                            "name": "Game Pieces", 
                            "status": "warn", 
                            "message": "Game pieces section missing from config."
                        })
                    
                    # Check alliance size
                    if 'alliance_size' in game_config:
                        alliance_size = game_config['alliance_size']
                        if isinstance(alliance_size, int) and alliance_size > 0:
                            self.results["config"]["details"].append({
                                "name": "Alliance Size", 
                                "status": "pass", 
                                "message": f"Alliance size is set to {alliance_size}."
                            })
                        else:
                            self.results["config"]["details"].append({
                                "name": "Alliance Size", 
                                "status": "warn", 
                                "message": "Alliance size must be a positive integer."
                            })
                    else:
                        self.results["config"]["details"].append({
                            "name": "Alliance Size", 
                            "status": "warn", 
                            "message": "Alliance size not specified in config."
                        })
                    
                    # Check data analysis configuration
                    if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
                        metrics = game_config['data_analysis']['key_metrics']
                        if not isinstance(metrics, list):
                            self.results["config"]["details"].append({
                                "name": "Key Metrics", 
                                "status": "warn", 
                                "message": "Key metrics is not a list."
                            })
                        elif len(metrics) == 0:
                            self.results["config"]["details"].append({
                                "name": "Key Metrics", 
                                "status": "warn", 
                                "message": "No key metrics defined."
                            })
                        else:
                            metric_issues = []
                            for metric in metrics:
                                # Basic required keys for all metrics
                                required_metric_keys = ['id', 'name']
                                missing_keys = [key for key in required_metric_keys if key not in metric]
                                
                                # Only require formula if the metric is not auto-generated
                                if not metric.get('auto_generated', False) and 'formula' not in metric:
                                    missing_keys.append('formula')
                                
                                if missing_keys:
                                    metric_issues.append(f"Metric {metric.get('id', 'unknown')} missing keys: {', '.join(missing_keys)}")
                            
                            if metric_issues:
                                self.results["config"]["details"].append({
                                    "name": "Key Metrics Validation", 
                                    "status": "warn", 
                                    "message": f"Issues with key metrics: {', '.join(metric_issues)}"
                                })
                            else:
                                self.results["config"]["details"].append({
                                    "name": "Key Metrics Validation", 
                                    "status": "pass", 
                                    "message": f"All {len(metrics)} key metrics are properly configured."
                                })
                    
                    # Check current event
                    try:
                        current_event_code = game_config.get('current_event_code')
                        if current_event_code:
                            # Use the team-isolation helper which handles case-insensitive and
                            # alliance-aware lookups so the system check matches UI discovery
                            try:
                                from app.utils.team_isolation import get_event_by_code
                                event = get_event_by_code(current_event_code)
                            except Exception:
                                event = Event.query.filter_by(code=current_event_code).first()

                            if event:
                                self.results["config"]["details"].append({
                                    "name": "Current Event", 
                                    "status": "pass", 
                                    "message": f"Current event '{current_event_code}' found in database."
                                })
                            else:
                                self.results["config"]["details"].append({
                                    "name": "Current Event", 
                                    "status": "warn", 
                                    "message": f"Current event '{current_event_code}' not found in database."
                                })
                    except Exception as e:
                        # This catches any other exceptions when processing valid JSON
                        self.results["config"]["details"].append({
                            "name": "Config Processing Error", 
                            "status": "fail", 
                            "message": f"Error processing game config: {str(e)}"
                        })
            else:
                self.results["config"]["details"].append({
                    "name": "Game Config", 
                    "status": "fail", 
                    "message": "Game configuration file does not exist."
                })
            
            # Check if backup config exists
            backup_config_path = os.path.join(os.getcwd(), 'config', 'game_config_backup.json')
            if os.path.exists(backup_config_path):
                self.results["config"]["details"].append({
                    "name": "Backup Config", 
                    "status": "pass", 
                    "message": "Backup configuration file exists."
                })
                
                # Check if backup is valid JSON
                backup_content = ""
                try:
                    with open(backup_config_path, 'r') as f:
                        backup_content = f.read()
                except Exception as e:
                    self.results["config"]["details"].append({
                        "name": "Backup File Reading", 
                        "status": "fail", 
                        "message": f"Error reading backup config file: {str(e)}"
                    })
                
                if backup_content:
                    try:
                        json.loads(backup_content)
                        self.results["config"]["details"].append({
                            "name": "Backup Config Parse", 
                            "status": "pass", 
                            "message": "Backup configuration file is valid JSON."
                        })
                    except json.JSONDecodeError as e:
                        self.results["config"]["details"].append({
                            "name": "Backup Config Parse", 
                            "status": "warn", 
                            "message": f"Backup configuration file is not valid JSON: {e.msg} at line {e.lineno}, column {e.colno}."
                        })
            else:
                self.results["config"]["details"].append({
                    "name": "Backup Config", 
                    "status": "warn", 
                    "message": "No backup configuration file found."
                })
            
            # Check SSL configuration
            ssl_dir = os.path.join(os.getcwd(), 'ssl')
            cert_file = os.path.join(ssl_dir, 'cert.pem')
            key_file = os.path.join(ssl_dir, 'key.pem')
            
            if os.path.exists(cert_file) and os.path.exists(key_file):
                self.results["config"]["details"].append({
                    "name": "SSL Configuration", 
                    "status": "pass", 
                    "message": "SSL certificate and key found."
                })
            else:
                self.results["config"]["details"].append({
                    "name": "SSL Configuration", 
                    "status": "warn", 
                    "message": "SSL certificate and/or key missing. HTTPS will not be available."
                })
            
            # Set overall config status
            failures = sum(1 for item in self.results["config"]["details"] if item["status"] == "fail")
            warnings = sum(1 for item in self.results["config"]["details"] if item["status"] == "warn")
            
            if failures > 0:
                self.results["config"]["status"] = "fail"
            elif warnings > 0:
                self.results["config"]["status"] = "warn"
            else:
                self.results["config"]["status"] = "pass"
                
        except Exception as e:
            self.results["config"]["details"].append({"name": "Config Error", "status": "fail", "message": str(e)})
            self.results["config"]["status"] = "fail"
    
    def check_routes_integrity(self):
        """Check that all routes are working properly"""
        try:
            # Identify all blueprints and routes
            app = current_app._get_current_object()
            
            # Track issues
            route_issues = []
            
            # Check all blueprints and routes
            for rule in app.url_map.iter_rules():
                try:
                    endpoint = rule.endpoint
                    blueprint = endpoint.split('.')[0] if '.' in endpoint else None
                    
                    # Skip static routes
                    if endpoint == 'static':
                        continue
                    
                    # Get the view function
                    if '.' in endpoint:
                        view_func = app.view_functions.get(endpoint)
                    else:
                        view_func = app.view_functions.get(endpoint)
                    
                    if view_func is None:
                        route_issues.append({
                            "name": f"Route {rule}", 
                            "status": "fail", 
                            "message": f"View function not found for endpoint {endpoint}"
                        })
                        continue
                    
                    # Check if the view function is wrapped properly
                    if hasattr(view_func, '__wrapped__'):
                        self.results["routes"]["details"].append({
                            "name": f"Route {rule}", 
                            "status": "pass", 
                            "message": f"Route {rule} has a valid view function."
                        })
                    else:
                        self.results["routes"]["details"].append({
                            "name": f"Route {rule}", 
                            "status": "pass", 
                            "message": f"Route {rule} has a valid view function."
                        })
                        
                except Exception as e:
                    route_issues.append({
                        "name": f"Route {rule}", 
                        "status": "fail", 
                        "message": f"Error checking route: {str(e)}"
                    })
            
            # Add any issues found
            for issue in route_issues:
                self.results["routes"]["details"].append(issue)
            
            # Set overall routes status
            failures = sum(1 for item in self.results["routes"]["details"] if item["status"] == "fail")
            warnings = sum(1 for item in self.results["routes"]["details"] if item["status"] == "warn")
            
            if failures > 0:
                self.results["routes"]["status"] = "fail"
            elif warnings > 0:
                self.results["routes"]["status"] = "warn"
            else:
                self.results["routes"]["status"] = "pass"
                
        except Exception as e:
            self.results["routes"]["details"].append({"name": "Routes Error", "status": "fail", "message": str(e)})
            self.results["routes"]["status"] = "fail"
    
    def check_models_integrity(self):
        """Check models and their relationships"""
        try:
            # List all model classes
            model_classes = [
                User, Role, Team, Event, Match, ScoutingData
                # Add more models as needed
            ]
            
            # Check each model
            for model_class in model_classes:
                try:
                    # Try to access the model's table
                    table_name = model_class.__tablename__
                    
                    # Check if we can query the model
                    count = model_class.query.count()
                    
                    self.results["models"]["details"].append({
                        "name": f"Model {model_class.__name__}", 
                        "status": "pass", 
                        "message": f"Model {model_class.__name__} is valid. Count: {count}"
                    })
                except Exception as e:
                    try:
                        db.session.rollback()
                    except Exception:
                        pass
                    self.results["models"]["details"].append({
                        "name": f"Model {model_class.__name__}", 
                        "status": "fail", 
                        "message": f"Error with model {model_class.__name__}: {str(e)}"
                    })
            
            # Check relationships (example with User and Role)
            try:
                user = User.query.first()
                if user:
                    # Access roles relationship
                    roles = user.get_role_names()
                    self.results["models"]["details"].append({
                        "name": "User-Role Relationship", 
                        "status": "pass", 
                        "message": f"User-Role relationship is working. User {user.username} has roles: {', '.join(roles)}"
                    })
            except Exception as e:
                self.results["models"]["details"].append({
                    "name": "User-Role Relationship", 
                    "status": "fail", 
                    "message": f"Error with User-Role relationship: {str(e)}"
                })
            
            # Set overall models status
            failures = sum(1 for item in self.results["models"]["details"] if item["status"] == "fail")
            warnings = sum(1 for item in self.results["models"]["details"] if item["status"] == "warn")
            
            if failures > 0:
                self.results["models"]["status"] = "fail"
            elif warnings > 0:
                self.results["models"]["status"] = "warn"
            else:
                self.results["models"]["status"] = "pass"
                
        except Exception as e:
            self.results["models"]["details"].append({"name": "Models Error", "status": "fail", "message": str(e)})
            self.results["models"]["status"] = "fail"
    
    def test_config_loading(self):
        """Test that the application can load and use the configuration properly"""
        try:
            # First try to load the game config directly from file if not in current_app
            game_config = None
            
            if 'GAME_CONFIG' in current_app.config:
                game_config = current_app.config['GAME_CONFIG']
                self.results["config"]["details"].append({
                    "name": "Config Loading", 
                    "status": "pass", 
                    "message": "GAME_CONFIG found in application configuration."
                })
            else:
                self.results["config"]["details"].append({
                    "name": "Config Loading", 
                    "status": "warn", 
                    "message": "GAME_CONFIG not found in application configuration. Trying to load directly from file."
                })
                
                # Try to load the config manually
                try:
                    config_path = os.path.join(os.getcwd(), 'config', 'game_config.json')
                    if os.path.exists(config_path):
                        with open(config_path, 'r') as f:
                            game_config = json.load(f)
                        self.results["config"]["details"].append({
                            "name": "Manual Config Loading", 
                            "status": "pass", 
                            "message": "Successfully loaded game configuration from file."
                        })
                    else:
                        self.results["config"]["details"].append({
                            "name": "Manual Config Loading", 
                            "status": "fail", 
                            "message": "Game configuration file not found."
                        })
                        return
                except json.JSONDecodeError as e:
                    self.results["config"]["details"].append({
                        "name": "Manual Config Loading", 
                        "status": "fail", 
                        "message": f"Failed to load game configuration: JSON error - {e.msg}"
                    })
                    return
                except Exception as e:
                    self.results["config"]["details"].append({
                        "name": "Manual Config Loading", 
                        "status": "fail", 
                        "message": f"Failed to load game configuration: {str(e)}"
                    })
                    return
            
            if not game_config:
                self.results["config"]["details"].append({
                    "name": "Config Loading", 
                    "status": "fail", 
                    "message": "Could not load game configuration."
                })
                return
            
            # Check that critical sections can be accessed without errors
            game_config = get_current_game_config()
            
            # Test accessing game periods - continue even if some periods aren't found
            test_periods = []
            period_errors = []
            for period in ['auto_period', 'teleop_period', 'endgame_period']:
                try:
                    if period in game_config:
                        duration = game_config[period].get('duration_seconds')
                        elements = game_config[period].get('scoring_elements', [])
                        test_periods.append({
                            'name': period,
                            'duration': duration,
                            'elements_count': len(elements)
                        })
                    else:
                        period_errors.append(f"{period} not found in game config")
                except Exception as e:
                    period_errors.append(f"Error accessing {period}: {str(e)}")
            
            if test_periods:
                self.results["config"]["details"].append({
                    "name": "Period Access", 
                    "status": "pass" if not period_errors else "warn", 
                    "message": f"Accessed game periods: {', '.join([p['name'] for p in test_periods])}"
                })
            
            if period_errors:
                self.results["config"]["details"].append({
                    "name": "Period Access Issues", 
                    "status": "warn", 
                    "message": f"Issues accessing periods: {', '.join(period_errors)}"
                })
            
            # Test formula parsing from key metrics - continue even if there are issues
            metric_count = 0
            metric_errors = []
            
            if 'data_analysis' in game_config:
                if 'key_metrics' in game_config['data_analysis']:
                    try:
                        metrics = game_config['data_analysis']['key_metrics']
                        if isinstance(metrics, list):
                            for i, metric in enumerate(metrics):
                                try:
                                    if 'formula' in metric:
                                        formula = metric['formula']
                                        if isinstance(formula, str):
                                            metric_count += 1
                                        else:
                                            metric_errors.append(f"Formula for metric #{i+1} is not a string")
                                    else:
                                        metric_errors.append(f"Missing formula in metric #{i+1}")
                                except Exception as e:
                                    metric_errors.append(f"Error processing metric #{i+1}: {str(e)}")
                        else:
                            metric_errors.append("Key metrics is not a list")
                    except Exception as e:
                        metric_errors.append(f"Error accessing key metrics: {str(e)}")
                else:
                    metric_errors.append("No 'key_metrics' found in data_analysis section")
            else:
                metric_errors.append("No 'data_analysis' section found in config")
            
            if metric_count > 0:
                self.results["config"]["details"].append({
                    "name": "Formula Access", 
                    "status": "pass" if not metric_errors else "warn", 
                    "message": f"Successfully accessed formulas in {metric_count} key metrics."
                })
            
            if metric_errors:
                self.results["config"]["details"].append({
                    "name": "Formula Access Issues", 
                    "status": "warn", 
                    "message": f"Issues with key metrics: {', '.join(metric_errors[:3])}" + 
                              (f" and {len(metric_errors) - 3} more issues" if len(metric_errors) > 3 else "")
                })
                
            # Check game pieces - continue even if there are issues
            piece_count = 0
            piece_errors = []
            
            if 'game_pieces' in game_config:
                try:
                    pieces = game_config['game_pieces']
                    if isinstance(pieces, list):
                        piece_names = []
                        for i, piece in enumerate(pieces):
                            try:
                                if 'name' in piece:
                                    piece_names.append(piece['name'])
                                    piece_count += 1
                                else:
                                    piece_errors.append(f"Game piece #{i+1} missing name")
                            except Exception as e:
                                piece_errors.append(f"Error processing game piece #{i+1}: {str(e)}")
                        
                        if piece_count > 0:
                            self.results["config"]["details"].append({
                                "name": "Game Pieces Access", 
                                "status": "pass" if not piece_errors else "warn", 
                                "message": f"Successfully accessed {piece_count} game pieces" + 
                                          (f": {', '.join(piece_names[:5])}" if piece_names else "")
                            })
                    else:
                        piece_errors.append("Game pieces is not a list")
                except Exception as e:
                    piece_errors.append(f"Error accessing game pieces: {str(e)}")
            else:
                piece_errors.append("No 'game_pieces' section found in config")
            
            if piece_errors:
                self.results["config"]["details"].append({
                    "name": "Game Pieces Access Issues", 
                    "status": "warn", 
                    "message": f"Issues with game pieces: {', '.join(piece_errors[:3])}" + 
                              (f" and {len(piece_errors) - 3} more issues" if len(piece_errors) > 3 else "")
                })
                
        except Exception as e:
            self.results["config"]["details"].append({
                "name": "Config Loading Test", 
                "status": "fail", 
                "message": f"Error testing config loading: {str(e)}"
            })
            # Continue with other checks despite this error
    
    def run_all_checks(self):
        """Run all system checks and return results"""
        # Run all checks
        self.check_database_integrity()
        self.check_config_integrity()
        self.test_config_loading()  # Add the new configuration loading test
        self.check_routes_integrity()
        self.check_models_integrity()
        
        # Calculate overall status
        categories = ["database", "config", "routes", "models"]
        statuses = [self.results[category]["status"] for category in categories]
        
        if "fail" in statuses:
            self.results["overall"]["status"] = "fail"
            self.results["overall"]["summary"] = "System check failed. Some critical components have issues."
        elif "warn" in statuses:
            self.results["overall"]["status"] = "warn"
            self.results["overall"]["summary"] = "System check completed with warnings."
        else:
            self.results["overall"]["status"] = "pass"
            self.results["overall"]["summary"] = "All system checks passed successfully."
        
        return self.results
