"""Tests for timestamps, freshness boundaries, feed staleness, and clock skew (contract §§3, 10, 13.3, 13.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from phlight.aircraft import (
    MAX_CLOCK_SKEW_S,
    SelectionConfig,
    select,
    select_from_file,
)

from .conftest import CONTROLLED_NOW, make_snapshot


@pytest.mark.parametrize(
    ("seen_pos", "expected_state", "expected_rejected"),
    [
        (9.9, "ok", {}),
        (10.0, "ok", {}),
        (10.1, "empty_sky", {"stale_position": 1}),
    ],
)
def test_position_age_boundary_at_zero_snapshot_age(
    hk_config: SelectionConfig,
    seen_pos: float,
    expected_state: str,
    expected_rejected: dict[str, int],
) -> None:
    """Catches wrong comparison operator (< vs <=) on the 10.0 s position freshness threshold (contract §10.5)."""
    snapshot = make_snapshot(
        [
            {
                "hex": "780a10",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": seen_pos,
                "seen": 0.2,
            }
        ]
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == expected_state
    assert dict(result.rejected) == expected_rejected
    if expected_state == "ok":
        assert result.aircraft is not None
        assert result.aircraft.position_age_s == pytest.approx(seen_pos, abs=1e-9)
    else:
        assert result.aircraft is None


def test_position_age_adds_snapshot_age_to_seen_pos(
    hk_config: SelectionConfig,
) -> None:
    """Catches evaluating seen_pos against max_position_age_s without adding snapshot_age_s (contract §3)."""
    # Snapshot is 4.0 s old (file_now = now - 4.0).
    # seen_pos = 6.0 -> position_age_s = 10.0 (fresh)
    # seen_pos = 6.1 -> position_age_s = 10.1 (stale_position)
    fresh_snap = make_snapshot(
        [
            {
                "hex": "780aaa",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 6.0,
                "seen": 0.5,
            }
        ],
        file_now=CONTROLLED_NOW - 4.0,
    )
    stale_snap = make_snapshot(
        [
            {
                "hex": "780aaa",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 6.1,
                "seen": 0.5,
            }
        ],
        file_now=CONTROLLED_NOW - 4.0,
    )

    fresh_res = select(fresh_snap, hk_config, now=CONTROLLED_NOW)
    assert fresh_res.state == "ok"
    assert fresh_res.snapshot_age_s == pytest.approx(4.0, abs=1e-9)
    assert fresh_res.aircraft is not None
    assert fresh_res.aircraft.position_age_s == pytest.approx(10.0, abs=1e-9)
    assert fresh_res.aircraft.message_age_s == pytest.approx(4.5, abs=1e-9)

    stale_res = select(stale_snap, hk_config, now=CONTROLLED_NOW)
    assert stale_res.state == "empty_sky"
    assert dict(stale_res.rejected) == {"stale_position": 1}


@pytest.mark.parametrize(
    ("seen", "expected_state", "expected_rejected"),
    [
        (29.9, "ok", {}),
        (30.0, "ok", {}),
        (30.1, "empty_sky", {"stale_message": 1}),
    ],
)
def test_message_age_boundary_while_position_is_fresh(
    hk_config: SelectionConfig,
    seen: float,
    expected_state: str,
    expected_rejected: dict[str, int],
) -> None:
    """Catches ignoring seen or using < instead of <= on the 30.0 s message freshness threshold (contract §10.6)."""
    snapshot = make_snapshot(
        [
            {
                "hex": "780a20",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 0.5,
                "seen": seen,
            }
        ]
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == expected_state
    assert dict(result.rejected) == expected_rejected
    if expected_state == "ok":
        assert result.aircraft is not None
        assert result.aircraft.message_age_s == pytest.approx(seen, abs=1e-9)


def test_absent_seen_uses_snapshot_age_without_rejecting_aircraft(
    hk_config: SelectionConfig,
) -> None:
    """Catches rejecting a record or crashing when optional seen is omitted (amendment 13.3)."""
    snapshot = make_snapshot(
        [
            {
                "hex": "780a30",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 1.5,
            }
        ],
        file_now=CONTROLLED_NOW - 2.0,
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.aircraft is not None
    assert result.aircraft.hex == "780a30"
    assert result.aircraft.message_age_s == pytest.approx(2.0, abs=1e-9)
    assert result.aircraft.position_age_s == pytest.approx(3.5, abs=1e-9)


def test_negative_seen_and_seen_pos_are_clamped_to_zero(
    hk_config: SelectionConfig,
) -> None:
    """Catches negative seen/seen_pos reducing snapshot_age_s or rejecting the record (contract §3)."""
    snapshot = make_snapshot(
        [
            {
                "hex": "780a40",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": -0.4,
                "seen": -1.2,
            }
        ],
        file_now=CONTROLLED_NOW - 3.0,
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == "ok"
    assert result.aircraft is not None
    assert result.aircraft.position_age_s == pytest.approx(3.0, abs=1e-9)
    assert result.aircraft.message_age_s == pytest.approx(3.0, abs=1e-9)


@pytest.mark.parametrize(
    ("age_s", "expected_state", "expected_reason"),
    [
        (14.9, "ok", None),
        (15.0, "ok", None),
        (15.1, "stale_input", "feed_stalled"),
        (20.0, "stale_input", "feed_stalled"),
    ],
)
def test_snapshot_staleness_boundary_and_stalled_feed(
    hk_config: SelectionConfig,
    age_s: float,
    expected_state: str,
    expected_reason: str | None,
) -> None:
    """Catches selecting from a stalled decoder feed or off-by-one at max_snapshot_age_s (contract §§3, 10.9)."""
    config = SelectionConfig(
        home=hk_config.home,
        max_snapshot_age_s=15.0,
        max_position_age_s=20.0,
        max_message_age_s=30.0,
    )
    snapshot = make_snapshot(
        [
            {
                "hex": "780abc",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 0.0,
                "seen": 0.0,
            }
        ],
        file_now=CONTROLLED_NOW - age_s,
    )

    result = select(snapshot, config, now=CONTROLLED_NOW)

    assert result.state == expected_state
    assert result.reason == expected_reason
    assert result.snapshot_time == pytest.approx(CONTROLLED_NOW - age_s, abs=1e-6)
    assert result.evaluated_at == pytest.approx(CONTROLLED_NOW, abs=1e-6)
    assert result.snapshot_age_s == pytest.approx(age_s, abs=1e-6)
    if expected_state == "stale_input":
        assert result.aircraft is None
        assert result.considered_count == 0
        assert result.eligible_count == 0
        assert dict(result.rejected) == {}


def test_stale_snapshot_fixture_file_returns_stale_input(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches failure to report stale_input/feed_stalled when reading a 20 s old file from disk (contract §10.9)."""
    result = select_from_file(
        fixtures_dir / "synthetic_stale_snapshot.json",
        hk_config,
        now=CONTROLLED_NOW,
    )

    assert result.state == "stale_input"
    assert result.reason == "feed_stalled"
    assert result.aircraft is None
    assert result.snapshot_time == pytest.approx(1759999980.0, abs=1e-6)
    assert result.evaluated_at == pytest.approx(CONTROLLED_NOW, abs=1e-6)
    assert result.snapshot_age_s == pytest.approx(20.0, abs=1e-6)
    assert result.considered_count == 0
    assert result.eligible_count == 0
    assert dict(result.rejected) == {}


@pytest.mark.parametrize(
    ("future_offset_s", "expected_state", "expected_reason"),
    [
        (4.9, "ok", None),
        (5.0, "ok", None),
        (5.1, "invalid_input", "invalid_now"),
        (60.0, "invalid_input", "invalid_now"),
    ],
)
def test_bounded_future_clock_skew_policy(
    hk_config: SelectionConfig,
    future_offset_s: float,
    expected_state: str,
    expected_reason: str | None,
) -> None:
    """Catches unbounded clamping of future file_now that would make a future-dated frozen file look fresh forever (amendment 13.4)."""
    assert MAX_CLOCK_SKEW_S == 5.0
    file_now = CONTROLLED_NOW + future_offset_s
    snapshot = make_snapshot(
        [
            {
                "hex": "780a50",
                "lat": 22.3193,
                "lon": 114.1694,
                "seen_pos": 0.2,
                "seen": 0.1,
            }
        ],
        file_now=file_now,
    )

    result = select(snapshot, hk_config, now=CONTROLLED_NOW)

    assert result.state == expected_state
    assert result.reason == expected_reason
    assert result.snapshot_time == pytest.approx(file_now, abs=1e-6)
    assert result.snapshot_age_s == pytest.approx(0.0, abs=1e-9)
    if expected_state == "ok":
        assert result.aircraft is not None
        assert result.aircraft.hex == "780a50"
        assert result.aircraft.position_age_s == pytest.approx(0.2, abs=1e-9)
    else:
        assert result.aircraft is None
        assert result.considered_count == 0
        assert result.eligible_count == 0
        assert dict(result.rejected) == {}


def test_future_snapshot_fixture_file_rejected_as_invalid_now(
    fixtures_dir: Path,
    hk_config: SelectionConfig,
) -> None:
    """Catches accepting a file on disk whose now is 60 s ahead of injected caller clock (amendment 13.4)."""
    result = select_from_file(
        fixtures_dir / "synthetic_future_snapshot.json",
        hk_config,
        now=CONTROLLED_NOW,
    )

    assert result.state == "invalid_input"
    assert result.reason == "invalid_now"
    assert result.aircraft is None
    assert result.snapshot_time == pytest.approx(1760000060.0, abs=1e-6)
    assert result.snapshot_age_s == pytest.approx(0.0, abs=1e-9)


def test_now_parameter_is_mandatory_keyword_only_and_validated(
    hk_config: SelectionConfig,
) -> None:
    """Catches defaulting now to wall clock or accepting positional/non-finite/boolean now (contract §8.3)."""
    snapshot = make_snapshot([])

    with pytest.raises(TypeError):
        select(snapshot, hk_config)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        select(snapshot, hk_config, CONTROLLED_NOW)  # type: ignore[misc]

    with pytest.raises(TypeError):
        select(snapshot, hk_config, now=True)  # type: ignore[arg-type]

    with pytest.raises(TypeError):
        select(snapshot, hk_config, now="1760000000.0")  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        select(snapshot, hk_config, now=float("nan"))

    with pytest.raises(ValueError):
        select(snapshot, hk_config, now=float("inf"))
