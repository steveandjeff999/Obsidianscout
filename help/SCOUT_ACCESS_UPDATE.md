# Scout Role Access Restriction Update

## Changes Made

1. **Updated Scout Role Permissions**
   - Scouts can no longer access the main dashboard
   - Removed `main.index` from the list of allowed routes for scouts
   - Added automatic redirect to the scouting page after login

2. **Modified Main Dashboard Route**
   - Added access control check to redirect scouts away from the dashboard
   - Shows a warning message when scouts try to access restricted pages

3. **Updated Navigation UI**
   - Modified the application logo link to point to the scouting page for scout users
   - Hidden the Dashboard navigation item for scout-only users
   - Left all other navigation behavior intact

4. **Added Test Scout User Script**
   - Created `create_test_scout.py` to easily create a test scout account
   - Default credentials: Username: "Scout User", Password: "scout123"
   - Use this account to test scout-only access restrictions

5. **UI/UX Improvements for Scout Role**
   - Greyed out "Recent Scouting Data" and "Game Configuration" sections on the scouting dashboard for users with ONLY the scout role
   - Users with both scout and analytics roles retain full access to these sections
   - Changed card headers to a grey color to visually indicate limited access for scout-only users
   - Added "Limited access" notes to restricted sections for scout-only users
   - Disabled all edit, view, and configuration buttons in these sections for scout-only users
   - Added access control checks in routes to prevent direct URL access to restricted pages for scout-only users
   - Redirect scout-only users with appropriate warning messages if they try to access restricted pages

## Testing the Changes

1. Create a test scout user:
   ```
   python create_test_scout.py
   ```

2. Log in with the scout user credentials:
   - Username: Scout User
   - Password: scout123

3. Verify that:
   - You're automatically taken to the scouting page after login
   - The dashboard link is not visible in the navigation menu
   - If you try to access the dashboard URL directly, you're redirected back to scouting
   - Recent Scouting Data and Game Configuration sections are greyed out
   - Buttons within these sections are disabled
   - If you try to access list, view, or delete routes directly, you're redirected with a warning

## User Experience for Different Roles

1. **Admin and Analytics Users**:
   - Can access all pages as before
   - No change in navigation or access
   - See full functionality on the scouting dashboard

2. **Scout-Only Users**:
   - See a simplified interface focused on scouting
   - Application logo redirects to scouting page
   - Dashboard and advanced features are hidden
   - Only see the scouting-related navigation items
   - See greyed-out sections for restricted functionality with visual cues
   - Cannot access detailed scouting data or configuration options

3. **Users with Multiple Roles**:
   - Users with both scout and analytics roles can access all data features
   - No greying out of sections for users with both scout and analytics roles
   - Buttons and links remain active for users with both scout and analytics roles
   - Route access is granted based on the highest privilege role assigned to the user
