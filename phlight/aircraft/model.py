"""Data model, state constants and rejection codes for aircraft selection.

State and reason values are plain lowercase strings so callers and tests may
compare against literals. They are collected here so the selection rules and
the documentation use one vocabulary.

See ``docs/aircraft-selection-contract.md`` (sections 6, 7 and 8.1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, TypeGuard

# --- Result states (contract section 7) -----------------------------------

STATE_OK = "ok"
STATE_EMPTY_SKY = "empty_sky"
STATE_STALE_INPUT = "stale_input"
STATE_MISSING_INPUT = "missing_input"
STATE_INVALID_INPUT = "invalid_input"
STATE_UNCONFIGURED = "unconfigured"

STATES: tuple[str, ...] = (
    STATE_OK,
    STATE_EMPTY_SKY,
    STATE_STALE_INPUT,
    STATE_MISSING_INPUT,
    STATE_INVALID_INPUT,
    STATE_UNCONFIGURED,
)

# --- Reasons attached to a non-ok state (contract section 7) -------------

REASON_FILE_NOT_FOUND = "file_not_found"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_IO_ERROR = "io_error"
REASON_JSON_DECODE = "json_decode"
REASON_NOT_AN_OBJECT = "not_an_object"
REASON_AIRCRAFT_NOT_LIST = "aircraft_not_list"
REASON_INVALID_NOW = "invalid_now"
REASON_FEED_STALLED = "feed_stalled"
REASON_HOME_NOT_CONFIGURED = "home_not_configured"
REASON_CONFIG_INVALID = "config_invalid"

REASONS: tuple[str, ...] = (
    REASON_FILE_NOT_FOUND,
    REASON_PERMISSION_DENIED,
    REASON_IO_ERROR,
    REASON_JSON_DECODE,
    REASON_NOT_AN_OBJECT,
    REASON_AIRCRAFT_NOT_LIST,
    REASON_INVALID_NOW,
    REASON_FEED_STALLED,
    REASON_HOME_NOT_CONFIGURED,
    REASON_CONFIG_INVALID,
)

# --- Per-aircraft rejection codes, in evaluation order (contract section 6)

REJECT_INVALID_RECORD = "invalid_record"
REJECT_INVALID_HEX = "invalid_hex"
REJECT_DUPLICATE_HEX = "duplicate_hex"
REJECT_NO_POSITION = "no_position"
REJECT_INVALID_POSITION = "invalid_position"
REJECT_INVALID_TIMESTAMP = "invalid_timestamp"
REJECT_STALE_MESSAGE = "stale_message"
REJECT_STALE_POSITION = "stale_position"
REJECT_GROUND = "ground"
REJECT_OUT_OF_RANGE = "out_of_range"

REJECTION_CODES: tuple[str, ...] = (
    REJECT_INVALID_RECORD,
    REJECT_INVALID_HEX,
    REJECT_DUPLICATE_HEX,
    REJECT_NO_POSITION,
    REJECT_INVALID_POSITION,
    REJECT_INVALID_TIMESTAMP,
    REJECT_STALE_MESSAGE,
    REJECT_STALE_POSITION,
    REJECT_GROUND,
    REJECT_OUT_OF_RANGE,
)

# --- Range limits ---------------------------------------------------------

#: Unix seconds accepted for a decoder file's ``now``: 2001-09-09 .. 5138-11-16.
MIN_EPOCH_SECONDS = 1e9
MAX_EPOCH_SECONDS = 1e11

#: Mean Earth radius used by the haversine distance, in metres.
EARTH_RADIUS_M = 6_371_008.8

#: A snapshot whose ``now`` is further ahead of the caller clock than this is
#: rejected rather than clamped, so a frozen future-dated file cannot look live
#: (contract amendment 13.4). The decoder and selector share one host clock, so
#: any real difference is a clock jump.
MAX_CLOCK_SKEW_S = 5.0


def is_finite_number(value: object) -> TypeGuard[int | float]:
    """Return True for a real finite number, rejecting booleans and strings.

    ``bool`` is a subclass of ``int`` in Python, and JSON decoders can emit very
    large integers, so both cases are handled explicitly.
    """

    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):  # pragma: no cover - exotic ints
        return False


def in_epoch_range(value: object) -> TypeGuard[int | float]:
    """Return True when ``value`` is a plausible Unix-seconds timestamp."""

    if not is_finite_number(value):
        return False
    return MIN_EPOCH_SECONDS <= float(value) < MAX_EPOCH_SECONDS


@dataclass(frozen=True, slots=True)
class HomeLocation:
    """Viewer position in WGS84 decimal degrees.

    Values are validated in ``__post_init__`` and rejected rather than clamped.
    ``-0.0``, integers and floats are accepted; strings and booleans are not.
    """

    lat: float
    lon: float

    def __post_init__(self) -> None:
        for field_name, limit in (("lat", 90.0), ("lon", 180.0)):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(
                    f"home {field_name} must be a number, "
                    f"got {type(value).__name__}"
                )
            try:
                number = float(value)
            except (OverflowError, ValueError) as exc:  # pragma: no cover
                raise TypeError(f"home {field_name} must be a number") from exc
            if not math.isfinite(number):
                raise ValueError(f"home {field_name} must be finite")
            if not -limit <= number <= limit:
                raise ValueError(
                    f"home {field_name} must be within {-limit:g}..{limit:g}"
                )
            object.__setattr__(self, field_name, number)


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    """Selection thresholds and the viewer position.

    ``problems`` is additive to the contract's field list: it carries the
    ``load_config`` problem codes so :func:`phlight.aircraft.select` can report
    ``unconfigured`` / ``config_invalid`` as section 8.4 requires. It is empty
    for hand-built configs and never alters selection when empty.
    """

    home: HomeLocation | None = None
    max_distance_km: float = 15.0
    max_position_age_s: float = 10.0
    max_message_age_s: float = 30.0
    max_snapshot_age_s: float = 15.0
    ignore_ground: bool = True
    problems: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.home is not None and not isinstance(self.home, HomeLocation):
            raise TypeError("home must be a HomeLocation or None")
        for field_name in (
            "max_distance_km",
            "max_position_age_s",
            "max_message_age_s",
            "max_snapshot_age_s",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be a number")
            try:
                number = float(value)
            except (OverflowError, ValueError) as exc:  # pragma: no cover
                raise TypeError(f"{field_name} must be a number") from exc
            if not math.isfinite(number):
                raise ValueError(f"{field_name} must be finite")
            if field_name == "max_distance_km":
                if number <= 0.0:
                    raise ValueError("max_distance_km must be positive")
            elif number < 0.0:
                raise ValueError(f"{field_name} must not be negative")
            object.__setattr__(self, field_name, number)
        if not isinstance(self.ignore_ground, bool):
            raise TypeError("ignore_ground must be a bool")
        if not isinstance(self.problems, tuple):
            object.__setattr__(self, "problems", tuple(self.problems))


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """One read of a decoder's ``aircraft.json``.

    ``aircraft`` holds the raw entries in file order; the selection step does
    all interpretation. When ``state`` is not ``"ok"`` the snapshot carries no
    usable data: ``file_now`` is ``None`` and ``aircraft`` is empty.
    """

    state: str
    file_now: float | None = None
    aircraft: tuple[dict, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class AircraftReport:
    """A selected aircraft, with the facts the artwork needs."""

    hex: str
    callsign: str | None
    lat: float
    lon: float
    distance_m: float
    distance_nm: float
    position_age_s: float
    message_age_s: float
    altitude_ft: int | None
    on_ground: bool
    track_deg: float | None
    ground_speed_kt: float | None
    category: str | None
    source_type: str | None


@dataclass(frozen=True, slots=True)
class SelectionResult:
    """Outcome of one selection pass.

    ``state`` is always one of :data:`STATES`; ``aircraft`` is ``None`` unless
    ``state == "ok"``. ``rejected`` counts only non-zero rejection codes, so its
    sum plus ``eligible_count`` equals ``considered_count`` for a valid
    snapshot.
    """

    state: str
    aircraft: AircraftReport | None
    reason: str | None
    snapshot_time: float | None
    evaluated_at: float
    snapshot_age_s: float | None
    considered_count: int
    eligible_count: int
    rejected: Mapping[str, int]