# Strategy Drawing Guide

The Strategy Drawing tool is a real-time collaborative canvas that allows teams to visually plan match strategies on a digital field map.

## Overview

Key features:
- **Real-time synchronization** - Multiple users can draw simultaneously
- **Match-specific drawings** - Separate canvas for each match
- **Custom field backgrounds** - Upload your own field images
- **Multi-color support** - Differentiate robots, strategies, and zones
- **Persistent storage** - Drawings saved automatically and persist across sessions
- **Shareable** - Generate public links for alliance partners

## Accessing Strategy Draw

1. Navigate to **Competition** > **Strategy Drawing** in the main navigation
2. Or go to **Matches** and click **Strategy Draw** on any specific match
3. The canvas loads with the current field background

## Using the Drawing Canvas

### Canvas Interface
- **Left sidebar**: Drawing tools and options
- **Center**: Canvas with field background
- **Top toolbar**: Match selector, clear, share buttons
- **Color picker**: Select drawing colors

### Drawing Tools

#### Pencil/Brush Tool
- **Click and drag** to draw freehand lines
- Use for robot paths, defensive zones, or annotations
- Adjustable line width in settings

#### Shapes (if available)
- Rectangle, circle, arrow tools
- Click once to start, drag to size, click again to finish
- Useful for marking zones and directions

#### Eraser
- Switch to eraser mode to remove parts of drawing
- Adjustable eraser size
- Does NOT remove background field image
- After erasing you can immediately draw again over that area; previously the eraser stroke would persist on top and wipe new content, but that has been corrected.

#### Text Tool (if available)
- Click to place text annotations
- Add notes like "Park here", "Defend zone", etc.
- Font size adjustable in settings

### Color Selection

1. Click the **color picker** in the toolbar
2. Select from palette or use custom color
3. Common color strategies:
   - **Red** for Red alliance robots
   - **Blue** for Blue alliance robots  
   - **Yellow** for defense zones
   - **Green** for scoring paths
   - **White** for general notes

### Match Selection

1. Use the **match selector dropdown** at the top
2. Select any upcoming or completed match
3. Drawing automatically loads for that match
4. Each match has its own separate canvas

## Real-Time Collaboration

### How It Works
- Drawings sync instantly across all connected devices
- You'll see other users' cursors and drawings in real-time
- **No conflicts** - everyone's changes merge seamlessly
- Works even with multiple people drawing simultaneously

### Collaboration Tips
- **Coordinate who draws what**: Assign roles (drive team, strategy, defense)
- **Use different colors**: Each person uses a different color for clarity
- **Add labels**: Use text to clarify whose plan is whose
- **Voice chat alongside**: Use team chat or external comms while drawing

### Typical Workflow
1. Strategy lead opens drawing 5-10 minutes before match
2. Drive coach draws primary robot path (Blue or Red)
3. Defense specialist marks defensive zones (Yellow)
4. Mentors add notes/adjustments (White text)
5. Team reviews final strategy together

## Managing Drawings

### Auto-Save
- Drawings save automatically every few seconds
- No need to manually save - changes persist immediately
- **Safe to close tab** - drawing will be there when you return

### Clearing the Canvas
1. Click **Clear Drawing** button
2. Confirmation prompt appears
3. Clearing syncs to all users in real-time
4. **Note**: Clear only affects drawings, not the field background

### Loading Previous Drawings
- Select a match from the dropdown
- Its previously saved drawing loads automatically
- No limit on how many match drawings you can store

## Custom Field Backgrounds

### Why Custom Backgrounds?
- Official field images match actual game elements
- Year-specific layouts
- Higher resolution for detailed strategies
- Team-branded templates

### Uploading a Custom Background
1. Find **Upload Background** button (admin only)
2. Select an image file (PNG, JPG, or GIF)
3. Image uploads and syncs to all users
4. **Applies globally** to all matches and all users
5. Background persists after refresh

### Background Best Practices
- Use high-resolution images (1920x1080 or higher)
- PNG format for transparency support
- Overhead view of field works best
- Include all major game elements (goals, zones, etc.)
- Test with drawing to ensure proper scaling

### Resetting to Default
- Delete custom background (admin only)
- System reverts to default field image
- All existing drawings remain intact

## Sharing Strategies

### Creating a Shareable Link
1. Click **Share Strategy** button
2. System generates unique public URL
3. Optional: Add password protection
4. Optional: Set expiration time

### Use Cases for Sharing
- Share with alliance partners before playoff matches
- Send to drive team's mobile devices
- Display on pit monitors
- Archive for post-competition review
- Share with mentors not at event

### Managing Shares
- Access "My Strategy Shares" to see all active links
- Revoke access anytime
- Track view counts and last access time

## Advanced Features

### WebSocket Synchronization
- Uses Socket.IO for low-latency real-time sync
- Automatic reconnection if connection drops
- Queues changes during offline periods
- Syncs when connection restored

### Match-Specific Persistence
- Each match has unique canvas state
- Stored in database with match_id reference
- Survives server restarts
- Accessible across all sessions

### Multi-User Indicators (if available)
- See other users currently viewing same match drawing
- User cursor positions may be visible
- Helps coordinate who's drawing where

## Best Practices

### Before a Match
- Review opponent scouting data first
- Identify key threats and opportunities
- Sketch primary strategy (1-2 minutes)
- Mark alternative plans if primary fails
- Clear canvas from previous match if reusing

### During Strategy Discussion
- One person drives the drawing while others suggest
- Use text annotations for verbal strategy elements
- Mark timing ("At 30s, move here")
- Highlight no-go zones for safety

### After the Match
- Leave drawing intact for post-match review
- Annotate what worked vs. didn't (different color)
- Reference in post-match debrief
- Use for future match predictions

### For Alliance Partners
- Share drawing link before match
- Coordinate strategies - don't duplicate effort
- Mark zones ("We handle left side, you handle right")
- Use for quick alignment before match starts

## Troubleshooting

### Drawing Not Syncing
- Check internet connection (Wi-Fi indicator)
- Refresh page to re-establish WebSocket connection
- Verify other users have latest version
- Check browser console for errors (F12)

### Canvas Not Loading
- Ensure match is selected from dropdown
- Check if browser blocks canvas/WebGL
- Try different browser (Chrome recommended)
- Clear browser cache and reload

### Background Image Not Showing
- Verify image uploaded successfully (admin check)
- Check image format (PNG/JPG supported)
- Try re-uploading with different file
- Ensure image file size under 5MB

### Accidental Clear
- **No undo for clear action** - be cautious
- Check if another user cleared (coordination issue)
- Redraw from memory if needed
- Consider screenshotting important strategies

## Tips for Effective Strategy Drawing

- **Keep it simple**: Overly complex drawings confuse drive teams
- **Use arrows**: Show direction and flow clearly
- **Label key moments**: "15s mark", "After auto", etc.
- **Contrast colors**: Ensure visibility on field background
- **Test before match day**: Practice using tool with team
- **Have backup plan**: Draw on whiteboard if tech fails
- **Screenshot final**: Capture image to reference during match

## Technical Details

### Supported Browsers
- Chrome/Edge (recommended)
- Firefox
- Safari (limited testing)
- Mobile browsers (touch support varies)

### Performance
- Optimized for tablets and large screens
- Works on phones but small screen limits utility
- Multiple concurrent users supported (10+ tested)
- Low bandwidth usage (<1KB per drawing action)

## Need Help?
- See `CONNECTIONS_AND_SYNC.md` for real-time sync details
- Check `TROUBLESHOOTING.md` for common issues
- Use the in-app **Assistant** for interactive help
- Contact your team's admin or tech lead 