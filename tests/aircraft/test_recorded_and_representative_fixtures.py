"""Tests against recorded and representative readsb/dump1090 fixtures (contract §§2, 6, 10, 13)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from phlight.aircraft import (
    HomeLocation,
    SelectionConfig,
    read_snapshot,
    select,
    select_from_file,
)

from .conftest import (
    CONTROLLED_NOW,
    HONG_KONG_HOME,
    PERPIGNAN_HOME,
    RECORDED_NOW,
)


def _git_blob_sha1(path: Path) -> str:
    raw = path.read_bytes().replace(b"\r\n", b"\n")
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def test_recorded_readsb_fixture_has_verified_upstream_provenance(
    fixtures_dir: Path,
) -> None:
    """Catches accidental tampering with the committed recorded decoder fixture."""
    fixture_path = fixtures_dir / "recorded_readsb_perpignan_2022.json"
    provenance_path = fixtures_dir / "PROVENANCE.md"

    assert fixture_path.is_file()
    assert provenance_path.is_file()
    assert _git_blob_sha1(fixture_path) == "51e1c0366016b9940e936dd2e62a124b5f2f3b8d"

    snapshot = read_snapshot(fixture_path)
    assert snapshot.state == "ok"
    assert snapshot.error is None
    assert snapshot.file_now == pytest.approx(RECORDED_NOW, abs=1e-6)
    assert len(snapshot.aircraft) == 19


def test_recorded_readsb_fixture_selects_nearest_fresh_aircraft_and_accounts_rejections(
    fixtures_dir: Path,
    perpignan_config: SelectionConfig,
) -> None:
    """Catches regressions in end-to-end selection, callsign stripping, lastPosition handling, or rejection counts on real recorded readsb data."""
    fixture_path = fixtures_dir / "recorded_readsb_perpignan_2022.json"

    result = select_from_file(fixture_path, perpignan_config, now=RECORDED_NOW)

    assert result.state == "ok"
    assert result.reason is None
    assert result.snapshot_time == pytest.approx(RECORDED_NOW, abs=1e-6)
    assert result.evaluated_at == pytest.approx(RECORDED_NOW, abs=1e-6)
    assert result.snapshot_age_s == pytest.approx(0.0, abs=1e-9)
    assert result.considered_count == 19
    assert result.eligible_count == 1
    assert dict(result.rejected) == {
        "no_position": 5,
        "stale_message": 3,
        "stale_position": 5,
        "out_of_range": 5,
    }
    assert sum(result.rejected.values()) + result.eligible_count == result.considered_count

    winner = result.aircraft
    assert winner is not None
    assert winner.hex == "406900"
    assert winner.callsign == "EXS37G"
    assert winner.lat == pytest.approx(42.545288, abs=1e-6)
    assert winner.lon == pytest.approx(2.520925, abs=1e-6)
    assert winner.distance_m == pytest.approx(592.86, abs=0.5)
    assert winner.distance_nm == pytest.approx(592.8628 / 1852.0, abs=1e-4)
    assert winner.position_age_s == pytest.approx(0.234, abs=1e-6)
    assert winner.message_age_s == pytest.approx(0.2, abs=1e-6)
    assert winner.altitude_ft == 37000
    assert winner.on_ground is False
    assert winner.track_deg == pytest.approx(185.83, abs=1e-4)
    assert winner.ground_speed_kt == pytest.approx(413.1, abs=1e-4)
    assert winner.category == "A3"
    assert winner.source_type == "adsb_icao"


def test_recorded_readsb_fixture_does_not_resurrect_last_position(
    fixtures_dir: Path,
) -> None:
    """Catches bug where readsb's aged-out lastPosition sub-object is used as a valid aircraft position."""
    fixture_path = fixtures_dir / "recorded_readsb_perpignan_2022.json"
    # Entry 4ca564 has no top-level lat/lon but carries lastPosition at (41.930054, 3.178607).
    # Place home directly at that lastPosition coordinate to prove it is never selected.
    config = SelectionConfig(
        home=HomeLocation(lat=41.930054, lon=3.178607),
        max_distance_km=5.0,
        max_message_age_s=60.0,
        max_position_age_s=120.0,
    )

    result = select_from_file(fixture_path, config, now=RECORDED_NOW)

    assert result.state == "empty_sky"
    assert result.aircraft is None
    assert result.rejected.get("no_position") == 5


def test_recorded_readsb_fixture_shifts_winner_when_home_moves(
    fixtures_dir: Path,
) -> None:
    """Catches hardcoded home coordinates or wrong distance ranking across multiple eligible recorded tracks."""
    fixture_path = fixtures_dir / "recorded_readsb_perpignan_2022.json"
    # Between 4076ed (43.185627, 2.567269 -> ~13.34 km) and 0a0022 (43.149036, 2.890974 -> ~13.28 km)
    carcassonne_config = SelectionConfig(home=HomeLocation(lat=43.17, lon=2.73))

    result = select_from_file(fixture_path, carcassonne_config, now=RECORDED_NOW)

    assert result.state == "ok"
    assert result.eligible_count == 2
    assert result.rejected.get("out_of_range") == 4
    assert result.aircraft is not None
    assert result.aircraft.hex == "0a0022"
    assert result.aircraft.callsign == "DAH1215"
    assert result.aircraft.distance_m == pytest.approx(13263.30, abs=0.5)


def test_synthetic_readsb_multi_selects_nearest_and_counts_all_rejections(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches wrong proximity selection or missing rejection categories on representative multi-aircraft readsb JSON."""
    fixture_path = fixtures_dir / "synthetic_readsb_multi.json"

    result = select_from_file(fixture_path, hk_config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.reason is None
    assert result.considered_count == 8
    assert result.eligible_count == 3
    assert dict(result.rejected) == {
        "no_position": 1,
        "stale_message": 1,
        "stale_position": 1,
        "ground": 1,
        "out_of_range": 1,
    }
    assert sum(result.rejected.values()) + result.eligible_count == result.considered_count

    assert result.aircraft is not None
    assert result.aircraft.hex == "780a02"
    assert result.aircraft.callsign == "HDA202"
    assert result.aircraft.distance_m == pytest.approx(2001.51, abs=0.5)
    assert result.aircraft.altitude_ft == 6400
    assert result.aircraft.category == "A3"
    assert result.aircraft.source_type == "adsb_icao"


def test_synthetic_readsb_multi_allows_non_icao_tisb_when_nearest(
    fixtures_dir: Path,
) -> None:
    """Catches unauthorized filtering of ~ non-ICAO or tisb_other source types (contract §§2.3, 6)."""
    fixture_path = fixtures_dir / "synthetic_readsb_multi.json"
    # Move home directly under ~0e9999 at (22.4273, 114.1694)
    config = SelectionConfig(home=HomeLocation(lat=22.4273, lon=114.1694))

    result = select_from_file(fixture_path, config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.aircraft is not None
    assert result.aircraft.hex == "~0e9999"
    assert result.aircraft.callsign == "TISB01"
    assert result.aircraft.source_type == "tisb_other"
    assert result.aircraft.distance_m == pytest.approx(0.0, abs=0.5)


def test_synthetic_dump1090_fa_retained_tracks_rejects_five_minute_stale_entries(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches trusting dump1090-fa array membership instead of checking seen, seen_pos, and zero-altitude ground speed."""
    fixture_path = fixtures_dir / "synthetic_dump1090_fa_retained.json"

    result = select_from_file(fixture_path, hk_config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.considered_count == 4
    assert result.eligible_count == 1
    assert dict(result.rejected) == {
        "stale_message": 1,
        "stale_position": 1,
        "ground": 1,
    }
    assert result.aircraft is not None
    assert result.aircraft.hex == "780dfa"
    assert result.aircraft.callsign == "BAW31"
    assert result.aircraft.distance_m == pytest.approx(5003.78, abs=0.5)
    assert result.aircraft.position_age_s == pytest.approx(1.5, abs=1e-6)
    assert result.aircraft.message_age_s == pytest.approx(0.5, abs=1e-6)


def test_select_from_file_matches_select_on_read_snapshot(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches divergence between select_from_file() and select(read_snapshot(path), ...)."""
    fixture_path = fixtures_dir / "synthetic_readsb_multi.json"

    snapshot = read_snapshot(fixture_path)
    from_snapshot = select(snapshot, hk_config, now=CONTROLLED_NOW)
    from_file = select_from_file(fixture_path, hk_config, now=CONTROLLED_NOW)

    assert from_file == from_snapshot
