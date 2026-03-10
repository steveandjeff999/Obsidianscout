import re
import pathlib

def test_offline_script_contains_dedupe():
    """Offline JS should include dedupeSelectOptions and call it during init."""
    script_path = pathlib.Path(__file__).parent.parent / 'app' / 'static' / 'js' / 'scouting_form_offline.js'
    content = script_path.read_text(encoding='utf-8')

    # ensure function is defined
    assert 'function dedupeSelectOptions' in content, "dedupeSelectOptions function missing"

    # ensure init calls it for match-selector and team-selector
    # check that the calls appear somewhere after function declaration
    assert re.search(r'initializeOfflineCache\([\s\S]*dedupeSelectOptions\(matchSel\)', content), \
        "initializeOfflineCache does not call dedupeSelectOptions for matchSel"
    assert re.search(r'initializeOfflineCache\([\s\S]*dedupeSelectOptions\(teamSel\)', content), \
        "initializeOfflineCache does not call dedupeSelectOptions for teamSel"
