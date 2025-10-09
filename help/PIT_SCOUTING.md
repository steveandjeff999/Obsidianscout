# Pit Scouting Guide

Pit scouting collects detailed technical information about each team's robot before matches begin, informing alliance selection and match strategy decisions.

## Overview

Pit scouting captures:
- **Robot specifications** (dimensions, weight, drivetrain)
- **Mechanism capabilities** (scoring methods, autonomous routines)
- **Team information** (experience level, programming language, strategy preferences)
- **Photos and media** (robot images, CAD, videos)
- **Qualitative assessments** (driver skill, reliability estimates)

## Accessing Pit Scouting

1. Navigate to **Pit Scouting** in the main navigation bar
2. You'll see the pit scouting dashboard with:
   - List of teams in current event
   - Pit scouting completion status
   - Recent pit scouting entries
   - Quick links to add new entries

## Configuration

### Setting Up Pit Scouting Forms

**Admins only** can configure pit scouting forms:

1. Go to **Admin Settings** > **Configuration** > **Pit Config**
2. Define form sections (Robot Specs, Mechanisms, Strategy, etc.)
3. Add form elements:
   - **Text fields**: Team name, programming language, notes
   - **Checkboxes**: Has vision, Can climb, Autonomous capable
   - **Dropdowns**: Drivetrain type, shooter mechanism
   - **Number inputs**: Robot weight, max speed, cycle time
   - **Ratings**: Driver skill (1-5), build quality (1-5)
   - **Image uploads**: Robot photos
4. Set default values and field labels
5. Save configuration

### Dynamic Form Generation

Forms generate automatically based on pit_config.json:
- Changes take effect immediately
- No code modifications needed
- Supports year-to-year game changes
- Can copy configurations between seasons

### Configuration Storage

Pit configuration stored in:
- `config/pit_config.json` (primary)
- `config/pit_config_backup.json` (automatic backup)
- Version-controlled for tracking changes

## Entering Pit Scouting Data

### Standard Form Entry

1. Click **New Pit Scouting Entry** or **Scout Team**
2. Select the **Team Number** from dropdown (auto-populated from event)
3. Enter your name as the pit scout
4. Fill in all form sections:

#### Robot Specifications
- Dimensions (length, width, height)
- Weight
- Drivetrain type (swerve, tank, mecanum, etc.)
- Motor types and counts
- Battery and electrical details

#### Mechanisms
- Intake type and effectiveness
- Scoring mechanisms (shooter, arm, elevator)
- Climbing/endgame capabilities
- Vision/sensors used
- Autonomous routines available

#### Team Information
- Years of FRC experience
- Programming language(s)
- Team size
- Preferred strategies
- Alliance partner preferences

#### Assessments
- Build quality rating
- Driver skill estimate
- Reliability concerns
- Unique features or innovations

5. Upload photos (optional but recommended)
6. Add detailed notes in comment field
7. Click **Submit** to save

### Tips for Effective Pit Scouting

- **Schedule dedicated time**: Visit pits during practice matches
- **Be respectful**: Teams are busy - ask if it's a good time
- **Take photos**: Front, side, mechanisms, control system
- **Ask specific questions**: "What's your cycle time?" not "How's your robot?"
- **Verify capabilities**: Ask to see demonstrations if possible
- **Get contact info**: For follow-up questions during competition
- **Note concerns**: Mention if robot seems incomplete or problematic

## Managing Pit Scouting Data

### Viewing Entries

1. Go to **Pit Scouting** > **List**
2. View all entries filtered by:
   - Event
   - Team number
   - Scout name
   - Completion status

### Editing Entries

1. Click on any entry to view full details
2. Click **Edit** button (if permissions allow)
3. Modify any fields
4. Click **Save** to update

### Data Validation

- Multiple scouts can enter data for same team
- Compare entries to verify accuracy
- Flag discrepancies for investigation
- Update as robot changes during event

## Photo Management

### Uploading Photos

1. In pit scouting form, find **Photo Upload** section
2. Click **Choose File** or drag-and-drop
3. Supported formats: JPG, PNG, GIF
4. Recommended: 1-3 photos per robot
5. Photos auto-associate with team entry

### Photo Organization

- Stored in `instance/uploads/pit_scouting/`
- Organized by team number
- Thumbnails generated automatically
- Accessible from team detail views

### Best Photo Practices

- **Front view**: Show overall robot layout
- **Mechanism closeup**: Capture key scoring mechanisms
- **Drivetrain**: Useful for mobility assessment
- **Control system**: Helpful for troubleshooting assistance
- **Use good lighting**: Pits can be dark - use phone flashlight
- **Include scale reference**: Person or ruler in frame helps

## Data Synchronization

### Auto-Sync Feature

- Pit scouting data syncs automatically across devices
- Changes propagate in near real-time
- Offline entries sync when connection restored

### Manual Sync

1. Go to **Pit Scouting** > **Sync**
2. Click **Sync Now** to force immediate sync
3. Status indicator shows last sync time
4. Useful after bulk data entry

### QR Code Export/Import

#### Exporting via QR
1. View a pit scouting entry
2. Click **Generate QR Code**
3. QR encodes the full entry
4. Display on device screen

#### Importing via QR
1. Go to **Pit Scouting** > **QR Scan**
2. Allow camera access
3. Point camera at QR code
4. Data automatically imports
5. Ideal for offline-to-online transfer

## Integration with Match Scouting

### Cross-Referencing Data

- Alliance selection screens show pit scouting summaries
- Match strategy analysis references pit capabilities
- Graphs can incorporate pit scouting metrics
- Search includes pit scouting notes

### Combined Analysis

1. Go to **Graphs** > **Side-by-Side Comparison**
2. Includes both match and pit data
3. See technical specs alongside performance metrics
4. Helps validate or question match data patterns

## Advanced Features

### API Access

- Pit scouting data accessible via REST API
- See `API_DOCUMENTATION.md` for endpoints
- Useful for custom analysis scripts
- Export to external tools (Excel, Tableau, etc.)

### Bulk Operations

- Import pit data from CSV (admin only)
- Export all pit data to CSV
- Bulk edit capabilities for corrections
- Clone entries for similar robots

### Custom Fields

- Add team-specific questions to pit forms
- Conditional fields (show/hide based on answers)
- Calculated fields (e.g., Power Weight Ratio)
- Custom validation rules

## Best Practices

### Pre-Event Preparation

1. **Review pit config**: Ensure questions relevant to current game
2. **Assign scouts**: 2-3 people dedicated to pit scouting
3. **Create checklist**: Teams to visit, priority targets
4. **Practice form**: Familiarize scouts with questions
5. **Test photo uploads**: Verify tablets can upload images

### During Event

1. **Start early**: Visit pits during practice matches
2. **Prioritize strategically**: Scout top-ranked teams first
3. **Update as needed**: Robots change - revisit later in event
4. **Cross-check**: Have second scout verify critical teams
5. **Sync frequently**: Don't lose data to device failure

### For Alliance Selection

1. **Create custom page**: Pit data dashboard with key metrics
2. **Compare top picks**: Side-by-side of potential partners
3. **Reference photos**: Visually confirm capabilities
4. **Check notes**: Subjective assessments matter
5. **Verify with match data**: Does pit claim match performance?

## Troubleshooting

### Form Not Loading

- Check pit_config.json exists in config folder
- Verify JSON is valid (use online validator)
- Ensure current event is selected
- Clear browser cache and reload

### Photos Not Uploading

- Check file size (max 5MB per photo)
- Verify supported format (JPG/PNG/GIF only)
- Ensure uploads folder permissions correct
- Try smaller file size or different format

### Data Not Syncing

- Check internet connection
- Verify WebSocket connection (look for "Connected" indicator)
- Force manual sync via Sync button
- Check server logs for errors

### QR Scan Not Working

- Grant camera permissions in browser
- Ensure adequate lighting
- Try increasing QR code size on display
- Use different device camera if issues persist

## Tips for Different Roles

### For Pit Scouts

- Be friendly and professional - you represent your team
- Have standard questions ready but be flexible
- Take good notes - details matter
- Don't argue if team reluctant to share info
- Thank teams for their time

### For Strategy Team

- Focus questions on match strategy relevance
- Ask about cycle times and efficiency
- Inquire about preferred alliance partner styles
- Note defensive capabilities
- Ask about autonomous modes and flex

### For Drive Team

- Understand opponent robot capabilities
- Note mechanisms that could interfere with your strategy
- Identify potential defensive targets
- Learn what to avoid during matches

### For Admins

- Configure forms before event
- Monitor data entry progress
- Ensure scouts have device access
- Backup data frequently
- Generate reports for team leadership

## Need Help?

- See `SETUP_INSTRUCTIONS.md` for configuration details
- Check `TROUBLESHOOTING.md` for common issues
- Review `DATA_MANAGEMENT.md` for export/import
- Use in-app **Assistant** for interactive help
- Contact your team's admin or lead scout 