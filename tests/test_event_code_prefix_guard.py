from app.utils.api_utils import strip_year_prefix
from app.utils.event_code_utils import (
    build_year_prefixed_event_code,
    event_code_variants,
    normalize_current_event_code_for_config,
    normalize_event_code,
)
from app.utils.tba_api_utils import construct_tba_event_key


def test_build_year_prefixed_event_code_avoids_double_prefix():
    assert build_year_prefixed_event_code("OKOK", season=2026) == "2026OKOK"
    assert build_year_prefixed_event_code("2026OKOK", season=2026) == "2026OKOK"
    assert build_year_prefixed_event_code("20262026OKOK", season=2026) == "2026OKOK"


def test_strip_year_prefix_handles_malformed_duplicates():
    assert strip_year_prefix("2026OKOK") == "OKOK"
    assert strip_year_prefix("20262026OKOK") == "OKOK"


def test_construct_tba_event_key_never_double_prefixes_year():
    assert construct_tba_event_key("OKOK", year=2026) == "2026okok"
    assert construct_tba_event_key("2026OKOK", year=2026) == "2026okok"
    assert construct_tba_event_key("20262026OKOK", year=2026) == "2026okok"


def test_config_normalization_prefers_raw_for_active_season():
    assert normalize_current_event_code_for_config("2026OKOK", season=2026) == "OKOK"
    assert normalize_current_event_code_for_config("20262026OKOK", season=2026) == "OKOK"
    assert normalize_current_event_code_for_config("2025OKOK", season=2026) == "2025OKOK"


def test_event_code_normalization_and_variants_cover_legacy_and_modern():
    assert normalize_event_code(" 20262026okok ") == "2026OKOK"

    variants = event_code_variants("20262026OKOK", season=2026)
    assert variants[0] == "2026OKOK"
    assert "OKOK" in variants
