# Graphing and Analysis Guide

Obsidian-Scout provides powerful data visualization and analysis tools to transform scouting data into actionable insights.

## Overview

The Graphs section offers multiple visualization modes:
- **Interactive Plotly Charts** - Dynamic, filterable graphs
- **Side-by-Side Comparisons** - Compare multiple teams across all metrics
- **Custom Pages** - Build personalized dashboards with multiple widgets
- **Shared Graphs** - Generate public links for external viewing

## Accessing the Graphs Section

1. Navigate to **Graphs** in the main navigation bar
2. You'll see the main graphing dashboard with options for:
   - Creating new graphs
   - Viewing existing custom pages
   - Accessing side-by-side comparison tool
   - Managing shared graphs

## Creating Interactive Graphs

### Basic Graph Creation
1. Click **Create Graph** or **Graphs** from the menu
2. Select your visualization type:
   - **Bar Chart**: Compare values across teams
   - **Line Chart**: Show trends over matches
   - **Box Plot**: Display statistical distributions
   - **Radar Chart**: Multi-dimensional team profiles
3. Choose your metric from the dropdown (auto, teleop, endgame points, ratings, etc.)
4. Select teams to include (filter by event)
5. Customize colors and labels
6. Click **Generate** to create the visualization

### Available Metrics
- All scoring elements from game configuration
- Auto-generated totals (Auto Points, Teleop Points, Endgame Points)
- **Total Points** from team_metrics table
- Custom calculated metrics from data_analysis config
- Post-match ratings and assessments

### Chart Types Explained

#### Bar Charts
- Best for comparing single metrics across multiple teams
- Shows average values with variance indicators
- Color-coded by alliance or custom grouping

#### Line Charts
- Ideal for tracking performance over time/matches
- Can overlay multiple teams on same graph
- Useful for identifying trends and consistency

#### Box Plots
- Displays median, quartiles, and outliers
- Great for understanding data spread and reliability
- Shows min/max ranges for each team

#### Radar Charts
- Multi-axis visualization for holistic team profiles
- Compare teams across 5-10 different metrics simultaneously
- Excellent for alliance selection decisions

## Side-by-Side Team Comparison

### Accessing Comparison Tool
1. Go to **Graphs** > **Side-by-Side Comparison**
2. Select 2-6 teams to compare
3. View comprehensive metric breakdown

### Comparison Features
- **All metrics displayed** in a sortable table
- **Visual indicators** highlight strongest teams per metric
- **Aggregation options**: Average, median, max, min, sum
- **Export to CSV** for external analysis
- **Live updates** as new scouting data is entered

### Use Cases
- Alliance partner selection
- Match strategy planning
- Identifying team strengths/weaknesses
- Pre-match opponent analysis

## Custom Pages and Widgets

### What are Custom Pages?
Custom pages are personalized dashboards where you can combine multiple graphs, statistics, and widgets into a single view.

### Creating a Custom Page
1. Go to **Graphs** > **Custom Pages** > **Create New Page**
2. Enter a page name (e.g., "Alliance Selection Dashboard")
3. Add a description (optional)
4. Click **Create**

### Adding Widgets to Pages

#### Built-in Widget Types
1. **Bar Chart Widget**: Team performance bars
2. **Line Chart Widget**: Trend lines over matches
3. **Box Plot Widget**: Statistical distribution
4. **Radar Chart Widget**: Multi-metric comparison
5. **Team Stats Table**: Detailed metric tables
6. **Match Predictions**: Upcoming match winner predictions
7. **Now Brief**: Real-time scouting activity summary

#### Custom Block Widgets
Advanced users can create custom widgets using Python-like code:
- Define custom data queries
- Create specialized visualizations
- Implement team-specific metrics
- See `CUSTOM_WIDGET_GUIDE.md` for details

### Managing Custom Pages
- **Edit**: Rearrange widgets, add new ones, change settings
- **Delete**: Remove unused pages
- **Clone**: Duplicate successful page layouts
- **Share**: Generate public links (see Sharing section)

## Graph Sharing

### Creating a Shareable Graph
1. Create any graph or custom page
2. Click **Share** button
3. System generates a unique public URL
4. Optional: Set expiration date
5. Optional: Require password for access

### Shared Graph Features
- **Public access**: No login required for viewers
- **Read-only**: Viewers cannot modify data
- **Real-time updates**: Shared graphs update as new data is entered
- **Revocable**: Admins can revoke access anytime

### Managing Shared Graphs
1. Go to **Graphs** > **My Shares**
2. View all active shared links
3. See access statistics (views, last accessed)
4. Revoke or renew shares

### Use Cases for Sharing
- Share with drive team during matches
- Present to team mentors/sponsors
- Collaborate with alliance partners
- Display on pit monitors

## Match Strategy Analysis

### Analyzing Upcoming Matches
1. Go to **Matches** > **Strategy** or **Matches** > **Analyze**
2. Select a specific match
3. View detailed breakdown:
   - Predicted winner with confidence %
   - Red/Blue alliance projected scores
   - Individual team performance metrics
   - Recommended strategies

### Match Prediction Algorithm
- Uses historical average scores for each team
- Weights recent performance higher
- Accounts for alliance synergy (if data available)
- Displays confidence level based on data quality

## Advanced Analysis Features

### Data Quality Indicators
- **Sample size**: Number of matches scouted per team
- **Consistency score**: Variance in performance
- **Last updated**: Timestamp of most recent data
- Visual warnings for insufficient data

### Filtering and Segmentation
- Filter by event, match type (qual/playoff)
- Date range selection
- Exclude outlier matches
- Group by alliance color

### Export Options
- **CSV Export**: All raw data for spreadsheet analysis
- **PNG Export**: High-res graph images for presentations
- **PDF Reports**: Multi-page formatted reports
- **JSON API**: Programmatic data access via API keys

## Best Practices

### For Alliance Selection
1. Create a custom page with 6-8 key metrics
2. Use radar charts to visualize complete team profiles
3. Compare top 10-15 teams side-by-side
4. Focus on consistency metrics (box plots) not just averages
5. Review qualitative notes/ratings alongside numbers

### For Match Strategy
1. Analyze upcoming match 10-15 minutes before it starts
2. Use line charts to check recent form/trends
3. Identify opponent weaknesses (compare to your strengths)
4. Note any recent robot issues from scouting comments
5. Share analysis with drive coach via shared graph link

### For Presentations
1. Create custom pages for each audience (drive team, sponsors, etc.)
2. Use contrasting colors for clarity
3. Include explanatory text widgets
4. Export to PNG for slideshows
5. Refresh data right before presenting

## Troubleshooting

### Graph Not Displaying Data
- Verify scouting data exists for selected teams/event
- Check date range filters aren't excluding all data
- Ensure metric exists in game configuration
- Clear browser cache and reload

### Slow Graph Performance
- Limit to 20-30 teams maximum per graph
- Use aggregated metrics rather than raw match data
- Reduce number of widgets on custom pages
- Close unused browser tabs

### Shared Link Not Working
- Check if share has expired
- Verify correct URL was copied (no truncation)
- Ensure viewer's browser supports JavaScript
- Try incognito/private window to rule out cache issues

## Tips for Effective Analysis

- **Cross-reference multiple metrics**: Don't rely on single data point
- **Watch for trends**: Improvement/decline over event matters
- **Consider context**: Understand why numbers are what they are
- **Validate outliers**: Check if extreme values are accurate
- **Update frequently**: Refresh analysis between matches
- **Collaborate**: Get input from scouts who watched the robots

## Need Help?
- See `CUSTOM_WIDGET_GUIDE.md` for advanced widget creation
- Check `API_DOCUMENTATION.md` for programmatic data access
- Use the in-app **Assistant** for interactive help
- Contact your team's analytics lead 