"""
Test trend visualization generation
"""

import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_trend_analysis():
    """Test trend analysis with visualization"""
    from app import create_app
    from app.assistant import get_assistant
    
    app = create_app()
    
    with app.app_context():
        assistant = get_assistant()
        
        # Test trend analysis
        print("Testing: 'trends for team 5454'")
        result = assistant.answer_question("trends for team 5454")
        
        print("\n=== RESPONSE ===")
        print(result.get('text', 'No text'))
        
        print("\n=== VISUALIZATION OPTIONS ===")
        vis_options = result.get('visualization_options')
        if vis_options:
            print(f"Type: {vis_options.get('type')}")
            print(f"Team Number: {vis_options.get('data', {}).get('team_number')}")
            print(f"Matches: {len(vis_options.get('data', {}).get('match_scores', []))}")
            print(f"Slope: {vis_options.get('data', {}).get('slope', 0):.4f}")
            print(f"Intercept: {vis_options.get('data', {}).get('intercept', 0):.2f}")
        else:
            print("No visualization options returned")
        
        print("\n=== TREND DATA ===")
        trend_data = result.get('trend_data')
        if trend_data:
            print(f"Matches Analyzed: {trend_data.get('matches_analyzed')}")
            print(f"Trend Percentage: {trend_data.get('trend_percentage', 0):.1f}%")
            print(f"First Half Avg: {trend_data.get('first_half_avg', 0):.1f}")
            print(f"Second Half Avg: {trend_data.get('second_half_avg', 0):.1f}")
        
        # Test visualization generation
        if vis_options:
            print("\n=== TESTING VISUALIZATION GENERATION ===")
            from app.assistant import get_visualizer
            visualizer = get_visualizer()
            
            vis_result = visualizer.generate_visualization(
                vis_options['type'],
                vis_options['data']
            )
            
            if vis_result.get('error'):
                print(f" Visualization Error: {vis_result.get('message')}")
            else:
                print(f" Visualization generated successfully!")
                print(f"   Image size: {len(vis_result.get('image', ''))} bytes (base64)")
                print(f"   Type: {vis_result.get('type')}")

if __name__ == '__main__':
    test_trend_analysis()
