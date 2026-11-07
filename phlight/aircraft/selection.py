"""Proximity selection over one decoder snapshot.

``select()`` is a pure function of ``(snapshot, config, now)``: it never reads
the system clock, the environment, file mtimes or randomness, so the same
inputs give the same result on any platform. Data problems are states in the
result, not exceptions.

See ``docs/aircraft-selection-contract.md`` sections 3, 5, 6, 7, 8.3 and 9.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Sequence

from .model import (
    EARTH_RADIUS_M,
    MAX_CLOCK_SKEW_S,
    REASON_AIRCRAFT_NOT_LIST,
    REASON_CONFIG_INVALID,
    REASON_FEED_STALLED,
    REASON_HOME_NOT_CONFIGURED,
    REASON_INVALID_NOW,
    REJECT_DUPLICATE_HEX,
    REJECT_GROUND,
    REJECT_INVALID_HEX,
    REJECT_INVALID_POSITION,
    REJECT_INVALID_RECORD,
    REJECT_INVALID_TIMESTAMP,
    REJECT_NO_POSITION,
    REJECT_OUT_OF_RANGE,
    REJECT_STALE_MESSAGE,
    REJECT_STALE_POSITION,
    REJECTION_CODES,
    STATE_EMPTY_SKY,
    STATE_INVALID_INPUT,
    STATE_OK,
    STATE_STALE_INPUT,
    STATE_UNCONFIGURED,
    AircraftReport,
    SelectionConfig,
    SelectionResult,
    SourceSnapshot,
    in_epoch_range,
    is_finite_number,
)
from .source import read_snapshot

_HEX_PATTERN = re.compile(r"^~?[0-9a-f]{6}$")

_MISSING = object()

#: Knots at or below which a zero-or-negative altitude counts as surface traffic.
_GROUND_SPEED_KT = 30.0


def distance_m(home_lat: float, home_lon: float, lat: float, lon: float) -> float:
    """Great-circle distance in metres using the haversine formula.

    Uses a spherical Earth of mean radius 6 371 008.8 m (contract section 5.1),
    which is deterministic and accurate to a few tenths of a percent — well
    inside a gate whose position inputs are already kilometres uncertain.
    Identical coordinates return exactly ``0.0``.
    """

    phi1 = math.radians(home_lat)
    phi2 = math.radians(lat)
    dphi = phi2 - phi1
    dlambda = math.radians(lon) - math.radians(home_lon)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def _round_half_up(value: float) -> int:
    """Nearest integer, half away from zero for the positive values we see."""
    return int(math.floor(value + 0.5))


def _terminal(
    state: str,
    reason: str | None,
    *,
    now: float,
    snapshot_time: float | None = None,
    snapshot_age_s: float | None = None,
) -> SelectionResult:
    """A result with no selected aircraft and no evaluated records."""

    return SelectionResult(
        state=state,
        aircraft=None,
        reason=reason,
        snapshot_time=snapshot_time,
        evaluated_at=now,
        snapshot_age_s=snapshot_age_s,
        considered_count=0,
        eligible_count=0,
        rejected={},
    )


def _callsign(entry: dict) -> str | None:
    flight = entry.get("flight")
    if not isinstance(flight, str):
        return None
    callsign = flight.rstrip()
    return callsign or None


def _altitude_ft(entry: dict) -> int | None:
    altitude = entry.get("alt_baro")
    if is_finite_number(altitude):
        return _round_half_up(float(altitude))
    return None


def _optional_number(entry: dict, key: str) -> float | None:
    value = entry.get(key)
    if is_finite_number(value):
        return float(value)
    return None


def _optional_text(entry: dict, key: str) -> str | None:
    value = entry.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _on_ground(entry: dict) -> bool:
    """Surface traffic, per contract section 6.

    ``alt_baro == "ground"`` is the decoder's own sentinel; a numeric altitude
    at or below zero still counts when the aircraft is slow (some decoders emit
    ``0`` for surface vehicles, which would otherwise win every proximity
    contest).
    """

    altitude = entry.get("alt_baro")
    if isinstance(altitude, str) and altitude == "ground":
        return True
    if is_finite_number(altitude) and float(altitude) <= 0.0:
        speed = entry.get("gs")
        if is_finite_number(speed) and float(speed) <= _GROUND_SPEED_KT:
            return True
    return False


def _position(entry: dict) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` when both are usable WGS84 numbers."""

    lat = entry.get("lat", _MISSING)
    lon = entry.get("lon", _MISSING)
    if lat is _MISSING or lon is _MISSING:
        return None
    if not is_finite_number(lat) or not is_finite_number(lon):
        return None
    lat_f = float(lat)
    lon_f = float(lon)
    if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lon_f <= 180.0):
        return None
    return lat_f, lon_f


def _ages(
    entry: dict, snapshot_age_s: float
) -> tuple[float, float] | None:
    """Return ``(message_age_s, position_age_s)`` or ``None`` when unusable.

    Decoder ages are relative to the file's own ``now``, so the snapshot's own
    age is added: a frozen decoder file must not look fresh. Negative ages
    (clock skew, float rounding) clamp to zero.
    """

    seen_pos = entry.get("seen_pos", _MISSING)
    if seen_pos is _MISSING or not is_finite_number(seen_pos):
        return None
    seen = entry.get("seen", _MISSING)
    if seen is not _MISSING and not is_finite_number(seen):
        return None
    message_age = snapshot_age_s
    if seen is not _MISSING:
        message_age += max(0.0, float(seen))
    position_age = snapshot_age_s + max(0.0, float(seen_pos))
    return message_age, position_age


def select(
    snapshot: SourceSnapshot,
    config: SelectionConfig,
    *,
    now: float,
) -> SelectionResult:
    """Choose the nearest eligible aircraft, or say why none was chosen.

    ``now`` is the injected caller clock in Unix seconds; nothing here reads the
    system clock. The result state follows the contract's precedence:
    ``unconfigured`` → input states → ``stale_input`` → ``empty_sky`` / ``ok``.
    """

    if not isinstance(snapshot, SourceSnapshot):
        raise TypeError("snapshot must be a SourceSnapshot")
    if not isinstance(config, SelectionConfig):
        raise TypeError("config must be a SelectionConfig")
    if isinstance(now, bool) or not isinstance(now, (int, float)):
        raise TypeError("now must be a Unix timestamp in seconds")
    now_f = float(now)
    if not math.isfinite(now_f):
        raise ValueError("now must be finite")

    # 1. Configuration first: with no usable home there is nothing to evaluate.
    if config.problems:
        return _terminal(STATE_UNCONFIGURED, REASON_CONFIG_INVALID, now=now_f)
    if config.home is None:
        return _terminal(STATE_UNCONFIGURED, REASON_HOME_NOT_CONFIGURED, now=now_f)

    # 2. A source that failed to read propagates its state unchanged.
    if snapshot.state != STATE_OK:
        state = snapshot.state if isinstance(snapshot.state, str) else STATE_INVALID_INPUT
        return _terminal(state, snapshot.error, now=now_f)

    # 3. Defensive validation: the component must not assume read_snapshot
    #    produced the snapshot (hand-built snapshots are legal input).
    file_now = snapshot.file_now
    if not in_epoch_range(file_now):
        return _terminal(STATE_INVALID_INPUT, REASON_INVALID_NOW, now=now_f)
    file_now_f = float(file_now)

    # A frozen file that claims to be from the future would otherwise clamp to
    # zero age and look live forever (amendment 13.4).
    if file_now_f - now_f > MAX_CLOCK_SKEW_S:
        return _terminal(
            STATE_INVALID_INPUT,
            REASON_INVALID_NOW,
            now=now_f,
            snapshot_time=file_now_f,
            snapshot_age_s=0.0,
        )

    aircraft = snapshot.aircraft
    if not isinstance(aircraft, Sequence) or isinstance(aircraft, (str, bytes)):
        return _terminal(
            STATE_INVALID_INPUT,
            REASON_AIRCRAFT_NOT_LIST,
            now=now_f,
            snapshot_time=file_now_f,
        )

    snapshot_age_s = max(0.0, now_f - file_now_f)

    # 4. A dead feed is not a quiet sky.
    if snapshot_age_s > config.max_snapshot_age_s:
        return _terminal(
            STATE_STALE_INPUT,
            REASON_FEED_STALLED,
            now=now_f,
            snapshot_time=file_now_f,
            snapshot_age_s=snapshot_age_s,
        )

    # 5. Evaluate each record once, first matching reason wins.
    rejected: dict[str, int] = {code: 0 for code in REJECTION_CODES}
    seen_hex: set[str] = set()
    candidates: list[AircraftReport] = []
    considered = 0

    home = config.home
    max_distance_m = config.max_distance_km * 1000.0

    for entry in aircraft:
        considered += 1

        if not isinstance(entry, dict):
            rejected[REJECT_INVALID_RECORD] += 1
            continue

        raw_hex = entry.get("hex")
        if not isinstance(raw_hex, str):
            rejected[REJECT_INVALID_HEX] += 1
            continue
        hex_code = raw_hex.lower()
        if not _HEX_PATTERN.fullmatch(hex_code):
            rejected[REJECT_INVALID_HEX] += 1
            continue
        if hex_code in seen_hex:
            rejected[REJECT_DUPLICATE_HEX] += 1
            continue
        seen_hex.add(hex_code)

        if ("lat" not in entry) or ("lon" not in entry):
            rejected[REJECT_NO_POSITION] += 1
            continue
        position = _position(entry)
        if position is None:
            rejected[REJECT_INVALID_POSITION] += 1
            continue
        lat, lon = position

        ages = _ages(entry, snapshot_age_s)
        if ages is None:
            rejected[REJECT_INVALID_TIMESTAMP] += 1
            continue
        message_age_s, position_age_s = ages

        if message_age_s > config.max_message_age_s:
            rejected[REJECT_STALE_MESSAGE] += 1
            continue
        if position_age_s > config.max_position_age_s:
            rejected[REJECT_STALE_POSITION] += 1
            continue

        on_ground = _on_ground(entry)
        if on_ground and config.ignore_ground:
            rejected[REJECT_GROUND] += 1
            continue

        distance = distance_m(home.lat, home.lon, lat, lon)
        if distance > max_distance_m:
            rejected[REJECT_OUT_OF_RANGE] += 1
            continue

        candidates.append(
            AircraftReport(
                hex=hex_code,
                callsign=_callsign(entry),
                lat=lat,
                lon=lon,
                distance_m=distance,
                distance_nm=distance / 1852.0,
                position_age_s=position_age_s,
                message_age_s=message_age_s,
                altitude_ft=_altitude_ft(entry),
                on_ground=on_ground,
                track_deg=_optional_number(entry, "track"),
                ground_speed_kt=_optional_number(entry, "gs"),
                category=_optional_text(entry, "category"),
                source_type=_optional_text(entry, "type"),
            )
        )

    # 6. Total order: rounded metres, then fresher position, then hex.
    candidates.sort(
        key=lambda report: (
            _round_half_up(report.distance_m),
            report.position_age_s,
            report.hex,
        )
    )

    winner = candidates[0] if candidates else None
    return SelectionResult(
        state=STATE_OK if winner is not None else STATE_EMPTY_SKY,
        aircraft=winner,
        reason=None,
        snapshot_time=file_now_f,
        evaluated_at=now_f,
        snapshot_age_s=snapshot_age_s,
        considered_count=considered,
        eligible_count=len(candidates),
        rejected={code: count for code, count in rejected.items() if count},
    )


def select_from_file(
    path: str | os.PathLike[str],
    config: SelectionConfig,
    *,
    now: float,
) -> SelectionResult:
    """Read ``path`` once and select from it. Equivalent to ``select(read_snapshot(path), ...)``."""

    return select(read_snapshot(path), config, now=now)