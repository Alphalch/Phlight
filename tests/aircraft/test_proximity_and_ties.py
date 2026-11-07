"""Tests for haversine distance, 15 km gate, and deterministic tie-breaking (contract §§5, 6, 9, 10, 13.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from phlight.aircraft import (
    HomeLocation,
    SelectionConfig,
    distance_m,
    read_snapshot,
    select,
)

from .conftest import CONTROLLED_NOW, HONG_KONG_HOME, make_snapshot


def test_distance_m_identical_coordinates_returns_exact_zero() -> None:
    """Catches floating-point NaN or non-zero residual when aircraft is directly at home coordinates."""
    d = distance_m(22.3193, 114.1694, 22.3193, 114.1694)
    assert d == 0.0


def test_distance_m_matches_spherical_haversine_reference_values() -> None:
    """Catches wrong Earth radius or degree/radian conversion errors in distance_m()."""
    # 0.018 deg north of 22.3193 -> 2001.5114 m on R=6_371_008.8 m
    assert distance_m(22.3193, 114.1694, 22.3373, 114.1694) == pytest.approx(
        2001.5114, abs=0.5
    )
    # 0.045 deg north -> 5003.7786 m
    assert distance_m(22.3193, 114.1694, 22.3643, 114.1694) == pytest.approx(
        5003.7786, abs=0.5
    )
    # Antipodal points (0, 0) and (0, 180) -> pi * R = 20_015_114.44 m without ValueError from sqrt(a) > 1
    assert distance_m(0.0, 0.0, 0.0, 180.0) == pytest.approx(
        20015114.44, abs=0.5
    )


def test_distance_gate_boundary_just_inside_and_just_outside_15km(
    hk_config: SelectionConfig,
) -> None:
    """Catches off-by-one or wrong unit conversion at the 15 km (15 000 m) proximity gate."""
    # lat=22.454193 -> 14999.4380 m (inside 15 km)
    # lat=22.454300 -> 15011.3358 m (outside 15 km)
    snapshot = make_snapshot(
        [
            {
                "hex": "780d01",
                "lat": 22.454300,
                "lon": 114.1694,
                "seen_pos": 0.2,
                "seen": 0.1,
            },
            {
                "hex": "780d02",
                "lat": 22.454193,
                "lon": 114.1694,
                "seen_pos": 0.5,
                "seen": 0.2,
            },
        ]
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.considered_count == 2
    assert result.eligible_count == 1
    assert dict(result.rejected) == {"out_of_range": 1}
    assert result.aircraft is not None
    assert result.aircraft.hex == "780d02"
    assert result.aircraft.distance_m == pytest.approx(14999.44, abs=0.5)


def test_distance_gate_uses_raw_metres_at_15000m_rounded_bucket(
    hk_config: SelectionConfig,
) -> None:
    """Catches gating on rounded distance_key_m instead of raw distance_m <= max_distance_km * 1000 (contract §§5.2, 6)."""
    # Both points round to distance_key_m == 15000:
    # - lat=22.454194 -> d = 14999.5492 m (<= 15000.0 m, must be accepted)
    # - lat=22.454199 -> d = 15000.1052 m (> 15000.0 m, must be rejected as out_of_range)
    inside_res = select(
        make_snapshot(
            [
                {
                    "hex": "780e01",
                    "lat": 22.454194,
                    "lon": 114.1694,
                    "seen_pos": 1.0,
                    "seen": 0.5,
                }
            ]
        ),
        hk_config,
        now=CONTROLLED_NOW,
    )
    assert inside_res.state == "ok"
    assert inside_res.aircraft is not None
    assert inside_res.aircraft.hex == "780e01"
    assert inside_res.aircraft.distance_m == pytest.approx(14999.55, abs=0.5)

    outside_res = select(
        make_snapshot(
            [
                {
                    "hex": "780e02",
                    "lat": 22.454199,
                    "lon": 114.1694,
                    "seen_pos": 1.0,
                    "seen": 0.5,
                }
            ]
        ),
        hk_config,
        now=CONTROLLED_NOW,
    )
    assert outside_res.state == "empty_sky"
    assert outside_res.aircraft is None
    assert dict(outside_res.rejected) == {"out_of_range": 1}


def test_tie_break_same_distance_key_m_prefers_fresher_position_over_raw_submetre_distance(
    hk_config: SelectionConfig,
) -> None:
    """Catches sorting by raw float distance_m instead of rounded distance_key_m = floor(distance_m + 0.5)."""
    # lat=22.337300 -> d = 2001.5114 m -> floor(d + 0.5) = 2002 m (seen_pos = 2.0 s)
    # lat=22.337303 -> d = 2001.8450 m -> floor(d + 0.5) = 2002 m (seen_pos = 1.0 s)
    # Although 780f01 is 0.33 m closer in raw float metres, both have distance_key_m == 2002,
    # so 780f02 MUST win on fresher position_age_s (1.0 < 2.0).
    snapshot = make_snapshot(
        [
            {
                "hex": "780f01",
                "lat": 22.337300,
                "lon": 114.1694,
                "seen_pos": 2.0,
                "seen": 0.1,
            },
            {
                "hex": "780f02",
                "lat": 22.337303,
                "lon": 114.1694,
                "seen_pos": 1.0,
                "seen": 0.9,
            },
        ]
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.eligible_count == 2
    assert result.aircraft is not None
    assert result.aircraft.hex == "780f02"


def test_tie_break_same_distance_key_m_and_position_age_prefers_lower_lowercase_hex(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches missing hex tie-breaker or case-sensitive hex sorting."""
    # synthetic_tie_distance_bucket.json has 3 aircraft all in distance_key_m == 2002:
    # - 780ccc: seen_pos=2.5 (loses on position_age_s)
    # - 780bbb: lat=22.337303 (d=2001.8450 m), seen_pos=1.0
    # - 780aaa: lat=22.337304 (d=2001.9562 m), seen_pos=1.0
    # Between 780bbb and 780aaa, both have distance_key_m=2002 and position_age_s=1.0,
    # so 780aaa wins on lexicographic hex despite being 0.11 m further in raw distance.
    snapshot = read_snapshot(fixtures_dir / "synthetic_tie_distance_bucket.json")

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.eligible_count == 3
    assert result.aircraft is not None
    assert result.aircraft.hex == "780aaa"
    assert result.aircraft.callsign == "TIE1"


def test_array_order_reversed_produces_identical_winner_for_unique_hexes(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches array-order dependence when candidates have unique hex codes (contract §§5.2, 9, 10.3)."""
    for fixture_name in (
        "synthetic_readsb_multi.json",
        "synthetic_tie_distance_bucket.json",
        "synthetic_dump1090_fa_retained.json",
    ):
        forward_snapshot = read_snapshot(fixtures_dir / fixture_name)
        reversed_snapshot = make_snapshot(
            list(reversed(forward_snapshot.aircraft)),
            file_now=forward_snapshot.file_now,
        )

        forward_result = select(forward_snapshot, hk_config, now=CONTROLLED_NOW)
        reversed_result = select(reversed_snapshot, hk_config, now=CONTROLLED_NOW)

        assert forward_result.state == "ok"
        assert reversed_result.state == "ok"
        assert forward_result.aircraft is not None
        assert reversed_result.aircraft is not None
        assert reversed_result.aircraft.hex == forward_result.aircraft.hex
        assert reversed_result.aircraft == forward_result.aircraft
        assert dict(reversed_result.rejected) == dict(forward_result.rejected)


def test_duplicate_hex_keeps_first_record_and_counts_subsequent_as_duplicate(
    hk_config: SelectionConfig,
) -> None:
    """Catches last-wins overwrite on duplicate hex or failure to count duplicate_hex (contract §6, amendment 13.1)."""
    # First record for 780d00 is at 5 km; second record for 780D00 (uppercase) is at 0 m.
    # Third aircraft 780d99 is at 2 km.
    # Because first 780d00 (5 km) is kept and second 780D00 (0 m) is rejected as duplicate_hex,
    # 780d99 (2 km) wins! Reversing the two 780d00 records makes 780d00 (0 m) win.
    entry_far = {
        "hex": "780d00",
        "flight": "DUPFAR  ",
        "lat": 22.3643,
        "lon": 114.1694,
        "seen_pos": 0.5,
        "seen": 0.2,
    }
    entry_near = {
        "hex": "780D00",
        "flight": "DUPNEAR ",
        "lat": 22.3193,
        "lon": 114.1694,
        "seen_pos": 0.5,
        "seen": 0.2,
    }
    entry_other = {
        "hex": "780d99",
        "flight": "OTHER   ",
        "lat": 22.3373,
        "lon": 114.1694,
        "seen_pos": 0.5,
        "seen": 0.2,
    }

    res_far_first = select(
        make_snapshot([entry_far, entry_near, entry_other]),
        hk_config,
        now=CONTROLLED_NOW,
    )
    assert res_far_first.state == "ok"
    assert res_far_first.considered_count == 3
    assert res_far_first.eligible_count == 2
    assert dict(res_far_first.rejected) == {"duplicate_hex": 1}
    assert res_far_first.aircraft is not None
    assert res_far_first.aircraft.hex == "780d99"

    res_near_first = select(
        make_snapshot([entry_near, entry_far, entry_other]),
        hk_config,
        now=CONTROLLED_NOW,
    )
    assert res_near_first.state == "ok"
    assert res_near_first.considered_count == 3
    assert res_near_first.eligible_count == 2
    assert dict(res_near_first.rejected) == {"duplicate_hex": 1}
    assert res_near_first.aircraft is not None
    assert res_near_first.aircraft.hex == "780d00"
    assert res_near_first.aircraft.callsign == "DUPNEAR"


def test_duplicate_hex_consumes_hex_even_when_first_record_is_rejected_later(
    hk_config: SelectionConfig,
) -> None:
    """Catches only marking a hex as seen after it passes position/freshness checks (amendment 13.1)."""
    snapshot = make_snapshot(
        [
            # First record has valid hex but no position -> rejected as no_position
            {"hex": "780abc", "seen": 0.2},
            # Second record has valid position right overhead -> must still be rejected as duplicate_hex
            {
                "hex": "780abc",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 0.2,
                "seen": 0.1,
            },
        ]
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "empty_sky"
    assert result.aircraft is None
    assert result.considered_count == 2
    assert result.eligible_count == 0
    assert dict(result.rejected) == {
        "no_position": 1,
        "duplicate_hex": 1,
    }
