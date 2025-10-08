# Auto Period Timer - Quick Start Guide

## For Scouts

### How to Use
1. **Enable**: Toggle "Enable Auto → Teleop Reminder" in Scout Information section
2. **Scout**: Start making entries in Auto period
3. **First Entry**: Timer starts automatically when you make your first scoring entry
4. **Wait**: After 15 seconds (or configured duration), a yellow banner will appear
5. **Switch**: Click the Teleop tab when ready - banner disappears automatically

### What You'll See
- ✅ Toggle switch in Scout Information
- ✅ Yellow warning banner after auto period
- ✅ Message: "Remember to switch to Teleop"
- ✅ Banner stays until you click Teleop tab

### Tips
- Your preference is saved automatically
- Toggle ON once, it remembers for all future sessions
- You can disable it anytime by toggling OFF
- Works with any scoring entry (counters or checkboxes)

## For Admins

### Quick Config
**Change Timer Duration:**
1. Edit `config/game_config.json`
2. Find `"auto_period": { "duration_seconds": 15 }`
3. Change 15 to your desired seconds
4. Restart server

### Files Changed
- `app/templates/scouting/partials/form_content.html` - Toggle & banner
- `app/static/js/scripts.js` - Timer logic
- `app/templates/scouting/form.html` - Initialization
- `app/static/css/scouting_form.css` - Styling

### Key Features
- ✅ Starts on first auto entry
- ✅ Persists preference in localStorage
- ✅ Sticky banner at top of form
- ✅ Auto-hides on teleop switch
- ✅ Optional audio notification
- ✅ Fully keyboard accessible

## Testing
```javascript
// Check if working (browser console)
console.log(window.autoPeriodTimerState);

// Expected output:
{
  timerStarted: true/false,
  timerCompleted: true/false,
  reminderShown: true/false,
  autoPeriodDuration: 15000
}
```

## Common Issues

**Banner doesn't show?**
- Enable the toggle
- Make at least one auto entry
- Wait full duration (15 seconds)

**Timer doesn't start?**
- Check toggle is ON
- Increment a counter or check a box with points

**Preference not saving?**
- Not in private/incognito mode
- localStorage must be enabled

---

**Full Documentation:** See `AUTO_PERIOD_TIMER_FEATURE.md`
