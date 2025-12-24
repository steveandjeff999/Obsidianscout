Alliance Help Icons Guide
=========================

Overview
--------
Small inline help icons (a question-mark) have been added across the *Scouting Alliances* UI to provide concise contextual guidance. These popovers appear on hover (desktop) or tap (mobile) and explain the purpose of headings or controls.

Where you'll see them
---------------------
- Main alliance pages: Dashboard, Alliance View, Create, Manage Teams/Events/Matches
- Configuration pages: Edit Game Config, Edit Pit Config
- Data pages: Import / Share Data, Manual Sync controls
- Key admin controls and modals

How to use them
---------------
- Desktop: Hover the question-mark icon to show the popover. You can also click the icon to pin the popover.
- Mobile / touch: Tap the icon to open the popover. Tap outside to dismiss.
- Keyboard: Help icons are focusable (tab) and will open the popover on focus (and on Enter/Space).

Accessibility
-------------
- Icons are reachable via keyboard and include an accessible aria-label describing the control (e.g., "Help: Alliance configuration").
- Popover content is sanitized and readable in dark mode.

Troubleshooting
---------------
- If icons are visible but popovers don't appear:
  - Ensure JavaScript is enabled (Bootstrap popovers require JS).
  - Verify your browser supports modern popover behavior (latest Chrome/Edge/Firefox recommended).
  - Check browser console for JS errors if popovers fail entirely.

Hiding the icons
----------------
If you prefer a cleaner UI, you can hide these inline help icons:
1. Go to **Settings** → **Show inline help icons**
2. Toggle the setting to off; this preference is stored in your browser's local storage

Screenshots / Media
-------------------
- Add screenshots illustrating a popover on desktop and a tap on mobile to `help/media/`.
- Recommended sizes: 800x400 for full-width desktop shots, and 360x640 for mobile examples.

Notes for maintainers
---------------------
- The help macro is in `app/templates/_help_icon.html` and uses Bootstrap popovers with sanitized HTML.
- To add or update a help popover, edit the template and provide a concise message (max ~150 chars) for clarity.
