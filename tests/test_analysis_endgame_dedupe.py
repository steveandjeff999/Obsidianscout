from app.utils import analysis


def make_team(team_number):
    return {
        'team': type('T', (), {'team_number': team_number}),
        'metrics': {'tot': 10, 'apt': 0, 'tpt': 10, 'ept': 0},
        'scouting_data': []
    }


def test_analyze_alliance_endgame_coordination_dedupe():
    # Construct alliance data with duplicates
    alliance_data = [make_team(2165), make_team(2373), make_team(4766), make_team(2165), make_team(2373)]
    game_config = {'endgame_period': {'scoring_elements': []}}

    result = analysis._analyze_alliance_endgame_coordination(alliance_data, game_config)
    assert 'team_capabilities' in result
    # Dedupe should ensure unique team numbers
    team_numbers = [tc['team_number'] for tc in result['team_capabilities']]
    assert len(team_numbers) == len(set(team_numbers))


def test_identify_key_battles_dedupe():
    red = [make_team(1), make_team(2), make_team(1)]
    blue = [make_team(3), make_team(4), make_team(4)]
    battles = analysis._identify_key_battles(red, blue, {})
    # Should produce at least one battle and not crash due to duplicates
    assert isinstance(battles, list)
    assert len(battles) >= 1
