"""
Comprehensive test of new advanced analytics features
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
app = create_app()

with app.app_context():
    from app.assistant import get_assistant
    assistant = get_assistant()
    
    print("=" * 70)
    print("ADVANCED ANALYTICS TEST - NEW CAPABILITIES")
    print("=" * 70)
    
    test_categories = {
        "Trend Analysis": [
            "trends for team 5454",
            "is team 254 improving",
            "team 1234 performance over time"
        ],
        "Predictions": [
            "predict team 5454 performance",
            "who will win match 5",
            "will team 254 win"
        ],
        "Consistency Analysis": [
            "consistency of team 5454",
            "how reliable is team 254"
        ],
        "Peak Performance": [
            "peak performance for team 5454",
            "best match for team 254"
        ],
        "Strengths & Weaknesses": [
            "strengths of team 5454",
            "weaknesses of team 254"
        ],
        "Alliance Predictions": [
            "what if team 5454 and 254 team up",
            "alliance between 5454 and 118"
        ]
    }
    
    passed = 0
    failed = 0
    
    for category, queries in test_categories.items():
        print(f"\n{'=' * 70}")
        print(f"CATEGORY: {category}")
        print('=' * 70)
        
        for query in queries:
            print(f"\nQuery: '{query}'")
            print("-" * 70)
            
            try:
                result = assistant.answer_question(query)
                
                if result and not result.get('error'):
                    text = result.get('text', '').encode('ascii', 'ignore').decode('ascii')
                    print(f"SUCCESS")
                    print(f"Response: {text[:200]}...")
                    
                    # Check for specific data structures
                    if result.get('trend_data'):
                        print(f"  - Trend data present: {result['trend_data'].get('trend_percentage', 0):.1f}%")
                    if result.get('prediction'):
                        print(f"  - Prediction data present")
                    if result.get('consistency'):
                        print(f"  - Consistency analysis: CV={result['consistency'].get('cv', 0):.1f}%")
                    
                    passed += 1
                else:
                    error_text = result.get('text', 'Unknown error')[:100] if result else 'No result'
                    print(f"FAILED: {error_text}")
                    failed += 1
                    
            except Exception as e:
                print(f"EXCEPTION: {type(e).__name__}: {str(e)}")
                failed += 1
    
    print(f"\n{'=' * 70}")
    print(f"TEST SUMMARY")
    print(f"{'=' * 70}")
    print(f"Total queries: {passed + failed}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Success rate: {(passed / (passed + failed) * 100):.1f}%")
    
    print(f"\n{'=' * 70}")
    print("NEW CAPABILITIES SUMMARY")
    print(f"{'=' * 70}")
    print("""
The assistant now supports:

1. TREND ANALYSIS
   - Analyze team performance trends over time
   - Identify improving/declining teams
   - Track trajectory and momentum
   
2. PREDICTIONS
   - Predict future team performance
   - Forecast match winners
   - Calculate win probabilities
   
3. CONSISTENCY ANALYSIS
   - Measure team reliability
   - Calculate performance variance
   - Identify consistent vs unpredictable teams
   
4. PEAK PERFORMANCE
   - Find best matches for teams
   - Identify ceiling potential
   - Understand optimal conditions
   
5. STRENGTHS & WEAKNESSES
   - Analyze team capabilities
   - Identify areas for improvement
   - Guide alliance selection
   
6. ALLIANCE PREDICTIONS
   - Predict combined team performance
   - Analyze synergies
   - Forecast alliance strength

Try queries like:
  - "trends for team 5454"
  - "predict who will win match 5"
  - "how consistent is team 254"
  - "strengths of team 118"
  - "what if 5454 and 254 team up"
    """)
