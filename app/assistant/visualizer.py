"""
Scout Assistant Visualizer
Creates graphs and visual representations of scouting data
"""

import json
import io
import base64
from typing import Dict, List, Any, Tuple, Optional
import matplotlib
matplotlib.use('Agg')  # Use Agg backend to avoid requiring a display
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import numpy as np
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
        sns.set_theme(style="whitegrid")
        plt.rcParams['figure.figsize'] = (10, 6)
        plt.rcParams['font.size'] = 12
        
        # Use team 5454 colors
        self.colors = {
            'primary': '#E51837',    # Team 5454 red
            'secondary': '#0066B3',  # Blue
            'tertiary': '#FFD100',   # Yellow
            'background': '#F5F5F5', # Light gray background
            'text': '#333333',       # Dark gray text
        }
        
        # Color palettes for multi-team visualizations
        self.palette = sns.color_palette([
            self.colors['primary'],
            self.colors['secondary'],
            '#00A651',  # Green
            '#FF8200',  # Orange
            '#8A2BE2',  # Purple
        ])
    
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
            'ranking_comparison': self.plot_ranking_comparison
        }
        
        if vis_type not in visualization_methods:
            return {
                "error": True,
                "message": f"Unsupported visualization type: {vis_type}"
            }
        
        try:
            # Call the appropriate visualization method
            figure = visualization_methods[vis_type](data)
            
            # Convert plot to base64-encoded image
            img_data = self.figure_to_base64(figure)
            
            # Close the figure to free memory
            plt.close(figure)
            
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
        
        # Metrics for radar chart
        metrics = ['auto_points', 'teleop_points', 'endgame_points', 
                   'scoring_efficiency', 'defense_rating', 'climb_success_rate']
        metric_labels = ['Auto', 'Teleop', 'Endgame', 'Scoring', 'Defense', 'Climb']
        
        # Set up radar chart
        angles = np.linspace(0, 2*np.pi, len(metrics), endpoint=False).tolist()
        angles += angles[:1]  # Close the loop
        
        fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))
        
        # Add lines for each team
        for i, team in enumerate(teams):
            stats = team.get('stats', {})
            values = [stats.get(m, 0) for m in metrics]
            
            # Normalize values for radar chart (0-1)
            max_values = [30, 50, 20, 1, 5, 1]  # Example max values for each metric
            norm_values = [min(v/max_v, 1) for v, max_v in zip(values, max_values)]
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