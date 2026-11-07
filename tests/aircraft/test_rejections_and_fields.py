"""Tests for per-aircraft rejection rules, ground traffic, optional field normalization, and empty_sky accounting (contract §§6, 7, 8.1, 10, 13.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from phlight.aircraft import (
    REJECTION_CODES,
    SelectionConfig,
    select,
    select_from_file,
)

from .conftest import CONTROLLED_NOW, HONG_KONG_HOME, make_snapshot


def test_rejection_codes_constant_matches_contract_order() -> None:
    """Catches reordering or renaming of the ten normative per-aircraft rejection codes (contract §6)."""
    assert tuple(REJECTION_CODES) == (
        "invalid_record",
        "invalid_hex",
        "duplicate_hex",
        "no_position",
        "invalid_position",
        "invalid_timestamp",
        "stale_message",
        "stale_position",
        "ground",
        "out_of_range",
    )


def test_overlapping_defects_use_first_matching_rejection_rule_without_double_counting(
    hk_config: SelectionConfig,
) -> None:
    """Catches wrong rejection evaluation order or double-counting a record with multiple defects (contract §6)."""
    snapshot = make_snapshot(
        [
            # 1. invalid_record (not a dict)
            "not-an-object",
            # 2. invalid_hex (also missing position, stale, ground, out of range)
            {
                "hex": "ZZZZZZ",
                "alt_baro": "ground",
                "seen_pos": 99.0,
                "seen": 99.0,
            },
            # Seed a valid hex 780003 that itself has no_position (4)
            {"hex": "780003"},
            # 3. duplicate_hex (also has invalid_position and stale timestamps)
            {
                "hex": "780003",
                "lat": 999.0,
                "lon": 999.0,
                "seen_pos": 99.0,
                "seen": 99.0,
            },
            # 4. no_position (lat absent, also has invalid timestamp and ground)
            {
                "hex": "780004",
                "lon": 114.1694,
                "seen_pos": "bad",
                "alt_baro": "ground",
            },
            # 5. invalid_position (lat out of range, also has invalid_timestamp and stale)
            {
                "hex": "780005",
                "lat": -91.0,
                "lon": 114.1694,
                "seen_pos": None,
                "seen": 99.0,
            },
            # 6. invalid_timestamp (seen_pos missing, also on ground and out of range)
            {
                "hex": "780006",
                "lat": 25.0,
                "lon": 114.1694,
                "seen": 99.0,
                "alt_baro": "ground",
            },
            # 7. stale_message (also stale_position, ground, out_of_range)
            {
                "hex": "780007",
                "lat": 25.0,
                "lon": 114.1694,
                "seen_pos": 50.0,
                "seen": 31.0,
                "alt_baro": "ground",
            },
            # 8. stale_position (fresh seen, also ground and out_of_range)
            {
                "hex": "780008",
                "lat": 25.0,
                "lon": 114.1694,
                "seen_pos": 11.0,
                "seen": 1.0,
                "alt_baro": "ground",
            },
            # 9. ground (fresh timestamps, also out_of_range)
            {
                "hex": "780009",
                "lat": 25.0,
                "lon": 114.1694,
                "seen_pos": 1.0,
                "seen": 0.5,
                "alt_baro": "ground",
            },
            # 10. out_of_range (airborne, fresh, > 15 km)
            {
                "hex": "780010",
                "lat": 25.0,
                "lon": 114.1694,
                "seen_pos": 1.0,
                "seen": 0.5,
                "alt_baro": 10000,
            },
        ]
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "empty_sky"
    assert result.aircraft is None
    assert result.reason is None
    assert result.considered_count == 11
    assert result.eligible_count == 0
    assert dict(result.rejected) == {
        "invalid_record": 1,
        "invalid_hex": 1,
        "duplicate_hex": 1,
        "no_position": 2,
        "invalid_position": 1,
        "invalid_timestamp": 1,
        "stale_message": 1,
        "stale_position": 1,
        "ground": 1,
        "out_of_range": 1,
    }
    assert sum(result.rejected.values()) + result.eligible_count == result.considered_count


@pytest.mark.parametrize(
    "bad_hex",
    [
        None,
        123456,
        True,
        "",
        "780ab",
        "780abcd",
        "780abg",
        "~~780abc",
        "780abc ",
    ],
)
def test_invalid_hex_variants_are_rejected(
    hk_config: SelectionConfig,
    bad_hex: object,
) -> None:
    """Catches lax hex regex or accepting non-string hex values (contract §§2.3, 6)."""
    entry = {
        "lat": 22.3193,
        "lon": 114.1694,
        "seen_pos": 0.2,
        "seen": 0.1,
    }
    if bad_hex is not None:
        entry["hex"] = bad_hex

    result = select(make_snapshot([entry]), hk_config, now=CONTROLLED_NOW)

    assert result.state == "empty_sky"
    assert dict(result.rejected) == {"invalid_hex": 1}


@pytest.mark.parametrize(
    "position_fields",
    [
        {},
        {"lat": 22.3193},
        {"lon": 114.1694},
        {"lastPosition": {"lat": 22.3193, "lon": 114.1694, "seen_pos": 0.2}},
        {"rr_lat": 22.3193, "rr_lon": 114.1694},
    ],
)
def test_missing_lat_or_lon_counted_as_no_position(
    hk_config: SelectionConfig,
    position_fields: dict[str, object],
) -> None:
    """Catches rendering positionless Mode-S reports as overhead or falling back to rr_lat/lastPosition (contract §§2.2, 6, 10.4)."""
    entry: dict[str, object] = {
        "hex": "780104",
        "seen_pos": 0.2,
        "seen": 0.1,
        **position_fields,
    }

    result = select(make_snapshot([entry]), hk_config, now=CONTROLLED_NOW)

    assert result.state == "empty_sky"
    assert result.aircraft is None
    assert dict(result.rejected) == {"no_position": 1}


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (None, 114.1694),
        (22.3193, None),
        ("22.3193", 114.1694),
        (22.3193, "114.1694"),
        (True, 114.1694),
        (22.3193, False),
        (90.0001, 114.1694),
        (-90.0001, 114.1694),
        (22.3193, 180.0001),
        (22.3193, -180.0001),
        (float("nan"), 114.1694),
        (22.3193, float("inf")),
    ],
)
def test_invalid_position_values_are_rejected(
    hk_config: SelectionConfig,
    lat: object,
    lon: object,
) -> None:
    """Catches accepting booleans, strings, NaN/Inf, or out-of-range coordinates as valid positions (contract §6)."""
    snapshot = make_snapshot(
        [
            {
                "hex": "780bad",
                "lat": lat,
                "lon": lon,
                "seen_pos": 0.2,
                "seen": 0.1,
            }
        ]
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "empty_sky"
    assert dict(result.rejected) == {"invalid_position": 1}


@pytest.mark.parametrize(
    ("seen_pos", "seen", "include_seen_pos"),
    [
        (0.0, 0.1, False),
        (None, 0.1, True),
        ("0.5", 0.1, True),
        (True, 0.1, True),
        (float("nan"), 0.1, True),
        (float("inf"), 0.1, True),
        (0.5, "0.1", True),
        (0.5, False, True),
        (0.5, float("nan"), True),
        (0.5, float("-inf"), True),
    ],
)
def test_invalid_timestamp_values_are_rejected(
    hk_config: SelectionConfig,
    seen_pos: object,
    seen: object,
    include_seen_pos: bool,
) -> None:
    """Catches accepting missing seen_pos or boolean/string/non-finite seen or seen_pos (contract §6)."""
    entry: dict[str, object] = {
        "hex": "780106",
        "lat": 22.3193,
        "lon": 114.1694,
        "seen": seen,
    }
    if include_seen_pos:
        entry["seen_pos"] = seen_pos

    result = select(make_snapshot([entry]), hk_config, now=CONTROLLED_NOW)

    assert result.state == "empty_sky"
    assert dict(result.rejected) == {"invalid_timestamp": 1}


@pytest.mark.parametrize(
    ("alt_baro", "gs", "expect_ground"),
    [
        ("ground", None, True),
        ("ground", 140.0, True),
        (0, 5.0, True),
        (0, 30.0, True),
        (-50, 0.0, True),
        (0, 30.1, False),
        (0, None, False),
        (0, "5.0", False),
        (0, True, False),
        (25, 5.0, False),
        (None, 5.0, False),
    ],
)
def test_ground_detection_and_ignore_ground_toggle(
    alt_baro: object,
    gs: object,
    expect_ground: bool,
) -> None:
    """Catches misclassifying surface vehicles or low-altitude slow aircraft under both ignore_ground settings (contract §§6, 10.7, 13.5)."""
    entry: dict[str, object] = {
        "hex": "780109",
        "lat": 22.3193,
        "lon": 114.1694,
        "seen_pos": 0.3,
        "seen": 0.1,
    }
    if alt_baro is not None:
        entry["alt_baro"] = alt_baro
    if gs is not None:
        entry["gs"] = gs

    snapshot = make_snapshot([entry])

    ignored = select(
        snapshot,
        SelectionConfig(home=HONG_KONG_HOME, ignore_ground=True),
        now=CONTROLLED_NOW,
    )
    if expect_ground:
        assert ignored.state == "empty_sky"
        assert dict(ignored.rejected) == {"ground": 1}
    else:
        assert ignored.state == "ok"
        assert ignored.aircraft is not None
        assert ignored.aircraft.on_ground is False

    allowed = select(
        snapshot,
        SelectionConfig(home=HONG_KONG_HOME, ignore_ground=False),
        now=CONTROLLED_NOW,
    )
    assert allowed.state == "ok"
    assert allowed.aircraft is not None
    assert allowed.aircraft.on_ground is expect_ground
    if alt_baro == "ground" or alt_baro is None:
        assert allowed.aircraft.altitude_ft is None
    elif isinstance(alt_baro, (int, float)):
        assert allowed.aircraft.altitude_ft == int(alt_baro)


def test_malformed_optional_fields_degrade_to_none_without_rejecting_aircraft(
    hk_config: SelectionConfig,
) -> None:
    """Catches crashes or false rejections when optional artwork/annotation fields are malformed (amendment 13.5)."""
    snapshot = make_snapshot(
        [
            {
                "hex": "780110",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 0.4,
                "seen": 0.2,
                "flight": 12345,
                "alt_baro": "cruising",
                "track": "north",
                "gs": True,
                "category": "",
                "type": ["adsb_icao"],
            }
        ]
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.aircraft is not None
    assert result.aircraft.hex == "780110"
    assert result.aircraft.callsign is None
    assert result.aircraft.altitude_ft is None
    assert result.aircraft.on_ground is False
    assert result.aircraft.track_deg is None
    assert result.aircraft.ground_speed_kt is None
    assert result.aircraft.category is None
    assert result.aircraft.source_type is None


def test_callsign_normalization_and_half_up_altitude_rounding(
    hk_config: SelectionConfig,
) -> None:
    """Catches failure to strip trailing spaces, convert blank callsigns to None, preserve Unicode, or round alt_baro half-up (contract §§8.1, 13.5)."""
    blank_res = select(
        make_snapshot(
            [
                {
                    "hex": "780111",
                    "flight": "        ",
                    "alt_baro": 3500.5,
                    "lat": 22.3193,
                    "lon": 114.1694,
                    "seen_pos": 0.2,
                    "seen": 0.1,
                }
            ]
        ),
        hk_config,
        now=CONTROLLED_NOW,
    )
    assert blank_res.state == "ok"
    assert blank_res.aircraft is not None
    assert blank_res.aircraft.callsign is None
    # Half-up: floor(3500.5 + 0.5) == 3501 (whereas Python's banker's round(3500.5) == 3500)
    assert blank_res.aircraft.altitude_ft == 3501

    unicode_res = select(
        make_snapshot(
            [
                {
                    "hex": "780112",
                    "flight": "國泰101  ",
                    "alt_baro": 3500.4,
                    "lat": 22.3193,
                    "lon": 114.1694,
                    "seen_pos": 0.2,
                    "seen": 0.1,
                }
            ]
        ),
        hk_config,
        now=CONTROLLED_NOW,
    )
    assert unicode_res.state == "ok"
    assert unicode_res.aircraft is not None
    assert unicode_res.aircraft.callsign == "國泰101"
    assert unicode_res.aircraft.altitude_ft == 3500


def test_empty_aircraft_array_fixture_yields_empty_sky_with_clean_counts(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches treating an empty aircraft array as invalid_input or populating zero-count rejection keys (contract §§7, 10.12)."""
    result = select_from_file(
        fixtures_dir / "synthetic_empty_sky.json",
        hk_config,
        now=CONTROLLED_NOW,
    )

    assert result.state == "empty_sky"
    assert result.aircraft is None
    assert result.reason is None
    assert result.snapshot_time == pytest.approx(CONTROLLED_NOW, abs=1e-6)
    assert result.evaluated_at == pytest.approx(CONTROLLED_NOW, abs=1e-6)
    assert result.snapshot_age_s == pytest.approx(0.0, abs=1e-9)
    assert result.considered_count == 0
    assert result.eligible_count == 0
    assert dict(result.rejected) == {}
