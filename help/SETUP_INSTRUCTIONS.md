# Authentication Setup Instructions

## Quick Start

Welcome to the 5454 Scout Platform!

### First Steps
1. Log in with your credentials.
2. Explore the dashboard to see team and match data.
3. Use the navigation bar to access different features.

### Need Help?
Use the Help page to search for answers or contact your admin for support.

## Steps to initialize and test the authentication system:

1. Make sure you have installed all dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Initialize the authentication system by running:
   ```
   python init_auth.py
   ```
   This will create:
   - Admin user: admin (password: password)
   - Roles: admin, analytics, scout
   
3. If you encounter any email-related errors, run the email fix script:
   ```
   python fix_emails.py
   ```
   This will fix any issues with empty email fields in the database.

3. Start the application:
   ```
   python run.py
   ```

4. Open your browser and navigate to http://127.0.0.1:5000/

5. You will be redirected to the login page. Log in with:
   - Username: admin
   - Password: password

6. Once logged in as admin, you can:
   - Access the User Management page from your user dropdown menu
   - Add new users with different roles
   - Test the system by logging in with different user accounts

7. **Important:** Set up your API credentials for automatic data syncing:
   
   **Dual API Support:** The platform now supports both FIRST API and The Blue Alliance API with automatic fallback.
   
   **Option 1 - The Blue Alliance API (Recommended):**
   - Visit https://www.thebluealliance.com/account
   - Create an account and generate a Read API key
   - Go to Configuration > API Settings in the scouting platform
   - Enter your TBA API key and set "The Blue Alliance API" as preferred source
   
   **Option 2 - FIRST API (Official):**
   - Obtain credentials from the FIRST API portal
   - Go to Configuration > API Settings in the scouting platform
   - Enter your FIRST API username and auth token
   
   **Option 3 - Both APIs (Maximum Reliability):**
   - Configure both APIs for automatic fallback
   - Choose your preferred primary source
   - System automatically falls back if primary fails
   
   **Testing:** Use the API Testing interface (Admin menu) to verify your configuration.
   
   For detailed API setup instructions, see `DUAL_API_README.md`

8. **Optional:** Test API integration:
   - Go to Admin menu > API Testing
   - Run quick tests with sample event codes (e.g., 2024cala)
   - Verify both primary and fallback APIs are working

## Role-based access:

- **Admin users** can access everything
- **Analytics users** can access all data and reports but not user management
- **Scout users** can only access scouting features and cannot access the main dashboard

## Windows users:

Run the `setup_auth.bat` script for a guided setup process:
```
setup_auth.bat
```

## Troubleshooting:

If you encounter any issues:

1. Make sure the database file exists at `instance/scouting.db`
2. Check that Flask-Login is installed (`pip install Flask-Login`)
3. If login isn't working, try resetting the admin password:
   ```python
   from app import create_app, db
   from app.models import User
   
   app = create_app()
   with app.app_context():
       user = User.query.filter_by(username="admin").first()
       if user:
           user.set_password("password")
           db.session.commit()
           print("Password reset successfully")
   ```

4. If all else fails, you can reset the database:
   ```
   rm instance/scouting.db
   python init_auth.py
   ```
