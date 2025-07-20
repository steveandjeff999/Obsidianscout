import os
import sys
from app import create_app, socketio, db
from flask import redirect, url_for, request, flash
from sqlalchemy.exc import IntegrityError, OperationalError
from app.models import User, Role
from app.utils.database_init import initialize_database, check_database_health
from app.utils.update_manager import UpdateManager

app = create_app()

# Setup auth redirect handler
@app.before_request
def check_first_run():
    # Check for restart trigger file (Flask reload mechanism)
    restart_trigger = os.path.join(os.path.dirname(__file__), '.flask_restart_trigger')
    if os.path.exists(restart_trigger):
        print("Flask restart trigger detected - server will reload")
        try:
            os.remove(restart_trigger)
        except:
            pass
    
    # Check for restart flag (fallback method)
    restart_flag = os.path.join(os.path.dirname(__file__), '.restart_flag')
    if os.path.exists(restart_flag):
        print("Restart flag detected - server was restarted after update")
        try:
            os.remove(restart_flag)
        except:
            pass
    
    # File integrity is now always in warning-only mode - no redirection needed
    
    # Check if database needs initialization
    if not User.query.first() and request.path != '/auth/login':
        # No users exist, database needs initialization
        flash('Database is being initialized. Please wait...', 'info')
        return redirect(url_for('auth.login'))

# Custom error handler for database issues
@app.errorhandler(IntegrityError)
def handle_integrity_error(error):
    if "UNIQUE constraint failed: user.email" in str(error):
        flash("Error: Email address must be unique. If you're trying to create a user without an email, " 
              "run 'python fix_emails.py' to fix database issues.", 'error')
    else:
        flash(f"Database integrity error: {str(error)}", 'error')
    return redirect(url_for('auth.manage_users'))

@app.errorhandler(OperationalError)
def handle_operational_error(error):
    flash(f"Database error: {str(error)}", 'error')
    return redirect(url_for('main.index'))

if __name__ == '__main__':
    # Determine if running in a production environment (like Render)
    # Render sets the 'RENDER' environment variable
    IS_PRODUCTION = 'RENDER' in os.environ

    # Get port from environment variables, fallback to 5000 for local dev
    port = int(os.environ.get('PORT', 5000))

    # Initialize database first
    print("Starting FRC Scouting Platform...")
    with app.app_context():
        try:
            # Check if database needs initialization
            if not check_database_health():
                print("Database needs initialization...")
                initialize_database()
            else:
                print("Database is healthy and ready.")
        except Exception as e:
            print(f"Database initialization error: {e}")
            print("Attempting to initialize database...")
            initialize_database()
    
    # Initialize file integrity monitoring
    print("Initializing file integrity monitoring...")
    if hasattr(app, 'file_integrity_monitor'):
        monitor = app.file_integrity_monitor
        
        # Initialize checksums if not already done
        if not monitor.checksums:
            monitor.initialize_checksums()
            print(f"File integrity monitoring initialized with {len(monitor.checksums)} files.")
        else:
            print(f"File integrity monitoring loaded with {len(monitor.checksums)} files.")
        
        # Perform integrity check (only at startup)
        if not monitor.check_integrity():
            print("WARNING: File integrity compromised detected on startup!")
            print("Warning-only mode is enabled - you can continue using the application.")
            monitor.integrity_compromised = True  # Mark as compromised for the warning banner
        else:
            print("File integrity verified - all files are intact.")
    
    # For local development, we can use self-signed SSL. In production, Render handles SSL.
    use_ssl = not IS_PRODUCTION
    ssl_context = None

    if use_ssl:
        cert_file = os.path.join(os.path.dirname(__file__), 'ssl', 'cert.pem')
        key_file = os.path.join(os.path.dirname(__file__), 'ssl', 'key.pem')

        if os.path.exists(cert_file) and os.path.exists(key_file):
            ssl_context = (cert_file, key_file)
        else:
            # Create directory for SSL certificates if it doesn't exist
            ssl_dir = os.path.join(os.path.dirname(__file__), 'ssl')
            if not os.path.exists(ssl_dir):
                os.makedirs(ssl_dir)
                
            print("SSL certificates not found. Generating self-signed certificates for local development...")
            try:
                from OpenSSL import crypto
                
                k = crypto.PKey()
                k.generate_key(crypto.TYPE_RSA, 2048)
                
                cert = crypto.X509()
                cert.get_subject().C = "US"
                cert.get_subject().ST = "State"
                cert.get_subject().L = "City"
                cert.get_subject().O = "Team 5454"
                cert.get_subject().OU = "Scouting App"
                cert.get_subject().CN = "localhost"
                cert.set_serial_number(1000)
                cert.gmtime_adj_notBefore(0)
                cert.gmtime_adj_notAfter(10*365*24*60*60)
                cert.set_issuer(cert.get_subject())
                cert.set_pubkey(k)
                cert.sign(k, 'sha256')
                
                with open(cert_file, "wb") as cf:
                    cf.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))
                with open(key_file, "wb") as kf:
                    kf.write(crypto.dump_privatekey(crypto.FILETYPE_PEM, k))
                
                ssl_context = (cert_file, key_file)
                print("Self-signed SSL certificates generated successfully.")
            except ImportError:
                print("Warning: pyOpenSSL not installed. Cannot generate SSL certs.")
                use_ssl = False
            except Exception as e:
                print(f"Error generating SSL certificates: {e}")
                use_ssl = False

    if IS_PRODUCTION:
        print(f"Starting server in production mode on port {port} (HTTP)...")
    elif use_ssl:
        print("Starting server with SSL support (HTTPS) for local development...")
    else:
        print("Starting server without SSL (HTTP) for local development...")
        print("Warning: Camera access for QR scanning may not work without HTTPS.")

    try:
        socketio.run(
            app,
            host='0.0.0.0',
            port=port,
            debug=not IS_PRODUCTION,
            use_reloader=not IS_PRODUCTION,  # Enable reloader in development
            ssl_context=ssl_context,
            allow_unsafe_werkzeug=True  # This line disables the production server error.
        )
    except KeyboardInterrupt:
        print("\nShutting down server...")
        sys.exit(0)