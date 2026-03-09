import re
import pathlib

def test_offline_script_contains_dedupe():
    """Offline JS should include dedupeSelectOptions and call it during init."""
    script_path = pathlib.Path(__file__).parent.parent / 'app' / 'static' / 'js' / 'scouting_form_offline.js'
    content = script_path.read_text(encoding='utf-8')

    # ensure function is defined
    assert 'function dedupeSelectOptions' in content, "dedupeSelectOptions function missing"

    # ensure init calls it for match-selector and team-selector
    init_block = re.search(r'function initializeOfflineCache\([\s\S]*?\}', content)
    assert init_block, "could not find initializeOfflineCache definition"
    init_text = init_block.group(0)

    assert 'dedupeSelectOptions(matchSel)' in init_text, "initializeOfflineCache does not call dedupeSelectOptions for matchSel"
    assert 'dedupeSelectOptions(teamSel)' in init_text, "initializeOfflineCache does not call dedupeSelectOptions for teamSel"
