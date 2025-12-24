Scouting Alliances - Documentation & Changelog Updates

What I changed:

- Added inline help icons (question-mark help popovers) across the Scouting Alliances UI and several management pages.
- Added `help/ALLIANCE_HELP_ICONS_GUIDE.md` with usage, troubleshooting, and screenshot placeholders.
- Performed a documentation sweep and inserted short inline-help notes in relevant help files (Privacy, Scouting Guide, Pit Scouting, Connections & Sync, Troubleshooting, Admin Guide, etc.)
- Updated help docs to document the presence and usage of inline help icons and how to toggle them off in Settings.
- Added a changelog entry in `app/CHANGELOG.txt` (Version 1.0.1.9).
- Updated `ALLIANCE_FIXES_SUMMARY.md` to note the UI change.

Files updated (high-level):

- `app/templates/scouting_alliances/view.html` (help icons added)
- `app/templates/scouting_alliances/manage_*.html` (help icons added to manage pages)
- `app/templates/scouting_alliances/*_config*.html` (help icons added)
- `app/templates/scouting_alliances/create.html` (help icons added)
- `help/ALLIANCE_CONSTRAINTS.md` (inline help icons note)
- `help/CONNECTIONS_AND_SYNC.md` (inline help icons note)
- `help/TROUBLESHOOTING.md` (hint about popover troubleshooting)
- `help/ADMIN_GUIDE.md` (tip: inline help icons)
- `ALLIANCE_FIXES_SUMMARY.md` (UI note)
- `app/CHANGELOG.txt` (Version 1.0.1.9 entry)

Notes and follow-ups:
- Consider adding screenshots or animated GIFs to the help docs to demonstrate how popovers behave on desktop vs mobile.
- If you'd like, I can open a branch and create a PR with these changes and a review-ready description.
