"""Tests for the local aircraft data model (phlight.render.models).

The renderer consumes snapshots produced by the local ADS-B ingest/selection
stage, so these tests pin the tolerant-loading contract: bad entries are
dropped, bad optional fields (including non-finite numbers and booleans)
degrade to None, valid non-ICAO ``~abcdef`` hex addresses are preserved, and
nothing raises except unusable files.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from phlight.render import Aircraft, AircraftSnapshot, SnapshotError, load_snapshot

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

    assert Aircraft(hex="abcdef", registration="B-1234").label == "B-1234"
    assert Aircraft(hex="abcdef").label == "ABCDEF"


def test_distance_sorted_view_puts_unknown_distances_last() -> None:
    snapshot = load_snapshot(fixture("overhead_snapshot.json"))
    ordered = [a.hex for a in snapshot.by_distance()]

    assert ordered[0] == "780912"
    assert ordered[-1] == "8990a1"


def test_loads_representative_classes_fixture_and_breaks_distance_ties_by_hex() -> None:
    snapshot = load_snapshot(fixture("representative_classes_snapshot.json"))

    assert len(snapshot.aircraft) == 7
    assert snapshot.dropped == ()
    assert snapshot.issues == ()

    ordered = [a.hex for a in snapshot.by_distance()]
    # 780a1b (2.5 km) and 780b20 (2.5 km) tie on distance; hex order breaks the tie.
    # 7f0099 has distance_km=None and sorts last.
    assert ordered == [
        "780912",
        "780a1b",
        "780b20",
        "780c30",
        "7c1a2b",
        "7c9b1f",
        "7f0099",
    ]


def test_representative_fixture_identity_and_type_label_fallbacks() -> None:
    snapshot = load_snapshot(fixture("representative_classes_snapshot.json"))
    by_hex = {a.hex: a for a in snapshot.aircraft}

    # No callsign -> falls back to registration; no type_name -> falls back to type_code
    assert by_hex["780b20"].label == "B-3101"
    assert by_hex["780b20"].type_label == "E190"

    # No callsign or registration -> falls back to uppercase hex
    assert by_hex["7f0099"].label == "7F0099"
    assert by_hex["7f0099"].type_label == "ZZZZ"

    # No type_name or type_code -> falls back to "Unknown type"
    assert Aircraft(hex="7f0099").type_label == "Unknown type"


def test_boolean_and_whitespace_fields_degrade_to_none() -> None:
    snapshot = AircraftSnapshot.from_dict(
        {
            "captured_at": True,
            "source": "   ",
            "home": ["not-a-mapping"],
            "aircraft": [
                {
                    "hex": "abc104",
                    "callsign": "   ",
                    "registration": 12345,
                    "type_code": "  ",
                    "type_name": False,
                    "operator": "",
                    "altitude_ft": True,
                    "distance_km": False,
                    "bearing_deg": True,
                    "track_deg": False,
                    "ground_speed_kt": True,
                    "seen_at": False,
                }
            ],
        }
    )

    assert snapshot.captured_at is None
    assert snapshot.source is None
    assert snapshot.home is None
    assert len(snapshot.aircraft) == 1
    aircraft = snapshot.aircraft[0]
    assert aircraft.callsign is None
    assert aircraft.registration is None
    assert aircraft.type_code is None
    assert aircraft.type_name is None
    assert aircraft.operator is None
    assert aircraft.altitude_ft is None
    assert aircraft.distance_km is None
    assert aircraft.bearing_deg is None
    assert aircraft.track_deg is None
    assert aircraft.ground_speed_kt is None
    assert aircraft.seen_at is None
    assert any("captured_at" in issue for issue in snapshot.issues)
    assert any("altitude_ft" in issue for issue in snapshot.issues)
    assert any("distance_km" in issue for issue in snapshot.issues)


def test_non_object_entries_and_non_list_aircraft_field_are_handled() -> None:
    non_list = AircraftSnapshot.from_dict({"captured_at": 1762500000, "aircraft": "invalid"})
    assert non_list.is_empty is True
    assert any("aircraft is not a list" in issue for issue in non_list.issues)

    null_list = AircraftSnapshot.from_dict({"captured_at": 1762500000, "aircraft": None})
    assert null_list.is_empty is True
    assert null_list.issues == ()

    mixed = AircraftSnapshot.from_dict(
        {
            "captured_at": 1762500000,
            "aircraft": [None, "bad", 42, ["list"], {"hex": "780912"}],
        }
    )
    assert [a.hex for a in mixed.aircraft] == ["780912"]
    assert len(mixed.dropped) == 4
    assert all("not a JSON object" in reason for reason in mixed.dropped)


def test_non_mapping_document_passed_to_from_dict_raises_snapshot_error() -> None:
    with pytest.raises(SnapshotError, match="JSON object"):
        AircraftSnapshot.from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_altitude",
    ["nan", "NaN", "inf", "-inf", "Infinity", float("nan"), float("inf"), float("-inf")],
)
def test_non_finite_altitude_degrades_to_none_without_raising(bad_altitude: object) -> None:
    snapshot = AircraftSnapshot.from_dict(
        {
            "captured_at": 1762500000,
            "aircraft": [{"hex": "abc101", "callsign": "NANALT", "altitude_ft": bad_altitude}],
        }
    )

    assert len(snapshot.aircraft) == 1
    assert snapshot.aircraft[0].altitude_ft is None
    assert any("altitude_ft" in issue for issue in snapshot.issues)


def test_non_finite_float_fields_and_captured_at_degrade_to_none_and_report_issues() -> None:
    snapshot = AircraftSnapshot.from_dict(
        {
            "captured_at": "nan",
            "aircraft": [
                {
                    "hex": "abc102",
                    "distance_km": "nan",
                    "bearing_deg": "nan",
                    "track_deg": "inf",
                    "ground_speed_kt": "-inf",
                    "seen_at": "inf",
                },
                {
                    "hex": "abc101",
                    "distance_km": 1.5,
                },
            ],
        }
    )

    assert snapshot.captured_at is None
    assert any("captured_at" in issue for issue in snapshot.issues)

    by_hex = {a.hex: a for a in snapshot.aircraft}
    bad = by_hex["abc102"]
    for field_name in ("distance_km", "bearing_deg", "track_deg", "ground_speed_kt", "seen_at"):
        value = getattr(bad, field_name)
        assert value is None or math.isfinite(value), f"{field_name} retained non-finite {value!r}"
        assert value is None, f"{field_name} should degrade to None"
        assert any(field_name in issue for issue in snapshot.issues)

    # Aircraft with degraded distance_km=None must sort after finite distances, never first.
    assert [a.hex for a in snapshot.by_distance()] == ["abc101", "abc102"]


def test_accepts_tilde_prefixed_non_icao_hex_address_from_selection_contract() -> None:
    snapshot = AircraftSnapshot.from_dict(
        {
            "captured_at": 1762500000,
            "aircraft": [
                {
                    "hex": " ~ABCDEF ",
                    "type_code": "C172",
                    "distance_km": 1.8,
                }
            ],
        }
    )

    assert snapshot.dropped == ()
    assert len(snapshot.aircraft) == 1
    assert snapshot.aircraft[0].hex == "~abcdef"
    assert snapshot.aircraft[0].label == "~ABCDEF"
