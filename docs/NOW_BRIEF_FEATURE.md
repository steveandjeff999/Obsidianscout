# Now Brief Feature Documentation

## Overview
The "Now Brief" panel is a Samsung-style dashboard widget that provides a comprehensive overview of recent scouting activity and upcoming matches at a glance.

## Features

### 1. Quick Stats Overview
- **Today's Scouts**: Shows unique scouts who have submitted data today
- **Upcoming Matches**: Count of next matches to scout
- **Teams Analyzed**: Total teams with at least one scouting entry

### 2. Recent Activity
- Displays the last 10 scouting entries
- Shows scout name, team number, and match information
- Includes time-ago stamps for easy reference

### 3. Next 5 Matches
- Shows detailed information for the next 5 matches
- Red and Blue alliance team displays with color-coded badges
- Scout coverage progress (how many teams have been scouted)
- Click on any match to view details
- Scheduled time display (when available)

### 4. Strategy Insights
- Shows recent strategy drawings
- Quick access to strategy analysis
- Links to match strategy pages
- Creator information

### 5. Top Performers
- Ranked list of top 5 teams by average score
- Medal-style ranking (Gold, Silver, Bronze)
- Links to team detail pages
- Performance metrics

## User Interface

### Design Elements
- **Modern Card Layout**: Samsung-style rounded corners with shadows
- **Gradient Header**: Eye-catching purple gradient header
- **Responsive Design**: Works on all screen sizes
- **Smooth Animations**: Hover effects and transitions
- **Auto-refresh**: Updates every 60 seconds automatically
- **Manual Refresh**: Button to refresh data on demand
- **Expandable/Collapsible**: Toggle to show/hide sections

### Visual Highlights
- Color-coded alliances (Red/Blue)
- Medal rankings for top performers
- Time badges for recent activity
- Progress indicators for scout coverage
- Icon-based section headers

## Technical Implementation

### Frontend
- **Location**: `app/templates/partials/brief_panel.html`
- **Included in**: Dashboard (`app/templates/index.html`)
- **Technology**: HTML, CSS, Vanilla JavaScript
- **Auto-refresh**: 60-second intervals
- **Real-time updates**: Fetches data from API endpoint

### Backend
- **API Endpoint**: `/api/brief-data`
- **Route**: `app/routes/main.py`
- **Authentication**: Requires login
- **Data Sources**:
  - ScoutingData table
  - Match table
  - Team table
  - StrategyDrawing table
  - Event table

### Data Flow
1. Frontend loads on dashboard
2. JavaScript fetches `/api/brief-data`
3. Backend queries database for:
   - Recent scouting activity
   - Upcoming matches for current event
   - Top performing teams
   - Strategy drawings
4. JSON response rendered by JavaScript
5. Auto-refresh every 60 seconds

## Usage

### For Users
1. Navigate to the dashboard
2. The Now Brief panel appears at the top
3. View quick stats and scroll through sections
4. Click on items to navigate to details:
   - Match cards → Match detail page
   - Strategy insights → Strategy analysis
   - Top performers → Team detail page
5. Use refresh button to update manually
6. Click collapse/expand to manage screen space

### For Administrators
- The panel automatically respects:
  - Current event configuration
  - Scouting team isolation
  - User permissions
- No special configuration needed

## Customization

### Adding New Sections
To add a new section to the brief panel:

1. Add HTML section in `brief_panel.html`:
```html
<div class="brief-section border-top">
    <div class="section-header p-3 pb-2">
        <h6 class="mb-0"><i class="fas fa-icon me-2"></i>Section Title</h6>
    </div>
    <div id="newSectionContainer">Loading...</div>
</div>
```

2. Add render function in JavaScript:
```javascript
renderNewSection: function(data) {
    const container = document.getElementById('newSectionContainer');
    // Render logic here
}
```

3. Add data to API endpoint in `main.py`:
```python
'new_section_data': your_data_query()
```

### Styling
All styles are contained within `<style>` tags in the partial.
Key CSS classes:
- `.brief-panel`: Main container
- `.brief-section`: Scrollable section
- `.activity-item`, `.match-card`, `.strategy-card`, `.performer-item`: Content cards

## API Response Format

```json
{
  "success": true,
  "today_scouts": 5,
  "upcoming_count": 5,
  "teams_analyzed": 12,
  "recent_activity": [
    {
      "scout_name": "John Doe",
      "team_number": 1234,
      "match_number": "Q15",
      "timestamp": "2025-10-08T14:30:00"
    }
  ],
  "upcoming_matches": [
    {
      "id": 1,
      "match_type": "Qualification",
      "match_number": 15,
      "scheduled_time": "2025-10-08T15:00:00",
      "red_teams": [1234, 5678, 9012],
      "blue_teams": [3456, 7890, 1234],
      "scout_coverage": {
        "scouted": 4,
        "total": 6
      }
    }
  ],
  "strategy_insights": [
    {
      "id": 1,
      "match_id": 10,
      "match_number": 12,
      "title": "Offensive Strategy",
      "creator_name": "Jane Smith"
    }
  ],
  "top_performers": [
    {
      "team_number": 1234,
      "team_name": "Team Name",
      "avg_score": 85.5
    }
  ]
}
```

## Performance Considerations

- API queries are optimized with filters
- Limited to recent data (last 10 entries, next 5 matches, top 5 teams)
- Sections have max-height with scrolling
- Auto-refresh uses 60-second intervals to avoid excessive requests
- Database queries respect team isolation for security

## Future Enhancements

Possible improvements:
- [ ] Real-time updates via WebSocket
- [ ] Customizable metrics/sections
- [ ] Export brief summary to PDF
- [ ] Push notifications for important updates
- [ ] Dark mode support
- [ ] Configurable refresh interval
- [ ] Widget reordering/customization
- [ ] Alliance-wide brief (alliance mode)

## Troubleshooting

### Brief panel not loading
- Check browser console for JavaScript errors
- Verify `/api/brief-data` endpoint is accessible
- Ensure user is logged in

### No data showing
- Verify current event is configured
- Check that scouting data exists
- Ensure proper team isolation settings

### Slow loading
- Check database query performance
- Reduce number of items fetched
- Consider caching API responses

## Related Files

- `app/templates/partials/brief_panel.html` - Main template
- `app/templates/index.html` - Dashboard inclusion
- `app/routes/main.py` - API endpoint
- `app/models.py` - Database models

## Support

For issues or questions:
1. Check the console for errors
2. Review API response in network tab
3. Verify database has sufficient data
4. Check user permissions and roles
