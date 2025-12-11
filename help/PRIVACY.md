# Privacy Policy

This page explains what data Obsidian-Scout collects, why we collect it, and how we use and protect it.

## What data we collect

- **Scouting data**: Match scouting entries including actions, ratings, and notes. (Supported operations: new entries, edits, deletions.)
- **Pit scouting data**: Detailed team information and robot capabilities.
- **Team and match metadata**: Team numbers, event schedules, match results, and standings.
- **Account information**: Username, email (if provided), roles, and basic account settings.
- **Chat and collaboration messages**: Direct messages, group messages, and assistant chat history used by chat features.
- **Instrumentation and logs**: Sync logs, activity logs, and diagnostic data to monitor and troubleshoot the system.

## Why we collect it

- **Core functionality**: Provide scouting, analytics, and match-assist features that depend on team and match data.
- **Real-time collaboration**: Enable real-time replication, alliance sharing, and chat functionality.
- **Sync and data integrity**: Support catch-up sync, server-to-server replication, and API imports.
- **Analytics and predictions**: Compute metrics, scoring predictions, and visualizations used for planning and analysis.

## How we use it

- We use scouting and pit data to populate dashboards, compute metrics, and drive match predictions and analytics.
- Team, match, and API-sourced data are used to keep schedules and scores up to date on the dashboard.
- Chat messages enable direct and group communications within teams and are stored to support history, search, and notifications.
- Diagnostic logs are retained for troubleshooting and improving reliability.

## Sharing and Isolation

- **Team Isolation**: Every API key is registered with a `scouting_team_number`. All queries are automatically filtered by that team number — teams cannot see each other's scouting data. (Data Privacy - Teams cannot see each other's scouting data.)
- **Alliances**: Alliance sharing is explicit; during Alliance Sync, shared data includes match scouting entries, team rankings, and strategy notes if opted in. Pit scouting and private notes are NOT shared unless explicitly opted in.
- **Revocation & control**: Members can leave or revoke alliance sharing anytime; no data is shared without explicit alliance membership.

## Security and Protections

- **Authentication**: Token-based authentication is used for API and sync operations.
- **Encryption**: All sync and web traffic uses HTTPS/WSS encryption where supported.
- **Audit logs**: Data access and changes are recorded in logs for audit and troubleshooting.
- **Minimum exposure**: We avoid sharing unnecessary fields (user passwords or internal credentials are never exposed; API keys also control fine-grained permissions).

## Data Retention & Deletion

- Users and administrators control data retention through the instance's backup, export, and deletion tools.
- Alliance owners can remove shared data from the alliance; users can delete their own chat or scouting entries according to the system's available operations.

## Questions or Concerns

If you have questions about data collection, sharing, or deletion, contact your team admin or consult the Admin settings and audit logs. For issues with sensitive data, please raise the concern with your deployment administrator.

---
*This privacy policy compiles relevant security and privacy information found in the server help files.*
