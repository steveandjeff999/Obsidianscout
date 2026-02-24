"""Full diagnostic: run get_matches_dual_api for 2026week0 and show playoff output."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('FLASK_ENV', 'testing')

from app import create_app
app = create_app()

from app.utils.api_utils import _merge_match_lists, get_matches_dual_api, api_to_db_match_conversion
from app.utils.tba_api_utils import tba_match_to_db_format, get_tba_event_matches

TBA_KEY = 'hae7pfixkaYpROTHhMx6XQ5qLkjT5v7jX7IymIp3sFadVOTsboxkSVJlYu4yoq9a'

with app.app_context():
    print("=== Running merge simulation with real TBA data ===")

    # Fetch real TBA data
    tba_raw = get_tba_event_matches('2026week0')
    primary_matches = []
    for m in tba_raw:
        md = tba_match_to_db_format(m, None, event_key='2026week0')
        if md:
            primary_matches.append(md)

    print(f"TBA records: {len(primary_matches)}")
    # Show TBA playoffs
    tba_po = [m for m in primary_matches if m.get('match_type') == 'Playoff']
    print(f"TBA Playoff records: {len(tba_po)}")
    for m in sorted(tba_po, key=lambda x: (x.get('comp_level',''), x.get('set_number',0), x.get('match_number',0))):
        print(f"  cl={m.get('comp_level'):4s} sn={m.get('set_number'):2d} mn={m.get('match_number'):2d}  "
              f"raw={m.get('raw_match_number'):2d}  red={m.get('red_alliance','')[:20]}  blue={m.get('blue_alliance','')[:20]}")

    # Simulate FIRST fallback (empty since no credentials)
    fallback_matches = []

    print()
    print("=== Merged result (TBA only) ===")
    merged = _merge_match_lists(primary_matches, fallback_matches)
    po = [m for m in merged if m.get('match_type') == 'Playoff']
    print(f"Total playoffs after merge: {len(po)} (expected 16)")
    for m in po:
        print(f"  mn={m.get('match_number'):3d}  cl={str(m.get('comp_level')):4s}  sn={m.get('set_number'):2d}  "
              f"display={str(m.get('display_match_number')):5s}  "
              f"red={str(m.get('red_alliance',''))[:18]}  blue={str(m.get('blue_alliance',''))[:18]}")

    print()
    ns = sorted(po, key=lambda m: m.get('match_number', 0))
    nums = [m.get('match_number') for m in ns]
    print(f"match_numbers: {nums}")
    dups = [n for n in nums if nums.count(n) > 1]
    if dups:
        print(f"DUPLICATES: {dups}")
    else:
        print("No duplicates ✓")
