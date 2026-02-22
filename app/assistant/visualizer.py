"""
Scout Assistant Visualizer
Creates graphs and visual representations of scouting data
"""

import json
import io
import base64
from typing import Dict, List, Any, Tuple, Optional

# ---------------------------------------------------------------------------
# Heavy optional plotting libraries
# ---------------------------------------------------------------------------
# matplotlib + seaborn must be imported lazily because:
#   a) seaborn 0.13.x has a regex that triggers infinite recursion in
#      Python 3.13's re module causing startup to hang / crash with
#      KeyboardInterrupt (not an Exception subclass, so a bare
#      `except Exception` will NOT save you).
#   b) Some headless servers don't have a display; the Agg backend avoids
#      that, but the import must still succeed first.
# We use `except BaseException` so even KeyboardInterrupt/SystemExit from a
# broken import are caught and the visualizer degrades gracefully.
# ---------------------------------------------------------------------------
plt = None
sns = None
pd  = None
np  = None
HAS_MATPLOTLIB = False
HAS_SEABORN    = False

try:
    import matplotlib as _mpl
    _mpl.use('Agg')  # must be set before importing pyplot
    import matplotlib.pyplot as _plt
    plt = _plt
    HAS_MATPLOTLIB = True
except BaseException as _e:
    import logging as _log
    _log.getLogger(__name__).warning(
        "matplotlib unavailable – visualisations will be disabled: %s", _e
    )

if HAS_MATPLOTLIB:
    try:
        import seaborn as _sns
        import pandas as _pd
        import numpy as _np
        sns = _sns
        pd  = _pd
        np  = _np
        HAS_SEABORN = True
    except BaseException as _e:
        import logging as _log
        _log.getLogger(__name__).warning(
            "seaborn/pandas/numpy unavailable – advanced visualisations disabled: %s", _e
        )
from app.models import Team, ScoutingData, Match, Event
from app.utils.analysis import calculate_team_metrics
import logging

logger = logging.getLogger(__name__)

class Visualizer:
    """
    Creates visualizations for scouting data and analysis
    """
    
    def __init__(self):
        # Set up default styling for plots
        self.setup_plot_style()
    
    def setup_plot_style(self):
        """Set up the default styling for all plots"""
        if HAS_MATPLOTLIB and plt is not None:
            plt.rcParams['figure.figsize'] = (10, 6)
            plt.rcParams['font.size'] = 12

        # If seaborn isn't available, fall back to matplotlib defaults and warn
        if HAS_SEABORN and sns is not None:
            try:
                sns.set_theme(style="whitegrid")
            except Exception:
                pass
        
        # Use team 5454 colors
        self.colors = {
            'primary': '#E51837',    # Team 5454 red
            'secondary': '#0066B3',  # Blue
            'tertiary': '#FFD100',   # Yellow
            'background': '#F5F5F5', # Light gray background
            'text': '#333333',       # Dark gray text
        }
        
        # Color palettes for multi-team visualizations
        if HAS_SEABORN and sns is not None:
            try:
                self.palette = sns.color_palette([
                    self.colors['primary'],
                    self.colors['secondary'],
                    '#00A651',  # Green
                    '#FF8200',  # Orange
                    '#8A2BE2',  # Purple
                ])
            except Exception:
                self.palette = [self.colors['primary'], self.colors['secondary'], '#00A651', '#FF8200', '#8A2BE2']
        else:
            # Minimal palette fallback
            self.palette = [self.colors['primary'], self.colors['secondary'], '#00A651', '#FF8200', '#8A2BE2']
    
    def generate_visualization(self, vis_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main method to generate a visualization based on the requested type
        
        Args:
            vis_type: Type of visualization to generate
            data: Data required for the visualization
            
        Returns:
            Dictionary with base64-encoded image and any related data
        """
        visualization_methods = {
            'team_performance': self.plot_team_performance,
            'team_comparison': self.plot_team_comparison,
            'metric_comparison': self.plot_metric_comparison,
            'match_breakdown': self.plot_match_breakdown,
            'radar_chart': self.plot_radar_chart,
            'event_summary': self.plot_event_summary,
            'match_schedule': self.plot_match_schedule,
            'team_ranking': self.plot_team_ranking,
            'ranking_comparison': self.plot_ranking_comparison,
            'trend_chart': self.plot_trend_chart
        }
        
        if vis_type not in visualization_methods:
            return {
                "error": True,
                "message": f"Unsupported visualization type: {vis_type}"
            }

        if not HAS_MATPLOTLIB or plt is None:
            return {
                "error": True,
                "message": "Visualization unavailable: matplotlib could not be loaded on this server."
            }

        # Note: some visualizations (like trend_chart) can be generated with
        # plain matplotlib only. Avoid blocking all visualizations if optional
        # dependencies (seaborn/pandas/numpy) are missing. Individual plot
        # methods should raise clear errors if they require those libs.

        try:
            # Call the appropriate visualization method
            figure = visualization_methods[vis_type](data)

            # Convert plot to base64-encoded image
            img_data = self.figure_to_base64(figure)

            # Close the figure to free memory
            try:
                plt.close(figure)
            except Exception:
                pass

            return {
                "image": img_data,
                "type": vis_type
            }
        except Exception as e:
            logger.error(f"Error generating {vis_type} visualization: {e}")
            return {
                "error": True,
                "message": f"Failed to generate visualization: {str(e)}"
            }
    
    def figure_to_base64(self, fig) -> str:
        """Convert a matplotlib figure to base64-encoded PNG"""
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)
        img_data = base64.b64encode(buf.getvalue()).decode('utf-8')
        return img_data
    
    def plot_team_performance(self, data: Dict[str, Any]):
        """Plot a team's performance across multiple metrics"""
        team = data.get('team', {})
        stats = team.get('stats', {})
        
        if not stats:
            raise ValueError("No team statistics provided")
        
        # Create figure and axis
        fig, ax = plt.subplots()
        
        # Get metrics to plot
        metrics = ['auto_points', 'teleop_points', 'endgame_points', 'total_points']
        metric_names = ['Auto', 'Teleop', 'Endgame', 'Total']
        values = [stats.get(m, 0) for m in metrics]
        
        # Create bar chart
        bars = ax.bar(metric_names, values, color=self.colors['primary'])
        
        # Add labels and title
        ax.set_title(f"Team {team['number']} Performance Breakdown")
        ax.set_ylabel('Average Points')
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                    f'{height:.1f}', ha='center', va='bottom')
        
        # Add grid lines
        ax.yaxis.grid(True, linestyle='--', alpha=0.7)
        
        return fig
    
    def plot_team_comparison(self, data: Dict[str, Any]):
        """Plot a comparison between two teams across multiple metrics"""
        teams = data.get('teams', [])
        
        if len(teams) < 2:
            raise ValueError("Need at least two teams to compare")
        
        # Extract team numbers and stats
        team_numbers = [str(team.get('number')) for team in teams]
        team_stats = [team.get('stats', {}) for team in teams]
        
        # Metrics to compare
        metrics = ['auto_points', 'teleop_points', 'endgame_points', 'total_points']
        metric_names = ['Auto', 'Teleop', 'Endgame', 'Total']
        
        # Set up figure
        fig, ax = plt.subplots()
        
        # Set up positions for grouped bars
        x = np.arange(len(metric_names))
        width = 0.35  # width of bars
        
        # Plot bars for each team
        for i, (team_num, stats) in enumerate(zip(team_numbers, team_stats)):
            values = [stats.get(m, 0) for m in metrics]
            bars = ax.bar(x + (i - 0.5 + 0.5*i) * width, values, width, 
                   label=f'Team {team_num}', 
                   color=self.palette[i % len(self.palette)])
        
        # Add labels and title
        ax.set_title(f"Team Comparison: {' vs '.join(team_numbers)}")
        ax.set_ylabel('Average Points')
        ax.set_xticks(x)
        ax.set_xticklabels(metric_names)
        ax.legend()
        
        # Add grid lines
        ax.yaxis.grid(True, linestyle='--', alpha=0.7)
        
        return fig
    
    def plot_metric_comparison(self, data: Dict[str, Any]):
        """Plot top teams for a specific metric"""
        teams = data.get('teams', [])
        metric = data.get('metric', 'Unknown')
        
        if not teams:
            raise ValueError("No team data provided")
        
        # Create sorted dataframe
        df = pd.DataFrame(teams)
        df = df.sort_values('value', ascending=False)
        
        # Create figure and axis
        fig, ax = plt.subplots()
        
        # Create horizontal bar chart
        bars = ax.barh(df['name'], df['value'], color=self.colors['primary'])
        
        # Add labels and title
        ax.set_title(f"Top Teams: {metric}")
        ax.set_xlabel('Performance Value')
        
        # Add value labels on bars
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax.text(width + 0.5, bar.get_y() + bar.get_height()/2.,
                    f'{width:.1f}', ha='left', va='center')
        
        # Invert y-axis to show highest values at the top
        ax.invert_yaxis()
        
        # Add grid lines
        ax.xaxis.grid(True, linestyle='--', alpha=0.7)
        
        return fig
    
    def plot_match_breakdown(self, data: Dict[str, Any]):
        """Plot the breakdown of a match"""
        match = data.get('match', {})
        
        if not match:
            raise ValueError("No match data provided")
        
        # Extract match data
        red_score = match.get('red_score', 0)
        blue_score = match.get('blue_score', 0)
        
        # Create figure with two subplots (score comparison and breakdown)
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
        
        # Plot 1: Score comparison
        bars = ax1.bar(['Red Alliance', 'Blue Alliance'], [red_score, blue_score], 
                color=[self.colors['primary'], self.colors['secondary']])
        
        ax1.set_title(f"Match {match['number']} Final Score")
        ax1.set_ylabel('Total Points')
        
        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax1.text(bar.get_x() + bar.get_width()/2., height + 0.5,
                    f'{height:.0f}', ha='center', va='bottom')
        
        # Plot 2: Point breakdown (placeholder - would need actual breakdown data)
        # This is just a placeholder - in a real app, you'd use actual point breakdowns
        categories = ['Auto', 'Teleop', 'Endgame']
        red_values = [red_score * 0.25, red_score * 0.5, red_score * 0.25]  # Example values
        blue_values = [blue_score * 0.25, blue_score * 0.5, blue_score * 0.25]  # Example values
        
        x = np.arange(len(categories))
        width = 0.35
        
        ax2.bar(x - width/2, red_values, width, label='Red', color=self.colors['primary'])
        ax2.bar(x + width/2, blue_values, width, label='Blue', color=self.colors['secondary'])
        
        ax2.set_title('Point Breakdown by Phase')
        ax2.set_xticks(x)
        ax2.set_xticklabels(categories)
        ax2.legend()
        
        plt.tight_layout()
        return fig
    
    def plot_radar_chart(self, data: Dict[str, Any]):
        """Create a radar chart comparing teams across multiple metrics"""
        teams = data.get('teams', [])
        
        if len(teams) < 1:
            raise ValueError("Need at least one team for radar chart")
        
        # Metrics for radar chart (label, stats key, optional fallback max)
        metric_config = [
            ('Auto', 'auto_points', None),
            ('Teleop', 'teleop_points', None),
            ('Endgame', 'endgame_points', None),
            ('Total', 'total_points', None),
            ('Quality', 'data_quality_score', 100),
            ('Confidence', 'prediction_confidence', 100),
        ]

        def safe_number(value, default=0.0):
            try:
                if value is None:
                    return default
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    return float(value.strip())
            except (ValueError, TypeError):
                pass
            return default

        # Pre-compute max values across all teams for normalization
        max_values = {}
        for _, metric_key, fallback_max in metric_config:
            values = []
            for team in teams:
                stats = team.get('stats', {}) or {}
                raw_val = stats.get(metric_key)
                # Some metrics may be stored as 0-1 fractions; scale to percentages if appropriate
                if metric_key in ('data_quality_score', 'prediction_confidence') and raw_val is not None and raw_val <= 1:
                    raw_val = raw_val * 100
                values.append(safe_number(raw_val))

            candidate_max = max(values) if values else 0
            if fallback_max is not None:
                candidate_max = max(candidate_max, fallback_max)
            if candidate_max <= 0:
                candidate_max = fallback_max or 1
            max_values[metric_key] = candidate_max

        metric_labels = [label for label, _, _ in metric_config]

        # Set up radar chart
        angles = np.linspace(0, 2*np.pi, len(metric_config), endpoint=False).tolist()
        angles += angles[:1]  # Close the loop
        
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        
        # Add lines for each team
        for i, team in enumerate(teams):
            stats = team.get('stats', {})
            norm_values = []
            for label, metric_key, _ in metric_config:
                value = stats.get(metric_key)
                # Scale fractional scores to percentage when appropriate so the radial scale is intuitive
                if metric_key in ('data_quality_score', 'prediction_confidence') and value is not None and value <= 1:
                    value = value * 100
                numeric_val = safe_number(value)
                max_val = max_values.get(metric_key, 1)
                normalized = numeric_val / max_val if max_val else 0
                # Clamp to 0-1 range to avoid matplotlib warnings
                normalized = max(0.0, min(normalized, 1.0))
                norm_values.append(normalized)

            norm_values += norm_values[:1]  # Close the loop
            
            # Plot the team
            ax.plot(angles, norm_values, linewidth=2, linestyle='solid', 
                    label=f"Team {team['number']}", color=self.palette[i % len(self.palette)])
            ax.fill(angles, norm_values, alpha=0.1, color=self.palette[i % len(self.palette)])
        
        # Set category labels
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(metric_labels)
        
        # Remove radial labels and set grid
        ax.set_yticklabels([])
        ax.grid(True)
        
        # Add legend and title
        team_numbers = [str(team.get('number')) for team in teams]
        ax.set_title(f"Team Comparison: {' vs '.join(team_numbers)}")
        ax.legend(loc='upper right', bbox_to_anchor=(0.1, 0.1))
        
        return fig
    
    def plot_event_summary(self, data: Dict[str, Any]):
        """Plot a summary of an event"""
        event = data.get('event', {})
        
        if not event:
            raise ValueError("No event data provided")
        
        # Create figure with multiple subplots
        fig = plt.figure(figsize=(12, 8))
        
        # Plot 1: Match completion progress
        ax1 = fig.add_subplot(221)
        total = event.get('total_matches', 0)
        completed = event.get('completed_matches', 0)
        
        ax1.pie([completed, total-completed], 
                labels=[f'Completed ({completed})', f'Remaining ({total-completed})'],
                colors=[self.colors['secondary'], self.colors['background']],
                autopct='%1.1f%%', startangle=90)
        ax1.set_title('Match Progress')
        
        # Plot 2: Scouting coverage
        ax2 = fig.add_subplot(222)
        teams_count = event.get('teams_count', 0)
        entries_count = event.get('scouting_entries', 0)
        
        ax2.bar(['Teams', 'Scouting Entries'], [teams_count, entries_count],
                color=[self.colors['primary'], self.colors['secondary']])
        ax2.set_title('Scouting Coverage')
        
        # Plot 3: Event timeline (placeholder)
        ax3 = fig.add_subplot(212)
        
        # This would be replaced with actual event timeline data
        days = pd.date_range(start=event.get('dates', '').split(' to ')[0], 
                            end=event.get('dates', '').split(' to ')[1])
        
        # Example data - in a real app, you'd use actual match counts per day
        match_counts = np.random.randint(10, 30, size=len(days))
        
        ax3.bar(days, match_counts, color=self.colors['primary'])
        ax3.set_title('Matches by Day')
        ax3.set_xlabel('Date')
        ax3.set_ylabel('Number of Matches')
        
        plt.tight_layout()
        return fig
    
    def plot_match_schedule(self, data: Dict[str, Any]):
        """Visualize the match schedule"""
        matches = data.get('matches', [])
        
        if not matches:
            raise ValueError("No match data provided")
        
        # Create dataframe for easier plotting
        match_data = []
        for match in matches:
            match_data.append({
                'match': f"Match {match['number']}",
                'time': match['time']
            })
            
        df = pd.DataFrame(match_data)
        
        # Create figure and axis
        fig, ax = plt.subplots(figsize=(10, max(6, len(matches) * 0.4)))
        
        # Create horizontal bar chart for schedule
        y_pos = range(len(df))
        ax.barh(y_pos, [1] * len(df), left=0, color=self.colors['secondary'], alpha=0.3)
        
        # Add match labels
        for i, (_, row) in enumerate(df.iterrows()):
            ax.text(0.1, i, f"{row['match']} - {row['time']}", va='center')
        
        # Remove axes and ticks
        ax.set_yticks([])
        ax.set_xticks([])
        ax.set_xlabel('')
        ax.set_title('Upcoming Matches')
        
        # Remove spines
        for spine in ax.spines.values():
            spine.set_visible(False)
            
        return fig
    
    def plot_team_ranking(self, data: Dict[str, Any]):
        """Plot team rankings for a specific metric"""
        teams = data.get('teams', [])
        metric = data.get('metric', 'Unknown')
        
        if not teams:
            raise ValueError("No team data provided")
        
        # Create sorted dataframe
        df = pd.DataFrame(teams)
        df = df.sort_values('value', ascending=True)
        
        # Create figure and axis
        fig, ax = plt.subplots(figsize=(10, max(6, len(teams) * 0.4)))
        
        # Create horizontal bar chart
        bars = ax.barh(df['name'], df['value'], color=self.colors['primary'])
        
        # Add labels and title
        ax.set_title(f"Team Rankings: {metric}")
        ax.set_xlabel('Performance Value')
        
        # Add value labels on bars
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax.text(width + 0.5, bar.get_y() + bar.get_height()/2.,
                    f'{width:.1f}', ha='left', va='center')
        
        # Add grid lines
        ax.xaxis.grid(True, linestyle='--', alpha=0.7)
        
        return fig
    
    def plot_ranking_comparison(self, data: Dict[str, Any]):
        """Compare a team's ranking across different metrics"""
        team = data.get('team', {})
        stats = team.get('stats', {})
        
        if not stats:
            raise ValueError("No team statistics provided")
        
        # Create figure and axis
        fig, ax = plt.subplots()
        
        # Get team's ranks for different metrics (this is placeholder data)
        # In a real app, you would compare this team to others to get actual rankings
        metrics = ['Auto', 'Teleop', 'Endgame', 'Overall', 'Defense', 'Climb']
        # Lower rank is better (1st, 2nd, etc.)
        ranks = [5, 12, 3, 7, 15, 2]  # Example ranking data
        
        # Create horizontal bar chart (inverted so 1st place is at the top)
        y_pos = range(len(metrics))
        bars = ax.barh(y_pos, [max(ranks) + 1 - r for r in ranks], 
                      color=self.colors['primary'])
        
        # Set custom tick labels
        ax.set_yticks(y_pos)
        ax.set_yticklabels(metrics)
        
        # Set custom x-tick labels (rankings)
        max_rank = max(ranks)
        ax.set_xticks(range(1, max_rank + 1))
        ax.set_xticklabels([str(max_rank + 1 - i) for i in range(1, max_rank + 1)])
        
        # Add rank labels on bars
        for i, bar in enumerate(bars):
            width = bar.get_width()
            rank = ranks[i]
            ax.text(width - 0.5, bar.get_y() + bar.get_height()/2.,
                    f'{rank}', ha='center', va='center')
        
        # Add title and labels
        ax.set_title(f"Team {team['number']} Rankings")
        ax.set_xlabel('Ranking Position')
        
        # Add grid lines
        ax.xaxis.grid(True, linestyle='--', alpha=0.7)
        
        return fig
    
    def plot_trend_chart(self, data: Dict[str, Any]):
        """Plot team performance trend over time with regression line"""
        # Support either being passed the assistant response (which contains
        # a `visualization_data` key) or being passed the visualization_data
        # dict directly.
        payload = data.get('visualization_data') if isinstance(data, dict) and data.get('visualization_data') else data

        team_number = payload.get('team_number')
        match_scores = payload.get('match_scores', []) or payload.get('matches', [])
        slope = payload.get('slope', 0)
        intercept = payload.get('intercept', 0)
        
        if not match_scores:
            raise ValueError("No match score data provided")
        
        # Extract match numbers and scores
        # Accept several possible keys for match id/number
        matches = []
        scores = []
        for score in match_scores:
            # Score value can be under 'score' or 'total'
            val = score.get('score') if isinstance(score, dict) else None
            if val is None:
                val = score.get('total') if isinstance(score, dict) else None
            if val is None and isinstance(score, (int, float)):
                val = score

            # Match identifier can be 'match_number', 'match', or 'match_id'
            mnum = None
            if isinstance(score, dict):
                mnum = score.get('match_number') or score.get('match') or score.get('match_id')
            # If still None, use index order
            matches.append(mnum if mnum is not None else len(matches))
            scores.append(val if val is not None else 0)
        
        # Create figure and axis
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Plot actual scores as scatter points
        ax.scatter(matches, scores, color=self.colors['primary'], 
                  s=100, alpha=0.6, label='Actual Scores', zorder=3)
        
        # Plot trend line
        if len(matches) >= 2 and slope != 0:
            x_vals = list(range(len(matches)))
            trend_line = [slope * x + intercept for x in x_vals]
            ax.plot(matches, trend_line, color=self.colors['secondary'], 
                   linewidth=2, linestyle='--', label='Trend Line', zorder=2)
        
        # Connect points with line
        ax.plot(matches, scores, color=self.colors['primary'], 
               linewidth=1.5, alpha=0.3, zorder=1)
        
        # Add labels and title
        trend_direction = "Improving" if slope > 0 else "Declining" if slope < 0 else "Stable"
        ax.set_title(f"Team {team_number} Performance Trend ({trend_direction})", 
                    fontsize=14, fontweight='bold')
        ax.set_xlabel('Match Number', fontsize=12)
        ax.set_ylabel('Total Points', fontsize=12)
        
        # Add legend
        ax.legend(loc='best', frameon=True, shadow=True)
        
        # Add grid
        ax.grid(True, linestyle='--', alpha=0.5, zorder=0)
        
        # Set background color
        ax.set_facecolor(self.colors['background'])
        
        # Format y-axis to show whole numbers
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f'{int(y)}'))
        
        # Add stats text box
        stats_text = f"Slope: {slope:.2f}\nAvg: {sum(scores)/len(scores):.1f}"
        props = dict(boxstyle='round', facecolor='white', alpha=0.8)
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, 
               fontsize=10, verticalalignment='top', bbox=props)
        
        plt.tight_layout()
        return fig