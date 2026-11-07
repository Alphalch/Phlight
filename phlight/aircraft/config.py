"""Configuration loading for aircraft selection.

``load_config`` accepts an already-parsed mapping so that file discovery, TOML
parsing and CLI plumbing stay outside the selection component. It never raises
on bad data and never coerces a stringly-typed number: an invalid field falls
back to its default, the home block becomes ``None`` when unusable, and every
problem is reported as a code. ``select()`` turns a non-empty problem tuple into
``unconfigured`` / ``config_invalid``.

Precedence, highest first: an explicit argument the caller's own CLI built into
the mapping → environment → configuration file → defaults.

See ``docs/aircraft-selection-contract.md`` section 8.4.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from .model import HomeLocation, SelectionConfig, in_epoch_range, is_finite_number

#: readsb's ``--write-json`` default directory.
DEFAULT_SOURCE_PATH = "/run/readsb/aircraft.json"

ENV_SOURCE_PATH = "PHLIGHT_AIRCRAFT_JSON"
ENV_HOME_LAT = "PHLIGHT_HOME_LAT"
ENV_HOME_LON = "PHLIGHT_HOME_LON"
ENV_MAX_DISTANCE_KM = "PHLIGHT_MAX_DISTANCE_KM"

_MISSING = object()


def _positive(value: object) -> float | None:
    if not is_finite_number(value):
        return None
    number = float(value)
    return number if number > 0.0 else None


def _non_negative(value: object) -> float | None:
    if not is_finite_number(value):
        return None
    number = float(value)
    return number if number >= 0.0 else None


def _coordinate(value: object, limit: float) -> float | None:
    if not is_finite_number(value):
        return None
    number = float(value)
    if not -limit <= number <= limit:
        return None
    return number


def _env_number(
    environ: Mapping[str, str], name: str, limit_type: str
) -> tuple[float | None, bool]:
    """Parse a numeric environment variable.

    Returns ``(value, present)``. ``value`` is ``None`` when the variable is
    present but not a usable number.
    """

    if name not in environ:
        return None, False
    raw = environ[name]
    if not isinstance(raw, str):
        return None, True
    try:
        number = float(raw.strip())
    except ValueError:
        return None, True
    if limit_type == "coordinate_lat":
        return (_coordinate(number, 90.0), True)
    if limit_type == "coordinate_lon":
        return (_coordinate(number, 180.0), True)
    if limit_type == "positive":
        return (_positive(number), True)
    return (number if is_finite_number(number) else None, True)


def _resolve_coordinate(
    environ: Mapping[str, str],
    env_name: str,
    limit_type: str,
    limit: float,
    raw: object,
    problem: str,
    problems: list[str],
) -> float | None:
    """Resolve one home coordinate from the environment, then the mapping.

    Contract §13.2: a valid environment value overrides the mapping without a
    problem code, while an invalid environment value records that setting's code
    exactly once and *falls back* to the mapping value when the mapping value is
    itself a valid coordinate. Only when neither source yields a usable number
    does the coordinate end up unresolvable (``None``), which leaves the home
    unusable. Falling back instead of discarding the home is what makes a typo
    in ``PHLIGHT_HOME_LAT`` a diagnostic rather than a silent loss of the
    configured position.
    """

    env_value, present = _env_number(environ, env_name, limit_type)
    if env_value is not None:
        return env_value
    fallback = (
        _coordinate(raw, limit) if raw is not _MISSING and raw is not None else None
    )
    if present or fallback is None:
        problems.append(problem)
    return fallback


def load_config(
    mapping: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[SelectionConfig, tuple[str, ...]]:
    """Build a :class:`SelectionConfig` from a parsed config mapping.

    Returns ``(config, problems)``. ``problems`` is empty when everything was
    usable. A bad setting keeps its default; a bad home block yields
    ``home=None``. An invalid environment value records its problem code and
    falls back to that setting's valid mapping value, or to the default when the
    mapping value is unusable too (contract §13.2).
    """

    environ = os.environ if environ is None else environ
    problems: list[str] = []

    if not isinstance(mapping, Mapping):
        problems_tuple = ("config_not_mapping",)
        return SelectionConfig(problems=problems_tuple), problems_tuple

    # --- home -------------------------------------------------------------
    home_block = mapping.get("home", _MISSING)
    home_lat: object = _MISSING
    home_lon: object = _MISSING
    home_configured = False
    home_usable = True

    if isinstance(home_block, Mapping):
        home_configured = True
        home_lat = home_block.get("lat", _MISSING)
        home_lon = home_block.get("lon", _MISSING)
    elif home_block is not _MISSING and home_block is not None:
        home_configured = True
        problems.append("home_invalid")
        home_usable = False

    if (ENV_HOME_LAT in environ) or (ENV_HOME_LON in environ):
        home_configured = True

    if home_configured and home_usable:
        # Each coordinate is resolved independently: environment first, then the
        # structured mapping as the §13.2 fallback for an invalid environment
        # value, then "absent" (which leaves the home unusable).
        resolved_lat = _resolve_coordinate(
            environ,
            ENV_HOME_LAT,
            "coordinate_lat",
            90.0,
            home_lat,
            "home_lat_invalid",
            problems,
        )
        resolved_lon = _resolve_coordinate(
            environ,
            ENV_HOME_LON,
            "coordinate_lon",
            180.0,
            home_lon,
            "home_lon_invalid",
            problems,
        )
        if resolved_lat is None or resolved_lon is None:
            home_usable = False
        else:
            home_lat = resolved_lat
            home_lon = resolved_lon

    home: HomeLocation | None = None
    if home_usable and home_lat is not _MISSING and home_lon is not _MISSING:
        home = HomeLocation(float(home_lat), float(home_lon))  # type: ignore[arg-type]

    # --- selection block --------------------------------------------------
    selection_block = mapping.get("selection", _MISSING)
    selection: Mapping[str, Any]
    if isinstance(selection_block, Mapping):
        selection = selection_block
    else:
        selection = {}
        if selection_block is not _MISSING and selection_block is not None:
            problems.append("selection_invalid")

    env_distance, present = _env_number(environ, ENV_MAX_DISTANCE_KM, "positive")
    if present:
        if env_distance is not None:
            max_distance_km: float | None = env_distance
        else:
            problems.append("max_distance_invalid")
            raw_distance = selection.get("max_distance_km", _MISSING)
            max_distance_km = (
                None if raw_distance is _MISSING else _positive(raw_distance)
            )
    else:
        max_distance_km = _read_positive(
            selection, "max_distance_km", "max_distance_invalid", problems
        )

    max_position_age_s = _read_non_negative(
        selection, "max_position_age_s", "max_position_age_invalid", problems
    )
    max_message_age_s = _read_non_negative(
        selection, "max_message_age_s", "max_message_age_invalid", problems
    )
    max_snapshot_age_s = _read_non_negative(
        selection, "max_snapshot_age_s", "max_snapshot_age_invalid", problems
    )

    ignore_ground = selection.get("ignore_ground", _MISSING)
    if ignore_ground is _MISSING:
        ignore_ground_value = True
    elif isinstance(ignore_ground, bool):
        ignore_ground_value = ignore_ground
    else:
        problems.append("ignore_ground_invalid")
        ignore_ground_value = True

    defaults = SelectionConfig()
    config = SelectionConfig(
        home=home,
        max_distance_km=(
            defaults.max_distance_km if max_distance_km is None else max_distance_km
        ),
        max_position_age_s=(
            defaults.max_position_age_s
            if max_position_age_s is None
            else max_position_age_s
        ),
        max_message_age_s=(
            defaults.max_message_age_s
            if max_message_age_s is None
            else max_message_age_s
        ),
        max_snapshot_age_s=(
            defaults.max_snapshot_age_s
            if max_snapshot_age_s is None
            else max_snapshot_age_s
        ),
        ignore_ground=ignore_ground_value,
        problems=tuple(problems),
    )
    return config, tuple(problems)


def _read_positive(
    selection: Mapping[str, Any], key: str, problem: str, problems: list[str]
) -> float | None:
    value = selection.get(key, _MISSING)
    if value is _MISSING:
        return None
    parsed = _positive(value)
    if parsed is None:
        problems.append(problem)
    return parsed


def _read_non_negative(
    selection: Mapping[str, Any], key: str, problem: str, problems: list[str]
) -> float | None:
    value = selection.get(key, _MISSING)
    if value is _MISSING:
        return None
    parsed = _non_negative(value)
    if parsed is None:
        problems.append(problem)
    return parsed


def load_source_path(
    mapping: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Resolve the decoder JSON path, with the same precedence as ``load_config``.

    Additive helper for the future CLI: ``SelectionConfig`` deliberately does not
    carry the source path, so the path is resolved here and passed separately to
    :func:`phlight.aircraft.select_from_file`.
    """

    environ = os.environ if environ is None else environ
    problems: list[str] = []
    path = DEFAULT_SOURCE_PATH

    raw_cfg: object = _MISSING
    if isinstance(mapping, Mapping):
        source_block = mapping.get("source", _MISSING)
        if isinstance(source_block, Mapping):
            raw_cfg = source_block.get("aircraft_json", _MISSING)
        elif source_block is not _MISSING and source_block is not None:
            problems.append("source_invalid")

    if ENV_SOURCE_PATH in environ:
        raw_env = environ[ENV_SOURCE_PATH]
        if isinstance(raw_env, str) and raw_env.strip():
            path = raw_env
        else:
            problems.append("source_path_invalid")
            if isinstance(raw_cfg, str) and raw_cfg.strip():
                path = raw_cfg
    elif raw_cfg is not _MISSING:
        if isinstance(raw_cfg, str) and raw_cfg.strip():
            path = raw_cfg
        else:
            problems.append("source_path_invalid")

    return path, tuple(problems)