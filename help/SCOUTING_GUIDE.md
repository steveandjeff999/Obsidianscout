# Scouting Guide

## Overview
This comprehensive guide covers the match scouting workflow in Obsidian-Scout, from data entry to analysis.

## Getting Started

### Accessing the Scouting Interface
1. Log in with your Scout or Analytics credentials
2. Navigate to **Scouting** in the navigation bar
3. You'll see the match scouting dashboard with recent entries

### Understanding the Scouting Form
The form is dynamically generated based on your game configuration and includes:
- **Auto Period**: Autonomous scoring elements
- **Teleop Period**: Teleoperated scoring elements  
- **Endgame Period**: Endgame actions (climbing, parking, etc.)
- **Post-Match**: Ratings, notes, and qualitative assessments

## Entering Match Data

### Standard Form Entry
1. Click **New Scouting Entry** or **Scout Match**
2. Select the **Event**, **Match Number**, and **Team** being scouted
3. Enter your name as the scout
4. Fill in scoring data using:
   - **Counters**: Plus/minus buttons (horizontally arranged)
   - **Booleans**: Checkboxes for yes/no actions
   - **Dropdowns**: Select from predefined options
   - **Ratings**: 1-5 star ratings for subjective measures
   - **Text Fields**: Notes and observations
5. Click **Submit** to save the entry

### Dynamic Counter Layout
- Counter inputs feature **horizontal +/- buttons** next to the number field
- Optimized for quick data entry during fast-paced matches
- Visual feedback confirms each increment/decrement

### QR Code Features

#### Generating QR Codes
1. Complete a scouting form
2. Click **Generate QR Code** after submission
3. QR code encodes the entire scouting entry
4. Display on tablet/phone screen for scanning

#### Scanning QR Codes
1. Go to **Scouting** > **QR Scan**
2. Allow camera access when prompted
3. Point camera at QR code
4. Data automatically imports into the database
5. Ideal for offline-to-online data transfer

#### Data Matrix Support
- Advanced 2D barcode format for higher data density
- Access via **Scouting** > **Data Matrix**
- Useful for complex game configurations with many fields

## Best Practices

### During Matches
- **Focus on your assigned team** - don't try to watch multiple robots
- **Use shorthand notations** in comment fields during the match
- **Submit immediately after the match** while details are fresh
- **Double-check team numbers** before submitting (most common error)

### Data Quality
- Be **consistent** with terminology and rating scales
- Don't estimate scores - only record what you clearly observe
- Use the **notes field** for context ("Broke down 30s into match")
- Rate **defense objectively** - don't let alliance color bias ratings

### Working Offline
- Obsidian-Scout supports **Progressive Web App (PWA)** functionality
- Install the app on tablets for offline capability
- Data syncs automatically when connection is restored
- QR codes enable manual data transfer if needed

## Viewing and Managing Data

### Scouting List
- View all entries from your scouting team
- Filter by event, match, team, or scout name
- Click any entry to view full details
- Edit or delete entries if permissions allow

### Quick Stats
The scouting dashboard shows:
- Total entries for current event
- Recent submissions (last 5)
- Scout coverage by match
- Teams not yet scouted

## Collaboration Features

### Team Chat
- Access via **Chat** button in navigation bar
- Real-time messaging with team members
- Create group chats for specific roles (pit scouts, match scouts, strategy)
- Unread message badge shows new activity

### Data Verification
- Multiple scouts can enter data for the same team/match
- Analytics tools average values from multiple sources
- Review discrepancies in the data view

## Advanced Features

### Match Strategy Integration
- Scouting data automatically feeds into match prediction algorithms
- View predicted winners in upcoming matches
- Strategy drawing tool references scouting notes

### Custom Metrics
- Game config defines calculated metrics
- Metrics auto-generate from raw scoring data
- Examples: shooting accuracy %, total points, cycle time

### Search and Filtering
- **Global search** (search icon in navbar) finds teams, matches, scouts
- Filter scouting list by multiple criteria simultaneously
- Export filtered data for external analysis

## Troubleshooting

### Form Not Loading
- Verify game configuration is set (Admin must configure)
- Check current event is selected in config
- Clear browser cache and reload

### Data Not Saving
- Check internet connection (or use QR code for offline)
- Verify all required fields are filled
- Ensure you're logged in (session may have expired)

### QR Scan Not Working
- Grant camera permissions in browser settings
- Ensure adequate lighting for the camera
- Try increasing QR code size on display device
- Check for glare or reflections on screen

## Tips for Event Day

### Setup
- Assign scouts to specific positions (Red 1, Red 2, Blue 1, etc.)
- Pre-populate team lists from event schedule
- Test QR scanning workflow before matches begin
- Have backup devices ready

### During Competition
- Submit data between matches, not during
- Use standardized scout names for consistency
- Communicate issues via team chat
- Take photos of scoreboards if needed for verification

### Post-Match
- Review submitted data for obvious errors
- Compare notes with other scouts
- Flag exceptional performances for strategy team
- Sync all devices before leaving venue

## Need Help?
- Use the **Help** page to search documentation
- Contact your team's admin or lead scout
- Check the **Troubleshooting** guide for common issues
- Use the **Assistant** feature for interactive help 