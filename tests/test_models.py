"""Tests for the local aircraft data model (phlight.render.models).

The renderer consumes snapshots produced by the (future) ADS-B ingest stage, so
these tests pin the tolerant-loading contract: bad entries are dropped, bad
optional fields degrade to None, and nothing raises except unusable files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from phlight.render import AircraftSnapshot, SnapshotError, load_snapshot

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def fixture(name: str) -> Path:
    return FIXTURES / name


def test_loads_every_aircraft_from_recorded_fixture() -> None:
    snapshot = load_snapshot(fixture("overhead_snapshot.json"))

    assert len(snapshot.aircraft) == 5
    assert snapshot.captured_at == 1762500000
    assert snapshot.dropped == ()


def test_keeps_optional_fields_that_are_absent() -> None:
    snapshot = load_snapshot(fixture("overhead_snapshot.json"))
    ga = next(a for a in snapshot.aircraft if a.hex == "7c1a2b")

    assert ga.operator is None
    assert ga.registration == "VH-ABC"
    assert ga.callsign == "VHABC"
    assert ga.altitude_ft == 3200


def test_drops_entries_without_a_usable_icao_hex() -> None:
    snapshot = load_snapshot(fixture("malformed_snapshot.json"))

    assert len(snapshot.aircraft) == 3
    assert len(snapshot.dropped) == 2
    assert all("hex" in reason for reason in snapshot.dropped)


def test_normalises_hex_case() -> None:
    snapshot = load_snapshot(fixture("malformed_snapshot.json"))

    assert snapshot.aircraft[-1].hex == "abc126"


def test_unparseable_number_degrades_to_none_and_is_reported() -> None:
    snapshot = load_snapshot(fixture("malformed_snapshot.json"))
    bad_alt = next(a for a in snapshot.aircraft if a.hex == "abc123")
    bad_dist = next(a for a in snapshot.aircraft if a.hex == "abc124")

    assert bad_alt.altitude_ft is None
    assert bad_dist.distance_km is None
    assert any("altitude_ft" in issue for issue in snapshot.issues)
    assert any("distance_km" in issue for issue in snapshot.issues)


def test_empty_aircraft_list_is_a_valid_snapshot() -> None:
    snapshot = load_snapshot(fixture("empty_sky_snapshot.json"))

    assert snapshot.aircraft == ()
    assert snapshot.is_empty is True
    assert snapshot.captured_at == 1762500600


def test_snapshot_without_aircraft_key_is_empty() -> None:
    snapshot = AircraftSnapshot.from_dict({"captured_at": 1.0})

    assert snapshot.is_empty is True


def test_missing_file_raises_snapshot_error(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError):
        load_snapshot(tmp_path / "nope.json")


def test_invalid_json_raises_snapshot_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")

    with pytest.raises(SnapshotError):
        load_snapshot(bad)


def test_non_object_document_raises_snapshot_error(tmp_path: Path) -> None:
    bad = tmp_path / "list.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(SnapshotError):
        load_snapshot(bad)


def test_label_prefers_callsign_then_registration_then_hex() -> None:
    snapshot = load_snapshot(fixture("overhead_snapshot.json"))
    by_hex = {a.hex: a for a in snapshot.aircraft}

    assert by_hex["780a1b"].label == "CPA715"
    assert by_hex["7c1a2b"].type_label == "Cessna 172"

    from phlight.render import Aircraft

    assert Aircraft(hex="abcdef", registration="B-1234").label == "B-1234"
    assert Aircraft(hex="abcdef").label == "ABCDEF"


def test_distance_sorted_view_puts_unknown_distances_last() -> None:
    snapshot = load_snapshot(fixture("overhead_snapshot.json"))
    ordered = [a.hex for a in snapshot.by_distance()]

    assert ordered[0] == "780912"
    assert ordered[-1] == "8990a1"