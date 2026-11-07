"""Local aircraft ingest and proximity selection.

Public interface, as fixed by ``docs/aircraft-selection-contract.md`` §8.5::

    from phlight.aircraft import (
        HomeLocation, SelectionConfig, SourceSnapshot, AircraftReport,
        SelectionResult, read_snapshot, select, select_from_file, distance_m,
        load_config,
    )

Read one decoder file::

    config, problems = load_config(mapping)
    result = select_from_file("/run/readsb/aircraft.json", config, now=time.time())

The result state is one of ``ok``, ``empty_sky``, ``stale_input``,
``missing_input``, ``invalid_input`` or ``unconfigured``. Every state other than
``ok`` renders as the empty-sky artwork; ``aircraft`` is ``None`` then.
"""

from __future__ import annotations

from .config import (
    DEFAULT_SOURCE_PATH,
    ENV_HOME_LAT,
    ENV_HOME_LON,
    ENV_MAX_DISTANCE_KM,
    ENV_SOURCE_PATH,
    load_config,
    load_source_path,
)
from .model import (
    EARTH_RADIUS_M,
    MAX_CLOCK_SKEW_S,
    MAX_EPOCH_SECONDS,
    MIN_EPOCH_SECONDS,
    REASON_AIRCRAFT_NOT_LIST,
    REASON_CONFIG_INVALID,
    REASON_FEED_STALLED,
    REASON_FILE_NOT_FOUND,
    REASON_HOME_NOT_CONFIGURED,
    REASON_INVALID_NOW,
    REASON_IO_ERROR,
    REASON_JSON_DECODE,
    REASON_NOT_AN_OBJECT,
    REASON_PERMISSION_DENIED,
    REASONS,
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
    STATE_MISSING_INPUT,
    STATE_OK,
    STATE_STALE_INPUT,
    STATE_UNCONFIGURED,
    STATES,
    AircraftReport,
    HomeLocation,
    SelectionConfig,
    SelectionResult,
    SourceSnapshot,
    in_epoch_range,
    is_finite_number,
)
from .selection import distance_m, select, select_from_file
from .source import read_snapshot

__all__ = [
    # data model
    "HomeLocation",
    "SelectionConfig",
    "SourceSnapshot",
    "AircraftReport",
    "SelectionResult",
    # functions
    "read_snapshot",
    "select",
    "select_from_file",
    "distance_m",
    "load_config",
    "load_source_path",
    # states
    "STATE_OK",
    "STATE_EMPTY_SKY",
    "STATE_STALE_INPUT",
    "STATE_MISSING_INPUT",
    "STATE_INVALID_INPUT",
    "STATE_UNCONFIGURED",
    "STATES",
    # reasons
    "REASON_FILE_NOT_FOUND",
    "REASON_PERMISSION_DENIED",
    "REASON_IO_ERROR",
    "REASON_JSON_DECODE",
    "REASON_NOT_AN_OBJECT",
    "REASON_AIRCRAFT_NOT_LIST",
    "REASON_INVALID_NOW",
    "REASON_FEED_STALLED",
    "REASON_HOME_NOT_CONFIGURED",
    "REASON_CONFIG_INVALID",
    "REASONS",
    # rejection codes
    "REJECT_INVALID_RECORD",
    "REJECT_INVALID_HEX",
    "REJECT_DUPLICATE_HEX",
    "REJECT_NO_POSITION",
    "REJECT_INVALID_POSITION",
    "REJECT_INVALID_TIMESTAMP",
    "REJECT_STALE_MESSAGE",
    "REJECT_STALE_POSITION",
    "REJECT_GROUND",
    "REJECT_OUT_OF_RANGE",
    "REJECTION_CODES",
    # configuration
    "DEFAULT_SOURCE_PATH",
    "ENV_SOURCE_PATH",
    "ENV_HOME_LAT",
    "ENV_HOME_LON",
    "ENV_MAX_DISTANCE_KM",
    # helpers
    "EARTH_RADIUS_M",
    "MAX_CLOCK_SKEW_S",
    "MIN_EPOCH_SECONDS",
    "MAX_EPOCH_SECONDS",
    "in_epoch_range",
    "is_finite_number",
]