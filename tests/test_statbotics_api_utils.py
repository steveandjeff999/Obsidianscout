import types

from app.utils.statbotics_api_utils import (
    parse_team_epa,
    get_statbotics_team_epa,
)
from app.utils.analysis import _apply_statbotics_epa


SAMPLE_HTML = """
<div>
  Team 254 (The Cheesy Poofs)
  EPA Breakdown:Auto: 5.9Teleop: 5.9Endgame: 5.9Total: 17.6
  [11 Worldwide out of 3776] [9 USA out of 2782]
</div>
"""


def test_parse_team_epa():
    parsed = parse_team_epa(SAMPLE_HTML)
    assert parsed is not None
    assert round(parsed["auto"], 1) == 5.9
    assert round(parsed["teleop"], 1) == 5.9
    assert round(parsed["endgame"], 1) == 5.9
    assert round(parsed["total"], 1) == 17.6
    assert parsed["rank_world"] == 11
    assert parsed["rank_country"] == 9


def test_get_team_epa_requests(monkeypatch):
    """When no client is available, fall back through REST API then HTML scraping."""
    # Disable the official client
    monkeypatch.setattr('app.utils.statbotics_api_utils._sb_client', None)
    monkeypatch.setattr('app.utils.statbotics_api_utils._sb_instance', None)

    class DummyResp:
        status_code = 200
        text = SAMPLE_HTML
        def json(self):
            raise ValueError("not json")

    call_count = {'n': 0}
    def fake_get(url, headers=None, timeout=None):
        call_count['n'] += 1
        # REST API calls return 404 to force HTML fallback
        if 'api.statbotics.io' in url:
            r = DummyResp()
            r.status_code = 404
            return r
        assert "statbotics.io" in url
        return DummyResp()

    monkeypatch.setattr('app.utils.statbotics_api_utils.requests.get', fake_get)

    data = get_statbotics_team_epa(254, use_cache=False)
    assert data is not None
    assert round(data["total"], 1) == 17.6


def test_prefers_official_client_statbotics_class(monkeypatch):
    """Official client with Statbotics().get_team_year() should be preferred."""
    class FakeStatbotics:
        def get_team_year(self, team_number, year):
            return {
                'team': team_number, 'year': year,
                'epa': {
                    'breakdown': {
                        'auto_points': 1.0, 'teleop_points': 2.0,
                        'endgame_points': 3.0, 'total_points': 6.0
                    }
                }
            }

    import types
    fake_mod = types.SimpleNamespace(Statbotics=FakeStatbotics)
    monkeypatch.setattr('app.utils.statbotics_api_utils._sb_client', fake_mod)
    monkeypatch.setattr('app.utils.statbotics_api_utils._sb_instance', None)
    monkeypatch.setattr('app.utils.statbotics_api_utils.requests.get',
                        lambda *a, **k: (_ for _ in ()).throw(Exception("requests called")))

    data = get_statbotics_team_epa(254, use_cache=False)
    assert data is not None
    assert data["total"] == 6.0
    assert data["auto"] == 1.0
    assert data["endgame"] == 3.0


def test_rest_api_fallback(monkeypatch):
    """When client is unavailable, REST API JSON endpoint should work."""
    import json as _json

    monkeypatch.setattr('app.utils.statbotics_api_utils._sb_client', None)
    monkeypatch.setattr('app.utils.statbotics_api_utils._sb_instance', None)

    class DummyResp:
        status_code = 200
        def json(self):
            return {
                'team': 1678, 'year': 2025,
                'epa': {
                    'breakdown': {
                        'auto_points': 7.1, 'teleop_points': 8.2,
                        'endgame_points': 9.3, 'total_points': 24.6,
                    }
                }
            }

    def fake_get(url, headers=None, timeout=None):
        if 'api.statbotics.io' in url:
            return DummyResp()
        raise Exception("should not reach HTML path")

    monkeypatch.setattr('app.utils.statbotics_api_utils.requests.get', fake_get)

    data = get_statbotics_team_epa(1678, use_cache=False)
    assert data is not None
    assert round(data["total"], 1) == 24.6
    assert round(data["auto"], 1) == 7.1


# ---------------------------------------------------------------------------
# Tests for _apply_statbotics_epa enrichment
# ---------------------------------------------------------------------------

def test_apply_epa_scouted_only_no_change(monkeypatch):
    """scouted_only mode should leave metrics untouched."""
    result = {'team_number': 100, 'match_count': 3, 'metrics': {'total_points': 42.0}}
    out = _apply_statbotics_epa(result, 'scouted_only')
    assert out['metrics']['total_points'] == 42.0
    assert '_epa_source' not in out['metrics']


def test_apply_epa_gap_fill_with_data(monkeypatch):
    """Gap-fill mode should NOT override when team has 3+ scouted matches."""
    result = {'team_number': 100, 'match_count': 3, 'metrics': {'total_points': 50.0}}
    out = _apply_statbotics_epa(result, 'scouted_with_statbotics')
    assert out['metrics']['total_points'] == 50.0
    assert '_epa_source' not in out['metrics']


def test_apply_epa_gap_fill_no_data(monkeypatch):
    """Gap-fill mode should inject EPA when match_count == 0."""
    monkeypatch.setattr('app.utils.analysis.get_statbotics_team_epa',
                        lambda tn: {'auto': 5.0, 'teleop': 6.0, 'endgame': 7.0, 'total': 18.0},
                        raising=False)
    # need to patch at the import target inside analysis
    import app.utils.analysis as _an
    orig = getattr(_an, 'get_statbotics_team_epa', None)
    monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa',
                        lambda tn, **kw: {'auto': 5.0, 'teleop': 6.0, 'endgame': 7.0, 'total': 18.0})

    result = {'team_number': 999, 'match_count': 0, 'metrics': {}}
    out = _apply_statbotics_epa(result, 'scouted_with_statbotics')
    assert out['metrics']['total_points'] == 18.0
    assert out['metrics']['auto_points'] == 5.0
    assert out['metrics']['_epa_source'] == 'statbotics'


def test_apply_epa_statbotics_only(monkeypatch):
    """statbotics_only mode should always replace metrics."""
    monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa',
                        lambda tn, **kw: {'auto': 10.0, 'teleop': 11.0, 'endgame': 12.0, 'total': 33.0})

    result = {'team_number': 254, 'match_count': 5, 'metrics': {'total_points': 99.0}}
    out = _apply_statbotics_epa(result, 'statbotics_only')
    assert out['metrics']['total_points'] == 33.0
    assert out['metrics']['auto_points'] == 10.0
    assert out['metrics']['_epa_source'] == 'statbotics'


def test_apply_epa_graduated_blend_1_match(monkeypatch):
    """With 1 scouted match, blend should be 70% EPA / 30% scouted."""
    monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa',
                        lambda tn, **kw: {'auto': 10.0, 'teleop': 10.0, 'endgame': 10.0, 'total': 30.0})

    result = {'team_number': 200, 'match_count': 1,
              'metrics': {'auto_points': 20.0, 'teleop_points': 20.0,
                          'endgame_points': 20.0, 'total_points': 60.0}}
    out = _apply_statbotics_epa(result, 'scouted_with_statbotics')
    # 70% EPA (10) + 30% scouted (20) = 7 + 6 = 13
    assert round(out['metrics']['auto_points'], 1) == 13.0
    assert round(out['metrics']['total_points'], 1) == 39.0
    assert out['metrics']['_epa_source'] == 'blended'


def test_apply_epa_graduated_blend_2_matches(monkeypatch):
    """With 2 scouted matches, blend should be 30% EPA / 70% scouted."""
    monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa',
                        lambda tn, **kw: {'auto': 10.0, 'teleop': 10.0, 'endgame': 10.0, 'total': 30.0})

    result = {'team_number': 300, 'match_count': 2,
              'metrics': {'auto_points': 20.0, 'teleop_points': 20.0,
                          'endgame_points': 20.0, 'total_points': 60.0}}
    out = _apply_statbotics_epa(result, 'scouted_with_statbotics')
    # 30% EPA (10) + 70% scouted (20) = 3 + 14 = 17
    assert round(out['metrics']['auto_points'], 1) == 17.0
    assert round(out['metrics']['total_points'], 1) == 51.0
    assert out['metrics']['_epa_source'] == 'blended'
