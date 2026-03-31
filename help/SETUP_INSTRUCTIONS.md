# Setup Instructions

Use this for first-time setup and first login.

## 1) Install dependencies

```powershell
pip install -r requirements.txt
```

## 2) Start the app

```powershell
python run.py
```

Default port is `8080` unless `PORT` is set.

```powershell
$env:PORT='5000'; python run.py
```

## 3) Log in

- Open the URL shown in terminal.
- First-run default account is usually:
  - `superadmin` / `password`
- Change the default password immediately after first login.

## 4) Create team users

From User Management:

- Create admins, analytics users, and scouts
- Confirm each user has the correct role and scouting team number

## 5) Configure API sync (recommended)

Go to `Configuration -> API Settings` and add:

- The Blue Alliance API key (recommended)
- FIRST API credentials (optional fallback)

Then run API testing from the admin menu.

## Role summary

- **Admin**: full access
- **Analytics**: analysis/data views, no user management
- **Scout**: scouting workflows only

## Quick troubleshooting

- If login fails, verify username/password and role assignment
- If app fails to start, ensure dependencies installed
- For reset/recovery steps, use `TROUBLESHOOTING.md`
