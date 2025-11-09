"""
Test script for offseason team remapping functionality.

This script tests the team remapping feature that handles offseason events
where teams use letter suffixes (e.g., 581B, 1678C) that map to 99xx numbers.

Example remap_teams from TBA:
{
  "frc9971": "frc971B",
  "frc9989": "frc581B",
  "frc9996": "frc1678C",
  "frc9997": "frc1678B",
  "frc9998": "frc1323C",
  "frc9999": "frc1323B"
}

Usage:
    python test_team_remapping.py
"""

def test_remap_team_number():
    """Test the remap_team_number function with various inputs"""
    from app.utils.tba_api_utils import remap_team_number, _event_remap_cache
    
    print("Testing team remapping functionality...")
    print("=" * 60)
    
    # Mock an event's remap_teams data
    test_event_key = "2025casj"
    _event_remap_cache[test_event_key] = {
        "581B": 9989,
        "581C": 9988,
        "1678B": 9997,
        "1678C": 9996,
        "1678D": 9986,
        "1323B": 9999,
        "1323C": 9998,
        "254B": 9994
    }
    
    # Test cases
    test_cases = [
        # (input, event_key, expected_output, description)
        ("581B", test_event_key, 9989, "Letter suffix team with remapping"),
        ("frc581B", test_event_key, 9989, "Letter suffix with frc prefix"),
        ("1678C", test_event_key, 9996, "Another letter suffix team"),
        ("5454", test_event_key, 5454, "Regular numeric team"),
        (5454, test_event_key, 5454, "Integer team number"),
        ("254", test_event_key, 254, "Numeric string team"),
        ("581b", test_event_key, 9989, "Lowercase letter suffix"),
        ("9999Z", test_event_key, "9999Z", "Letter suffix without remapping"),
        ("", test_event_key, None, "Empty string"),
        (None, test_event_key, None, "None input"),
    ]
    
    passed = 0
    failed = 0
    
    for input_val, event_key, expected, description in test_cases:
        result = remap_team_number(input_val, event_key)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status}: {description}")
        print(f"  Input: {repr(input_val)} → Output: {repr(result)} (Expected: {repr(expected)})")
        if result != expected:
            print(f"  ERROR: Mismatch!")
        print()
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return failed == 0


def test_tba_match_conversion():
    """Test match conversion with remapped team numbers"""
    from app.utils.tba_api_utils import tba_match_to_db_format, _event_remap_cache
    
    print("Testing TBA match conversion with team remapping...")
    print("=" * 60)
    
    # Mock event remap data
    test_event_key = "2025casj"
    _event_remap_cache[test_event_key] = {
        "581B": 9989,
        "1678C": 9996,
        "254B": 9994
    }
    
    # Mock TBA match data with letter-suffix teams
    tba_match = {
        "key": "2025casj_qm1",
        "comp_level": "qm",
        "match_number": 1,
        "alliances": {
            "red": {
                "team_keys": ["frc581B", "frc1678C", "frc254"],
                "score": 120
            },
            "blue": {
                "team_keys": ["frc5454", "frc254B", "frc1323"],
                "score": 115
            }
        }
    }
    
    result = tba_match_to_db_format(tba_match, event_id=1, event_key=test_event_key)
    
    print("Input match:")
    print(f"  Red: {tba_match['alliances']['red']['team_keys']}")
    print(f"  Blue: {tba_match['alliances']['blue']['team_keys']}")
    print()
    
    print("Converted match:")
    print(f"  Red alliance: {result['red_alliance']}")
    print(f"  Blue alliance: {result['blue_alliance']}")
    print()
    
    # Verify remapping
    expected_red = "9989,9996,254"  # 581B→9989, 1678C→9996, 254→254
    expected_blue = "5454,9994,1323"  # 5454→5454, 254B→9994, 1323→1323
    
    red_ok = result['red_alliance'] == expected_red
    blue_ok = result['blue_alliance'] == expected_blue
    
    if red_ok and blue_ok:
        print("✓ PASS: Team remapping worked correctly")
        return True
    else:
        print("✗ FAIL: Team remapping did not work as expected")
        if not red_ok:
            print(f"  Red alliance: expected {expected_red}, got {result['red_alliance']}")
        if not blue_ok:
            print(f"  Blue alliance: expected {expected_blue}, got {result['blue_alliance']}")
        return False


def test_safe_int_team_number():
    """Test the safe_int_team_number utility"""
    from app.utils.api_utils import safe_int_team_number
    
    print("Testing safe_int_team_number utility...")
    print("=" * 60)
    
    test_cases = [
        (5454, 5454, "Integer input"),
        ("5454", 5454, "Numeric string"),
        ("581B", "581B", "Letter suffix (uppercase)"),
        ("581b", "581B", "Letter suffix (lowercase)"),
        ("  1678  ", 1678, "String with whitespace"),
        ("", None, "Empty string"),
        (None, None, "None input"),
        ("9999Z", "9999Z", "Number with letter suffix"),
    ]
    
    passed = 0
    failed = 0
    
    for input_val, expected, description in test_cases:
        result = safe_int_team_number(input_val)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status}: {description}")
        print(f"  Input: {repr(input_val)} → Output: {repr(result)} (Expected: {repr(expected)})")
        if result != expected:
            print(f"  ERROR: Mismatch!")
        print()
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return failed == 0


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("OFFSEASON TEAM REMAPPING TEST SUITE")
    print("=" * 60 + "\n")
    
    all_passed = True
    
    try:
        # Run tests
        all_passed &= test_safe_int_team_number()
        all_passed &= test_remap_team_number()
        all_passed &= test_tba_match_conversion()
        
        print("\n" + "=" * 60)
        if all_passed:
            print("✓ ALL TESTS PASSED")
            print("\nThe fix successfully handles offseason teams like 581B, 1678C")
            print("by mapping them to their 99xx equivalents (9989, 9996, etc.)")
        else:
            print("✗ SOME TESTS FAILED")
            print("\nPlease review the failures above.")
        print("=" * 60 + "\n")
        
    except Exception as e:
        print(f"\n✗ TEST SUITE ERROR: {e}")
        import traceback
        traceback.print_exc()
