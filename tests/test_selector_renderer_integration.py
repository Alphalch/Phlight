"""Integration and regression tests across phlight.aircraft and phlight.render.

Exercises the local selector (``phlight.aircraft``) and portrait renderer
(``phlight.render``) against shared deterministic local inputs and failure
states without a live ADS-B feed, network service, or physical display.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from phlight.aircraft import (
    REASON_AIRCRAFT_NOT_LIST,
    REASON_CONFIG_INVALID,
    REASON_FEED_STALLED,
    REASON_FILE_NOT_FOUND,
    REASON_HOME_NOT_CONFIGURED,
    REASON_INVALID_NOW,
    REASON_JSON_DECODE,
    REASON_NOT_AN_OBJECT,
    REJECT_GROUND,
    REJECT_NO_POSITION,
    REJECT_OUT_OF_RANGE,
    REJECT_STALE_POSITION,
    STATE_EMPTY_SKY,
    STATE_INVALID_INPUT,
    STATE_MISSING_INPUT,
    STATE_OK,
    STATE_STALE_INPUT,
    STATE_UNCONFIGURED,
    HomeLocation,
    SelectionConfig,
    SourceSnapshot,
    load_config,
    read_snapshot,
    select,
    select_from_file,
)
from phlight.render import (
    AircraftSnapshot,
    RenderConfig,
    load_snapshot,
    render_snapshot,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
HOME = HomeLocation(lat=22.3375, lon=114.1831)
NOW = 1762500001.0


def test_selector_rejects_ineligible_records_without_forcing_empty_sky() -> None:
    config = SelectionConfig(home=HOME, max_distance_km=15.0)
    result = select_from_file(FIXTURES / "readsb_decoder_snapshot.json", config, now=NOW)

    assert result.state == STATE_OK
    assert result.aircraft is not None
    assert result.aircraft.hex == "780912"
    assert result.aircraft.callsign == "HDA812"
    assert result.considered_count == 6
    assert result.eligible_count == 2
    assert result.rejected == {
        REJECT_GROUND: 1,
        REJECT_NO_POSITION: 1,
        REJECT_STALE_POSITION: 1,
        REJECT_OUT_OF_RANGE: 1,
    }
    assert sum(result.rejected.values()) + result.eligible_count == result.considered_count


def test_selector_empty_sky_when_all_aircraft_out_of_range_renders_empty_state() -> None:
    config = SelectionConfig(home=HOME, max_distance_km=0.5)
    result = select_from_file(FIXTURES / "readsb_decoder_snapshot.json", config, now=NOW)

    assert result.state == STATE_EMPTY_SKY
    assert result.aircraft is None
    assert result.eligible_count == 0

    snapshot = AircraftSnapshot(captured_at=result.snapshot_time, aircraft=())
    render_res = render_snapshot(snapshot, RenderConfig(width=240, height=400, now=NOW))

    assert render_res.status == "empty"
    assert render_res.empty_sky is True
    assert render_res.rendered_ids == ()


def test_selector_failure_states_produce_no_aircraft_deterministically(tmp_path: Path) -> None:
    valid_cfg = SelectionConfig(home=HOME)
    raw_snap = read_snapshot(FIXTURES / "readsb_decoder_snapshot.json")

    # 1. unconfigured / home_not_configured
    unconfigured_home = select(raw_snap, SelectionConfig(home=None), now=NOW)
    assert unconfigured_home.state == STATE_UNCONFIGURED
    assert unconfigured_home.reason == REASON_HOME_NOT_CONFIGURED
    assert unconfigured_home.aircraft is None

    # 2. unconfigured / config_invalid
    bad_cfg, problems = load_config(None, environ={})
    assert problems == ("config_not_mapping",)
    unconfigured_bad = select(raw_snap, bad_cfg, now=NOW)
    assert unconfigured_bad.state == STATE_UNCONFIGURED
    assert unconfigured_bad.reason == REASON_CONFIG_INVALID
    assert unconfigured_bad.aircraft is None

    # 3. missing_input / file_not_found
    missing_res = select_from_file(tmp_path / "absent.json", valid_cfg, now=NOW)
    assert missing_res.state == STATE_MISSING_INPUT
    assert missing_res.reason == REASON_FILE_NOT_FOUND
    assert missing_res.aircraft is None

    # 4. invalid_input / json_decode, not_an_object, aircraft_not_list, invalid_now
    bad_json = tmp_path / "corrupt.json"
    bad_json.write_text("{corrupt", encoding="utf-8")
    assert select_from_file(bad_json, valid_cfg, now=NOW) == select_from_file(
        bad_json, valid_cfg, now=NOW
    )
    assert select_from_file(bad_json, valid_cfg, now=NOW).state == STATE_INVALID_INPUT
    assert select_from_file(bad_json, valid_cfg, now=NOW).reason == REASON_JSON_DECODE

    list_json = tmp_path / "list.json"
    list_json.write_text("[]", encoding="utf-8")
    assert select_from_file(list_json, valid_cfg, now=NOW).reason == REASON_NOT_AN_OBJECT

    not_list = SourceSnapshot(state=STATE_OK, file_now=1762500000.0, aircraft="bad")  # type: ignore[arg-type]
    assert select(not_list, valid_cfg, now=NOW).reason == REASON_AIRCRAFT_NOT_LIST

    bad_now = SourceSnapshot(state=STATE_OK, file_now=123.0, aircraft=())
    assert select(bad_now, valid_cfg, now=NOW).reason == REASON_INVALID_NOW

    # 5. stale_input / feed_stalled
    stale_res = select(raw_snap, valid_cfg, now=1762500000.0 + 25.0)
    assert stale_res.state == STATE_STALE_INPUT
    assert stale_res.reason == REASON_FEED_STALLED
    assert stale_res.aircraft is None


def test_selected_non_icao_tilde_hex_aircraft_is_accepted_by_renderer() -> None:
    """Contract §2.3 allows ~abcdef non-ICAO hexes in selector; renderer must not drop them."""
    source = SourceSnapshot(
        state=STATE_OK,
        file_now=1762500000.0,
        aircraft=(
            {
                "hex": "~abcdef",
                "flight": "TISB01  ",
                "alt_baro": 3400,
                "gs": 180.0,
                "track": 90.0,
                "lat": 22.3450,
                "lon": 114.1831,
                "seen": 0.5,
                "seen_pos": 1.0,
            },
        ),
    )
    sel = select(source, SelectionConfig(home=HOME), now=NOW)
    assert sel.state == STATE_OK
    assert sel.aircraft is not None
    assert sel.aircraft.hex == "~abcdef"

    snapshot = AircraftSnapshot.from_dict(
        {
            "captured_at": sel.snapshot_time,
            "aircraft": [asdict(sel.aircraft)],
        }
    )
    assert snapshot.dropped == ()
    assert len(snapshot.aircraft) == 1

    rendered = render_snapshot(snapshot, RenderConfig(width=240, height=400, now=NOW))
    assert rendered.status == "current"
    assert rendered.empty_sky is False
    assert rendered.rendered_ids == ("~abcdef",)


def test_selected_aircraft_report_distance_is_preserved_by_renderer_model() -> None:
    """Selection emits distance_m/distance_nm on AircraftReport; renderer must preserve distance_km."""
    sel = select_from_file(
        FIXTURES / "readsb_decoder_snapshot.json",
        SelectionConfig(home=HOME),
        now=NOW,
    )
    assert sel.state == STATE_OK
    assert sel.aircraft is not None

    snapshot = AircraftSnapshot.from_dict(
        {
            "captured_at": sel.snapshot_time,
            "aircraft": [asdict(sel.aircraft)],
        }
    )
    assert len(snapshot.aircraft) == 1
    assert snapshot.aircraft[0].distance_km == pytest.approx(sel.aircraft.distance_m / 1000.0)


def test_readsb_decoder_snapshot_loaded_by_renderer_preserves_capture_time_and_metrics() -> None:
    """Local readsb aircraft.json uses now/flight/alt_baro/gs/track and includes surface traffic."""
    sel = select_from_file(
        FIXTURES / "readsb_decoder_snapshot.json",
        SelectionConfig(home=HOME),
        now=NOW,
    )
    assert sel.state == STATE_OK
    assert sel.aircraft is not None
    assert sel.aircraft.hex == "780912"

    snapshot = load_snapshot(FIXTURES / "readsb_decoder_snapshot.json")
    assert snapshot.captured_at == pytest.approx(1762500000.0)

    by_hex = {a.hex: a for a in snapshot.aircraft}
    assert "780912" in by_hex
    assert by_hex["780912"].callsign == "HDA812"
    assert by_hex["780912"].altitude_ft == 2175
    assert by_hex["780912"].ground_speed_kt == pytest.approx(164.0)
    assert by_hex["780912"].track_deg == pytest.approx(295.0)


def test_selection_result_mapping_passed_to_renderer_from_dict_preserves_winner_and_timestamp() -> None:
    """SelectionResult uses snapshot_time and a single aircraft report; renderer from_dict must accept it."""
    sel = select_from_file(
        FIXTURES / "readsb_decoder_snapshot.json",
        SelectionConfig(home=HOME),
        now=NOW,
    )
    assert sel.state == STATE_OK
    assert sel.aircraft is not None

    snapshot = AircraftSnapshot.from_dict(asdict(sel))
    assert snapshot.captured_at == pytest.approx(sel.snapshot_time)
    assert snapshot.issues == ()
    assert len(snapshot.aircraft) == 1
    assert snapshot.aircraft[0].hex == "780912"
    assert snapshot.aircraft[0].callsign == "HDA812"
    assert snapshot.aircraft[0].distance_km == pytest.approx(sel.aircraft.distance_m / 1000.0)

    rendered = render_snapshot(snapshot, RenderConfig(width=240, height=400, now=NOW))
    assert rendered.status == "current"
    assert rendered.empty_sky is False
    assert rendered.rendered_ids == ("780912",)
