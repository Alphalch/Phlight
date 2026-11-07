"""Tests for file input errors, configuration loading, home validation, and state precedence (contract §§2, 4, 7, 8, 10, 13.2, 13.5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from phlight.aircraft import (
    DEFAULT_SOURCE_PATH,
    HomeLocation,
    SelectionConfig,
    SourceSnapshot,
    load_config,
    load_source_path,
    read_snapshot,
    select,
    select_from_file,
)

from .conftest import CONTROLLED_NOW, HONG_KONG_HOME, make_snapshot


@pytest.mark.parametrize(
    ("fixture_name", "expected_state", "expected_reason"),
    [
        ("does_not_exist.json", "missing_input", "file_not_found"),
        ("synthetic_empty_file.json", "invalid_input", "json_decode"),
        ("synthetic_malformed_truncated.json", "invalid_input", "json_decode"),
        ("synthetic_invalid_utf8.json", "invalid_input", "json_decode"),
        ("synthetic_not_an_object.json", "invalid_input", "not_an_object"),
        ("synthetic_aircraft_not_list.json", "invalid_input", "aircraft_not_list"),
        ("synthetic_missing_now.json", "invalid_input", "invalid_now"),
        ("synthetic_milliseconds_now.json", "invalid_input", "invalid_now"),
    ],
)
def test_read_snapshot_and_select_from_file_on_missing_and_malformed_files(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
    fixture_name: str,
    expected_state: str,
    expected_reason: str,
) -> None:
    """Catches raising exceptions or returning wrong state/reason on missing, truncated, empty, non-UTF8, or schema-invalid files (contract §§2.2, 7, 8.2, 10.10, 13.5)."""
    path = fixtures_dir / fixture_name

    snapshot = read_snapshot(path)
    assert snapshot.state == expected_state
    assert snapshot.error == expected_reason
    assert snapshot.file_now is None
    assert snapshot.aircraft == ()

    result = select_from_file(path, hk_config, now=CONTROLLED_NOW)
    assert result.state == expected_state
    assert result.reason == expected_reason
    assert result.aircraft is None
    assert result.snapshot_time is None
    assert result.evaluated_at == pytest.approx(CONTROLLED_NOW, abs=1e-6)
    assert result.snapshot_age_s is None
    assert result.considered_count == 0
    assert result.eligible_count == 0
    assert dict(result.rejected) == {}


def test_read_snapshot_directory_path_returns_io_error(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches unhandled IsADirectoryError/OSError when the configured path points to a directory (contract §8.2)."""
    snapshot = read_snapshot(fixtures_dir)
    assert snapshot.state == "missing_input"
    assert snapshot.error in ("io_error", "permission_denied")
    assert snapshot.file_now is None
    assert snapshot.aircraft == ()

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)
    assert result.state == "missing_input"
    assert result.reason == snapshot.error


def test_read_snapshot_permission_error_returns_permission_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches mapping PermissionError to io_error or allowing it to escape read_snapshot() (contract §8.2)."""
    target = tmp_path / "locked_aircraft.json"
    target.write_text('{"now": 1760000000.0, "aircraft": []}', encoding="utf-8")

    def _raise_perm(_self: Path) -> bytes:
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "read_bytes", _raise_perm)

    snapshot = read_snapshot(target)
    assert snapshot.state == "missing_input"
    assert snapshot.error == "permission_denied"
    assert snapshot.file_now is None
    assert snapshot.aircraft == ()


def test_read_snapshot_generic_os_error_returns_io_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches non-FileNotFound/Permission OSError escaping read_snapshot() (contract §8.2)."""
    target = tmp_path / "io_fail_aircraft.json"

    def _raise_os(_self: Path) -> bytes:
        raise OSError("low-level I/O failure")

    monkeypatch.setattr(Path, "read_bytes", _raise_os)

    snapshot = read_snapshot(target)
    assert snapshot.state == "missing_input"
    assert snapshot.error == "io_error"


@pytest.mark.parametrize(
    "bad_now",
    [
        None,
        True,
        "1760000000.0",
        999_999_999.9,
        100_000_000_000.0,
        1_760_000_000_000,
        float("nan"),
        float("inf"),
    ],
)
def test_hand_built_snapshot_with_invalid_file_now_is_rejected_by_select(
    hk_config: SelectionConfig,
    bad_now: object,
) -> None:
    """Catches select() assuming read_snapshot() already validated file_now (contract §§3, 8.3)."""
    snapshot = SourceSnapshot(
        state="ok",
        file_now=bad_now,  # type: ignore[arg-type]
        aircraft=(),
        error=None,
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "invalid_input"
    assert result.reason == "invalid_now"
    assert result.aircraft is None


def test_hand_built_snapshot_with_non_sequence_aircraft_is_rejected_by_select(
    hk_config: SelectionConfig,
) -> None:
    """Catches select() iterating over a string/bytes or non-sequence aircraft field on a hand-built SourceSnapshot."""
    for bad_aircraft in ("not-a-tuple", b"bytes", 42):
        snapshot = SourceSnapshot(
            state="ok",
            file_now=CONTROLLED_NOW,
            aircraft=bad_aircraft,  # type: ignore[arg-type]
            error=None,
        )
        result = select(snapshot, hk_config, now=CONTROLLED_NOW)
        assert result.state == "invalid_input"
        assert result.reason == "aircraft_not_list"


def test_home_location_validation_accepts_numbers_and_rejects_strings_bools_and_out_of_range() -> None:
    """Catches clamping out-of-range coordinates or coercing strings/booleans in HomeLocation (contract §4)."""
    zero_home = HomeLocation(lat=-0.0, lon=0)
    assert zero_home.lat == 0.0
    assert zero_home.lon == 0.0

    pole_home = HomeLocation(lat=-90, lon=180)
    assert pole_home.lat == -90.0
    assert pole_home.lon == 180.0

    for bad_lat, bad_lon, exc_type in [
        ("22.3193", 114.1694, TypeError),
        (22.3193, "114.1694", TypeError),
        (True, 114.1694, TypeError),
        (22.3193, False, TypeError),
        (90.001, 114.1694, ValueError),
        (-90.001, 114.1694, ValueError),
        (22.3193, 180.001, ValueError),
        (22.3193, -180.001, ValueError),
        (float("nan"), 114.1694, ValueError),
        (22.3193, float("inf"), ValueError),
    ]:
        with pytest.raises(exc_type):
            HomeLocation(lat=bad_lat, lon=bad_lon)  # type: ignore[arg-type]


def test_load_config_absent_home_and_invalid_home_states() -> None:
    """Catches inferring a default home or coercing string/out-of-range home coordinates in load_config (contract §§4, 8.4, 10.11, 13.2)."""
    valid_snapshot = make_snapshot(
        [
            {
                "hex": "780abc",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 0.2,
                "seen": 0.1,
            }
        ]
    )

    # 1. Home absent -> unconfigured / home_not_configured
    cfg_absent, probs_absent = load_config({}, environ={})
    assert cfg_absent.home is None
    assert probs_absent == ()
    assert cfg_absent.problems == ()
    res_absent = select(valid_snapshot, cfg_absent, now=CONTROLLED_NOW)
    assert res_absent.state == "unconfigured"
    assert res_absent.reason == "home_not_configured"
    assert res_absent.aircraft is None

    # 2. Home out of range -> unconfigured / config_invalid
    cfg_oor, probs_oor = load_config(
        {"home": {"lat": 95.0, "lon": 114.1694}},
        environ={},
    )
    assert cfg_oor.home is None
    assert "home_lat_invalid" in probs_oor
    assert cfg_oor.problems == probs_oor
    res_oor = select(valid_snapshot, cfg_oor, now=CONTROLLED_NOW)
    assert res_oor.state == "unconfigured"
    assert res_oor.reason == "config_invalid"
    assert res_oor.aircraft is None

    # 3. Home as a string in structured config -> unconfigured / config_invalid (never coerced)
    cfg_str, probs_str = load_config(
        {"home": {"lat": "22.3193", "lon": 114.1694}},
        environ={},
    )
    assert cfg_str.home is None
    assert "home_lat_invalid" in probs_str
    res_str = select(valid_snapshot, cfg_str, now=CONTROLLED_NOW)
    assert res_str.state == "unconfigured"
    assert res_str.reason == "config_invalid"


def test_load_config_non_mapping_propagates_problem_to_config_and_select() -> None:
    """Catches load_config(None) returning empty config.problems so select() misreports home_not_configured instead of config_invalid (contract §8.4, amendment 13.2)."""
    valid_snapshot = make_snapshot(
        [
            {
                "hex": "780abc",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 0.2,
                "seen": 0.1,
            }
        ]
    )

    config, problems = load_config(None, environ={})  # type: ignore[arg-type]

    assert problems == ("config_not_mapping",)
    assert config.problems == ("config_not_mapping",)

    result = select(valid_snapshot, config, now=CONTROLLED_NOW)
    assert result.state == "unconfigured"
    assert result.reason == "config_invalid"
    assert result.aircraft is None


def test_load_config_valid_env_distance_overrides_invalid_mapping_without_retaining_problem() -> None:
    """Catches retaining max_distance_invalid from mapping when a higher-precedence valid PHLIGHT_MAX_DISTANCE_KM overrides it (contract §8.4, amendment 13.2)."""
    valid_snapshot = make_snapshot(
        [
            {
                "hex": "780abc",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 0.2,
                "seen": 0.1,
            }
        ]
    )

    config, problems = load_config(
        {
            "home": {"lat": "bad", "lon": 999.0},
            "selection": {"max_distance_km": "bad"},
        },
        environ={
            "PHLIGHT_HOME_LAT": "22.3193",
            "PHLIGHT_HOME_LON": "114.1694",
            "PHLIGHT_MAX_DISTANCE_KM": "15",
        },
    )

    assert problems == ()
    assert config.problems == ()
    assert config.home == HomeLocation(lat=22.3193, lon=114.1694)
    assert config.max_distance_km == pytest.approx(15.0, abs=1e-9)

    result = select(valid_snapshot, config, now=CONTROLLED_NOW)
    assert result.state == "ok"
    assert result.aircraft is not None
    assert result.aircraft.hex == "780abc"

    # When both mapping and environment are invalid, problem code is recorded once and default is used
    both_bad_cfg, both_bad_probs = load_config(
        {
            "home": {"lat": 22.3193, "lon": 114.1694},
            "selection": {"max_distance_km": "bad"},
        },
        environ={"PHLIGHT_MAX_DISTANCE_KM": "-5"},
    )
    assert both_bad_probs == ("max_distance_invalid",)
    assert both_bad_cfg.problems == ("max_distance_invalid",)
    assert both_bad_cfg.max_distance_km == pytest.approx(15.0, abs=1e-9)


def test_load_config_ignores_receiver_json_style_top_level_coordinates() -> None:
    """Catches inferring home location from receiver.json lat/lon keys outside [home] (contract §§4, 12)."""
    cfg, problems = load_config(
        {
            "lat": 22.3193,
            "lon": 114.1694,
            "receiver": {"lat": 22.3193, "lon": 114.1694},
        },
        environ={},
    )
    assert cfg.home is None
    assert problems == ()

    res = select(make_snapshot([]), cfg, now=CONTROLLED_NOW)
    assert res.state == "unconfigured"
    assert res.reason == "home_not_configured"


def test_load_config_environment_overrides_and_parsing() -> None:
    """Catches failure to parse numeric strings from environment variables or wrong precedence over config mapping (contract §§8.4, 13.2)."""
    mapping: dict[str, Any] = {
        "home": {"lat": 10.0, "lon": 20.0},
        "selection": {
            "max_distance_km": 15.0,
            "max_position_age_s": 8.0,
            "max_message_age_s": 25.0,
            "max_snapshot_age_s": 12.0,
            "ignore_ground": False,
        },
    }
    environ = {
        "PHLIGHT_HOME_LAT": " 22.3193 ",
        "PHLIGHT_HOME_LON": "114.1694",
        "PHLIGHT_MAX_DISTANCE_KM": "20.5",
    }

    config, problems = load_config(mapping, environ=environ)

    assert problems == ()
    assert config.problems == ()
    assert config.home == HomeLocation(lat=22.3193, lon=114.1694)
    assert config.max_distance_km == pytest.approx(20.5, abs=1e-9)
    assert config.max_position_age_s == pytest.approx(8.0, abs=1e-9)
    assert config.max_message_age_s == pytest.approx(25.0, abs=1e-9)
    assert config.max_snapshot_age_s == pytest.approx(12.0, abs=1e-9)
    assert config.ignore_ground is False


def test_load_config_invalid_selection_fields_and_env_values_propagate_to_select() -> None:
    """Catches losing selection block or environment validation errors before select() runs (amendment 13.2)."""
    valid_snapshot = make_snapshot([])

    # Invalid structured selection values with a valid home
    cfg_sel, probs_sel = load_config(
        {
            "home": {"lat": 22.3193, "lon": 114.1694},
            "selection": {
                "max_distance_km": "15.0",
                "max_position_age_s": -1.0,
                "max_message_age_s": True,
                "max_snapshot_age_s": "15",
                "ignore_ground": "true",
            },
        },
        environ={},
    )
    assert set(probs_sel) == {
        "max_distance_invalid",
        "max_position_age_invalid",
        "max_message_age_invalid",
        "max_snapshot_age_invalid",
        "ignore_ground_invalid",
    }
    res_sel = select(valid_snapshot, cfg_sel, now=CONTROLLED_NOW)
    assert res_sel.state == "unconfigured"
    assert res_sel.reason == "config_invalid"

    # Invalid environment variable value overrides valid mapping and flags problem
    cfg_env, probs_env = load_config(
        {"home": {"lat": 22.3193, "lon": 114.1694}},
        environ={"PHLIGHT_MAX_DISTANCE_KM": "0"},
    )
    assert probs_env == ("max_distance_invalid",)
    res_env = select(valid_snapshot, cfg_env, now=CONTROLLED_NOW)
    assert res_env.state == "unconfigured"
    assert res_env.reason == "config_invalid"

    # Independent lat/lon validation when env lat and mapping lon are both invalid
    cfg_home_mixed, probs_home_mixed = load_config(
        {"home": {"lat": 22.3193, "lon": "bad_lon"}},
        environ={"PHLIGHT_HOME_LAT": "bad_lat"},
    )
    assert cfg_home_mixed.home is None
    assert probs_home_mixed == ("home_lat_invalid", "home_lon_invalid")


def test_load_source_path_precedence_and_validation() -> None:
    """Catches auto-probing decoder paths or wrong env/mapping precedence in load_source_path() (contract §§2.1, 8.4, 13.2)."""
    # Default path is /run/readsb/aircraft.json
    path_default, probs_default = load_source_path({}, environ={})
    assert path_default == DEFAULT_SOURCE_PATH == "/run/readsb/aircraft.json"
    assert probs_default == ()

    # Config mapping overrides default
    path_cfg, probs_cfg = load_source_path(
        {"source": {"aircraft_json": "/run/dump1090-fa/aircraft.json"}},
        environ={},
    )
    assert path_cfg == "/run/dump1090-fa/aircraft.json"
    assert probs_cfg == ()

    # Environment variable overrides config mapping
    path_env, probs_env = load_source_path(
        {"source": {"aircraft_json": "/run/dump1090-fa/aircraft.json"}},
        environ={"PHLIGHT_AIRCRAFT_JSON": "/run/dump1090-mutability/aircraft.json"},
    )
    assert path_env == "/run/dump1090-mutability/aircraft.json"
    assert probs_env == ()

    # Blank or non-string source path reports source_path_invalid and falls back
    path_bad, probs_bad = load_source_path(
        {"source": {"aircraft_json": "   "}},
        environ={},
    )
    assert path_bad == DEFAULT_SOURCE_PATH
    assert probs_bad == ("source_path_invalid",)


def test_load_source_path_valid_env_overrides_invalid_mapping_without_retaining_problem() -> None:
    """Catches retaining source_path_invalid from mapping when a higher-precedence valid PHLIGHT_AIRCRAFT_JSON overrides it (contract §8.4, amendment 13.2)."""
    path_env_over_bad, probs_env_over_bad = load_source_path(
        {"source": {"aircraft_json": "   "}},
        environ={"PHLIGHT_AIRCRAFT_JSON": "/run/dump1090-mutability/aircraft.json"},
    )
    assert path_env_over_bad == "/run/dump1090-mutability/aircraft.json"
    assert probs_env_over_bad == ()

    # When both mapping and environment are invalid, source_path_invalid is recorded once
    path_both_bad, probs_both_bad = load_source_path(
        {"source": {"aircraft_json": "   "}},
        environ={"PHLIGHT_AIRCRAFT_JSON": ""},
    )
    assert path_both_bad == DEFAULT_SOURCE_PATH
    assert probs_both_bad == ("source_path_invalid",)


def test_result_state_precedence_order() -> None:
    """Catches wrong state precedence when multiple failure conditions hold simultaneously (contract §7)."""
    missing_snap = SourceSnapshot(
        state="missing_input",
        file_now=None,
        aircraft=(),
        error="file_not_found",
    )
    stale_empty_snap = make_snapshot([], file_now=CONTROLLED_NOW - 25.0)

    # 1. unconfigured (config_invalid) outranks missing_input
    bad_cfg, _ = load_config({"home": {"lat": "bad", "lon": 114.0}}, environ={})
    res1 = select(missing_snap, bad_cfg, now=CONTROLLED_NOW)
    assert res1.state == "unconfigured"
    assert res1.reason == "config_invalid"

    # 2. unconfigured (home_not_configured) outranks missing_input and stale_input
    unconfigured_cfg = SelectionConfig(home=None)
    res2 = select(missing_snap, unconfigured_cfg, now=CONTROLLED_NOW)
    assert res2.state == "unconfigured"
    assert res2.reason == "home_not_configured"

    res3 = select(stale_empty_snap, unconfigured_cfg, now=CONTROLLED_NOW)
    assert res3.state == "unconfigured"
    assert res3.reason == "home_not_configured"

    # 3. stale_input outranks empty_sky
    configured_cfg = SelectionConfig(home=HONG_KONG_HOME)
    res4 = select(stale_empty_snap, configured_cfg, now=CONTROLLED_NOW)
    assert res4.state == "stale_input"
    assert res4.reason == "feed_stalled"
