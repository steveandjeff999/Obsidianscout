from types import SimpleNamespace
from app.utils.team_isolation import dedupe_team_list


def make_team(number, scouting_team=None, name=None):
    return SimpleNamespace(team_number=number, scouting_team_number=scouting_team, team_name=name)


def test_dedupe_prefers_alliance_member():
    # Two team records with same team_number: one belongs to alliance member, one to another team
    t1 = make_team(100, scouting_team=10, name='Local')
    t2 = make_team(100, scouting_team=20, name='Alliance')

    teams = [t1, t2]

    deduped = dedupe_team_list(teams, prefer_alliance=True, alliance_team_numbers=[20], current_scouting_team=10)
    assert len(deduped) == 1
    assert deduped[0].scouting_team_number == 20


def test_dedupe_prefers_local_when_not_alliance():
    t1 = make_team(101, scouting_team=10, name='Local')
    t2 = make_team(101, scouting_team=20, name='Other')

    teams = [t2, t1]  # order swapped to ensure preference picks local

    deduped = dedupe_team_list(teams, prefer_alliance=False, alliance_team_numbers=[20], current_scouting_team=10)
    assert len(deduped) == 1
    assert deduped[0].scouting_team_number == 10


def test_dedupe_handles_multiple_teams():
    t1 = make_team(200, scouting_team=10)
    t2 = make_team(201, scouting_team=10)
    t3 = make_team(200, scouting_team=20)

    deduped = dedupe_team_list([t1, t2, t3], prefer_alliance=True, alliance_team_numbers=[20], current_scouting_team=10)
    assert len(deduped) == 2
    assert {t.team_number for t in deduped} == {200, 201}