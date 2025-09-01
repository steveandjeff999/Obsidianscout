# User navigation cheat sheet

This document explains how to reach important pages in the application for each user type: Admin, Analytics, and Scout.

Checklist
- [x] Provide login/register/profile instructions
- [x] List key pages and exact URLs for Admin users
- [x] List key pages and exact URLs for Analytics users
- [x] List key pages and exact URLs for Scout users
- [x] Note common redirects and role-specific behavior

## Quick notes (general)
- App root: `/` (main dashboard). Requires login.
- Login page: `/auth/login`
- Register: `/auth/register`
- Profile: `/auth/profile`
- Logout: `/auth/logout`
- If a user has no assigned role, they are sent to `/auth/select_role` after login.
- For many admin-only pages the `superadmin` role is required; `admin` has a subset of admin abilities.

## How login redirects work
- On successful login the app chooses the landing page:
  - If a user is ONLY a `scout` (and not `admin` or `analytics`) they are redirected to the scouting dashboard: `/scouting/`.
  - Otherwise users are sent to the main dashboard: `/`.

## Admin (roles: `admin`, `superadmin`)
Admins manage users and team settings and can access administrative dashboards.

Main admin pages and how to reach them:
- Main dashboard: `/` (login → main dashboard)
- Manage users (list / edit): `/auth/users`  (also linked from the admin menu)
- Add user: `/auth/add_user`
- Edit user: `/auth/edit_user/<user_id>` (open from the users list)
- View user: `/auth/users/<user_id>`
- Admin settings (team-level settings): `/auth/admin/settings`
  - Toggle account creation lock: action on the admin settings page (`/auth/admin/toggle-account-lock` POST)
- System check: `/auth/system_check` (run integrity/system checks)
- Email settings (superadmin only): `/auth/admin/email-settings`
- Send test email (superadmin only): `/auth/admin/email-test` (POST)
- Site notifications (superadmin-only management page): `/auth/notifications`
- Database administration (superadmin only): `/admin/database/`
  - API status: `/admin/database/api/status`
  - Optimize DB: `/admin/database/optimize` (POST)
  - Export DB: `/admin/database/export`
  - Import DB: `/admin/database/import` (POST with file)

Notes:
- Only `superadmin` users can access `/admin/database/*` and some email/notification actions.
- Admins who are not superadmin are scoped to their `scouting_team_number` for user listings and settings.

## Analytics (role: `analytics`, often combined with `admin`)
Analytics users can view graphs, data exports and the data dashboard.

Key analytics pages:
- Main dashboard: `/` (login → main dashboard)
- Graphs dashboard: `/graphs/` (requires `analytics` role)
  - Use query params for team/event/metric filtering, e.g. `/graphs/?teams=254&metric=points`
- Data import/export & overview: `/data/` (requires `analytics` role)
  - Import Excel: `/data/import/excel`
  - Import QR: `/data/import_qr`
- Scouting data listing (analytics or admin): `/scouting/list` (analytics have access; scouts only are redirected away)
- Shared graphs / saved charts may be available under `/graphs/` pages

Notes:
- If you have both `analytics` and `scout` roles you'll keep analytics access (you will not be auto-redirected to `/scouting/`).

## Scout (role: `scout`)
Scouts primarily submit and view scouting forms and QR codes.

Key scout pages and how to reach them:
- After login (scout-only accounts): you are redirected to the scouting dashboard: `/scouting/`
- Scouting dashboard (overview): `/scouting/`
- Scouting form (select team & match then scout): `/scouting/form`
  - The form can be loaded via AJAX by posting `team_id` and `match_id` to `/scouting/form` (XHR)
- Generate/Display QR / Data Matrix for a saved scouting record:
  - Friendly display (query params): `/scouting/qr?team_id=<id>&match_id=<id>`
  - Direct link: `/scouting/qr/<team_id>/<match_id>`
- List of scouting entries (`/scouting/list`) is restricted: if user is ONLY a scout (no analytics/admin) they will be redirected to `/scouting/` and denied the full list view.

Notes:
- Scouts must include their team number on login. The login form requests `team_number` and a user must exist with that `scouting_team_number`.
- Scouts cannot access the main dashboard (`/`) unless they also have `admin` or `analytics` roles.

## Other useful pages (all roles may use depending on permissions)
- About: `/about`
- Config view: `/config`
- Config edit: `/config/edit` and `/config/simple-edit` (requires proper permissions)
- Teams list: `/teams/`
- Matches list: `/matches/`
- Pit scouting: `/pit-scouting/` (if enabled in UI)
- Assistant/chat: `/assistant/`

## Troubleshooting & tips
- If you cannot access a page, check your roles in your profile (`/auth/profile`) or ask a `superadmin` to review your roles at `/auth/users`.
- To change which role you use when you first sign up, go to `/auth/select_role` after login (visible if you have no roles assigned).
- Superadmins can create or reset admin accounts using scripts in `other/` (for example `other/reset_admin.py`).

---
File: `help/user-navigation.md` added to the repository. Map of requirements:
- Add help doc: Done (`help/user-navigation.md`).
- Instructions for Admin, Analytics, Scout: Done.

If you want, I can:
- Make this available in the app UI under the Help menu (`app/routes/main.py` references `help/` already). I can add a link or a route to serve this file — tell me if you'd like that change and whether to use the existing `HELP_FOLDER` mechanism.
