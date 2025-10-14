"""
Diagnostic script to check what matches exist in the database
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
app = create_app()

with app.app_context():
    from app.models import Match
    
    print("=" * 60)
    print("DATABASE MATCH INVENTORY")
    print("=" * 60)
    
    # Get all matches
    all_matches = Match.query.order_by(Match.match_number).all()
    
    if not all_matches:
        print("\nNO MATCHES FOUND IN DATABASE!")
    else:
        print(f"\nTotal matches: {len(all_matches)}")
        print("\nMatch breakdown by type:")
        
        by_type = {}
        for match in all_matches:
            match_type = match.match_type or "None"
            if match_type not in by_type:
                by_type[match_type] = []
            by_type[match_type].append(match.match_number)
        
        for match_type, numbers in sorted(by_type.items()):
            print(f"\n  {match_type.upper()}:")
            numbers.sort()
            print(f"    Match numbers: {', '.join(map(str, numbers))}")
        
        print("\n" + "-" * 60)
        print("Sample matches (first 10):")
        print("-" * 60)
        
        for match in all_matches[:10]:
            status = "completed" if match.red_score is not None else "upcoming"
            print(f"  Match {match.match_number} ({match.match_type}) - {status}")
    
    print("\n" + "=" * 60)
    
    # Test specific queries
    print("\nTesting specific queries:")
    print("-" * 60)
    
    test_cases = [
        (5, None),
        (5, 'qualification'),
        (5, 'playoff'),
        (3, 'playoff'),
    ]
    
    for match_num, match_type in test_cases:
        from sqlalchemy import func
        query = Match.query.filter_by(match_number=match_num)
        if match_type:
            match_type_map = {
                'practice': 'practice',
                'qual': 'qualification',
                'qualification': 'qualification',
                'playoff': 'playoff',
                'elim': 'playoff',
            }
            normalized = match_type_map.get(match_type.lower())
            if normalized:
                # Case-insensitive comparison
                query = query.filter(func.lower(Match.match_type) == normalized.lower())
        
        result = query.first()
        type_str = f" ({match_type})" if match_type else ""
        if result:
            print(f"  Match {match_num}{type_str}: FOUND - type={result.match_type}")
        else:
            print(f"  Match {match_num}{type_str}: NOT FOUND")
    
    print("=" * 60)
