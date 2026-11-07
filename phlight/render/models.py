"""Local aircraft data model used by the portrait renderer.

The model is deliberately storage-agnostic: the ADS-B ingest stage writes a
JSON document, the renderer reads it. Nothing here contacts a network, a vendor
service, or a database, so rendering is reproducible from a recorded file.

Document shape (all keys optional except ``aircraft`` entries' ``hex``)::

    {
      "captured_at": 1762500000,        # epoch seconds, UTC
      "source": "dump1090",
      "home": {"lat": 22.3, "lon": 114.1, "label": "home"},
      "aircraft": [
        {"hex": "780a1b", "callsign": "CPA715", "type_code": "B738",
         "altitude_ft": 11250, "distance_km": 4.2, "bearing_deg": 38,
         "track_deg": 52, "ground_speed_kt": 287, "seen_at": 1762499994}
      ]
    }
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = ["Aircraft", "AircraftSnapshot", "SnapshotError", "load_snapshot"]

_HEX_RE = re.compile(r"^~?[0-9a-fA-F]{6}$")

_STRING_FIELDS = ("callsign", "registration", "type_code", "type_name", "operator")
_FLOAT_FIELDS = ("distance_km", "bearing_deg", "track_deg", "ground_speed_kt", "seen_at")


class SnapshotError(ValueError):
    """Raised when a snapshot document cannot be used at all."""


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            result = float(value)
        except (OverflowError, ValueError):
            return None
        return result if math.isfinite(result) else None
    if isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return None
        return result if math.isfinite(result) else None
    return None


def _snapshot_time(value: Any, issues: list[str]) -> float | None:
    if value is None:
        return None
    seconds = _number(value)
    if seconds is None:
        issues.append("captured_at is not a number; timestamps will be omitted")
    return seconds


@dataclass(frozen=True)
class Aircraft:
    """One aircraft report, as far as local reception could determine it.

    Every field except ``hex`` may be missing: an SDR hears an identity and a
    position, not a tail number or an operator.
    """

    hex: str
    callsign: str | None = None
    registration: str | None = None
    type_code: str | None = None
    type_name: str | None = None
    operator: str | None = None
    altitude_ft: int | None = None
    distance_km: float | None = None
    bearing_deg: float | None = None
    track_deg: float | None = None
    ground_speed_kt: float | None = None
    seen_at: float | None = None

    @property
    def label(self) -> str:
        """Best short identifier for display: callsign, then registration, then hex."""
        return self.callsign or self.registration or self.hex.upper()

    @property
    def type_label(self) -> str:
        return self.type_name or self.type_code or "Unknown type"

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        issues: list[str] | None = None,
        context: str = "aircraft",
    ) -> "Aircraft | None":
        """Build an Aircraft, or return None when the entry has no usable identity."""
        problems = issues if issues is not None else []
        raw_hex = data.get("hex")
        if not isinstance(raw_hex, str) or not _HEX_RE.match(raw_hex.strip()):
            problems.append(f"{context}: dropped, missing or invalid 6-character hex")
            return None
        hex_code = raw_hex.strip().lower()

        values: dict[str, Any] = {"hex": hex_code}
        string_fallbacks = {
            "callsign": ("callsign", "flight"),
            "registration": ("registration", "r"),
            "type_code": ("type_code", "t"),
            "type_name": ("type_name",),
            "operator": ("operator",),
        }
        for field_name, keys in string_fallbacks.items():
            raw_str = next((data.get(k) for k in keys if data.get(k) is not None), None)
            values[field_name] = _clean_string(raw_str)

        altitude = data.get("altitude_ft")
        if altitude is None and "alt_baro" in data:
            alt_baro = data.get("alt_baro")
            altitude = None if alt_baro == "ground" else alt_baro
        if altitude is None:
            values["altitude_ft"] = None
        else:
            number = _number(altitude)
            if number is None:
                problems.append(f"{context} {hex_code}: altitude_ft is not a number ({altitude!r})")
            values["altitude_ft"] = None if number is None else int(round(number))

        float_fallbacks = {
            "distance_km": ("distance_km",),
            "bearing_deg": ("bearing_deg",),
            "track_deg": ("track_deg", "track"),
            "ground_speed_kt": ("ground_speed_kt", "gs"),
            "seen_at": ("seen_at",),
        }
        for field_name, keys in float_fallbacks.items():
            raw = next((data.get(k) for k in keys if k in data), None)
            number = _number(raw)
            if raw is not None and number is None:
                problems.append(f"{context} {hex_code}: {field_name} is not a number ({raw!r})")
            values[field_name] = number

        if values["distance_km"] is None and "distance_m" in data:
            dist_m = _number(data.get("distance_m"))
            if dist_m is not None:
                values["distance_km"] = dist_m / 1000.0

        return cls(**values)


@dataclass(frozen=True)
class AircraftSnapshot:
    """A point-in-time view of what the receiver heard."""

    captured_at: float | None = None
    aircraft: tuple[Aircraft, ...] = ()
    home: Mapping[str, Any] | None = None
    source: str | None = None
    dropped: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.aircraft

    def by_distance(self) -> tuple[Aircraft, ...]:
        """Closest first; reports without a distance sort last, ties broken by hex."""
        return tuple(
            sorted(
                self.aircraft,
                key=lambda a: (a.distance_km is None, a.distance_km or 0.0, a.hex),
            )
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AircraftSnapshot":
        if not isinstance(data, Mapping):
            raise SnapshotError("snapshot document must be a JSON object")

        issues: list[str] = []
        dropped: list[str] = []
        raw_time = (
            data.get("captured_at")
            if "captured_at" in data
            else (data.get("now") if "now" in data else data.get("snapshot_time"))
        )
        captured_at = _snapshot_time(raw_time, issues)

        raw_aircraft = data.get("aircraft", [])
        if raw_aircraft is None:
            raw_aircraft = []
        elif isinstance(raw_aircraft, Mapping):
            raw_aircraft = [raw_aircraft]
        if not isinstance(raw_aircraft, list):
            issues.append("aircraft is not a list; no aircraft loaded")
            raw_aircraft = []

        aircraft: list[Aircraft] = []
        for index, entry in enumerate(raw_aircraft):
            if not isinstance(entry, Mapping):
                dropped.append(f"entry {index}: dropped, not a JSON object")
                continue
            parsed = Aircraft.from_dict(entry, issues, context=f"entry {index}")
            if parsed is None:
                dropped.append(issues[-1])
            else:
                aircraft.append(parsed)

        home = data.get("home")
        return cls(
            captured_at=captured_at,
            aircraft=tuple(aircraft),
            home=home if isinstance(home, Mapping) else None,
            source=_clean_string(data.get("source")),
            dropped=tuple(dropped),
            issues=tuple(issues),
        )


def load_snapshot(path: str | Path) -> AircraftSnapshot:
    """Read a local snapshot document.

    Raises SnapshotError when the file is unreadable or is not a JSON object;
    damaged individual aircraft are dropped and reported instead.
    """
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"cannot read snapshot {file_path}: {exc.strerror or exc}") from exc

    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SnapshotError(f"{file_path} is not valid JSON: {exc.msg}") from exc

    if not isinstance(document, Mapping):
        raise SnapshotError(f"{file_path} must contain a JSON object")

    return AircraftSnapshot.from_dict(document)