import types
import pytest
import requests

from app.utils.statbotics_api_utils import (
    parse_team_epa,
    get_statbotics_team_epa,
)
from app.utils.analysis import _apply_statbotics_epa, get_epa_metrics_for_team


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


def test_apply_epa_negative_values_clamped(monkeypatch):
    """Negative EPA/OPR values should be treated as zero to avoid negative
    predicted match scores."""
    # statbotics_only mode
    monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa',
                        lambda tn, **kw: {'auto': -5.0, 'teleop': -2.0, 'endgame': -1.0, 'total': -8.0})
    result = {'team_number': 400, 'match_count': 0, 'metrics': {}}
    out = _apply_statbotics_epa(result, 'statbotics_only')
    assert out['metrics']['total_points'] == 0.0
    assert out['metrics']['auto_points'] == 0.0

    # tba_opr_only mode via analysis _apply_statbotics_epa path
    monkeypatch.setattr('app.utils.tba_api_utils.get_tba_team_opr',
                        lambda tn, **kw: {'total': -12.0})
    result2 = {'team_number': 500, 'match_count': 0, 'metrics': {}}
    out2 = _apply_statbotics_epa(result2, 'tba_opr_only')
    assert out2['metrics']['total_points'] == 0.0
    # auto/teleop/endgame keys should not be injected when OPR-only has no breakdown
    assert 'auto_points' not in out2['metrics']


def test_get_epa_metrics_for_team_clamps_negative(monkeypatch):
    """get_epa_metrics_for_team() should never return a negative total."""
    # patch TBA util to return negative value
    monkeypatch.setattr('app.utils.tba_api_utils.get_tba_team_opr',
                        lambda tn, **kw: {'total': -20.0})
    # force EPA source to tba_opr_only so the helper returns the value
    monkeypatch.setattr('app.utils.analysis._get_epa_source_for_team',
                        lambda: 'tba_opr_only')
    data = get_epa_metrics_for_team(1234)
    assert data['total'] == 0.0


def test_refresh_opr_epa_for_event_calls_backends(monkeypatch):
    called = {'epa': [], 'opr': []}

    monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa',
                        lambda tn, **kw: called['epa'].append((tn, kw)) or {'total': 11.1})
    monkeypatch.setattr('app.utils.tba_api_utils.get_tba_team_opr',
                        lambda tn, event_key=None: called['opr'].append((tn, event_key)) or {'total': 22.2})

    from app.utils.analysis import refresh_opr_epa_for_event
    refresh_opr_epa_for_event('2026ARLI', team_numbers=[254, 1678])

    assert len(called['epa']) == 2
    assert (254, {'use_cache': False}) in called['epa']
    assert len(called['opr']) == 2
    assert called['opr'][0][1] == '2026arli'


def test_get_epa_metrics_for_team_statbotics_fallbacks_to_tba(monkeypatch):
    """When Statbotics is unavailable, get_epa_metrics_for_team should use TBA OPR."""
    # force EPA source to scouted_with_statbotics
    monkeypatch.setattr('app.utils.analysis._get_epa_source_for_team',
                        lambda: 'scouted_with_statbotics')

    # Simulate statbotics missing
    monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa',
                        lambda tn, **kw: None)
    # Simulate TBA returning a good OPR
    monkeypatch.setattr('app.utils.tba_api_utils.get_tba_team_opr',
                        lambda tn, **kw: {'total': 42.5})

    data = get_epa_metrics_for_team(1111)
    assert data['total'] == 42.5
    assert data['epa_source'] == 'scouted_with_statbotics'


def test_apply_epa_uses_tba_fallback_when_statbotics_missing(monkeypatch):
    """_apply_statbotics_epa should use TBA OPR if Statbotics yields no EPA."""
    monkeypatch.setattr('app.utils.statbotics_api_utils.get_statbotics_team_epa',
                        lambda tn: None)
    monkeypatch.setattr('app.utils.tba_api_utils.get_tba_team_opr',
                        lambda tn: {'total': 23.1})

    result = {'team_number': 2222, 'match_count': 0, 'metrics': {}}
    out = _apply_statbotics_epa(result, 'scouted_with_statbotics')
    assert out['metrics']['total_points'] == 23.1
    assert out['metrics']['_epa_source'] == 'tba_opr'


def test_get_team_epa_transient_network_error_does_not_cache_miss(monkeypatch):
    """Transient Statbotics failures (5xx / network) should not create a permanent miss."""
    monkeypatch.setattr('app.utils.statbotics_api_utils._sb_client', None)

    def fake_get(*args, **kwargs):
        raise requests.RequestException("timeout")

    monkeypatch.setattr('app.utils.statbotics_api_utils.requests.get', fake_get)

    cache_calls = {'epa': 0, 'db': 0}

    def fake_epa_cache_set(key, value):
        cache_calls['epa'] += 1

    def fake_db_cache_put(team_number, epa_dict):
        cache_calls['db'] += 1

    monkeypatch.setattr('app.utils.statbotics_api_utils._epa_cache_set', fake_epa_cache_set)
    monkeypatch.setattr('app.utils.statbotics_api_utils._db_cache_put', fake_db_cache_put)

    data = get_statbotics_team_epa(254, use_cache=False)
    assert data is None
    assert cache_calls['epa'] == 0
    assert cache_calls['db'] == 0


def test_rest_api_500_raises_transient_error(monkeypatch):
    monkeypatch.setattr('app.utils.statbotics_api_utils._sb_client', None)

    class DummyResp:
        status_code = 500

        def json(self):
            return {}

    monkeypatch.setattr('app.utils.statbotics_api_utils.requests.get', lambda *args, **kwargs: DummyResp())

    from app.utils.statbotics_api_utils import StatboticsTransientError, _rest_api_get_team_epa

    with pytest.raises(StatboticsTransientError):
        _rest_api_get_team_epa(254)
