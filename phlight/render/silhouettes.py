"""Original aircraft plan-view geometry.

These silhouettes are not photographs, tracings, or licensed art: each one is
generated from a small parameter set (fuselage width, wing sweep, span, tail
size) into normalised polygons that live in a 0..1 box, nose at y=0. They are
authored for Phlight and covered by the repository licence, so nothing here
derives from FlightPortrait's proprietary artwork or from third-party icon sets.

Because the geometry is parametric, unknown or unusual types still render: they
fall back to a generic swept-wing symbol rather than being dropped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

__all__ = [
    "Part",
    "Symbol",
    "SYMBOLS",
    "class_for_type",
    "symbol_for",
    "TYPE_CLASSES",
]

Point = tuple[float, float]

ORIGINAL = "original geometry authored for Phlight (MIT licensed with this repository)"


@dataclass(frozen=True)
class Part:
    """One closed polygon of a plan-view silhouette, in normalised coordinates."""

    points: tuple[Point, ...]
    label: str = ""


@dataclass(frozen=True)
class Symbol:
    size_class: str
    parts: tuple[Part, ...]
    attribution: str = ORIGINAL

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [x for part in self.parts for x, _ in part.points]
        ys = [y for part in self.parts for _, y in part.points]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def aspect(self) -> float:
        """width / height of the drawn silhouette."""
        min_x, min_y, max_x, max_y = self.bbox
        return (max_x - min_x) / (max_y - min_y)


@dataclass(frozen=True)
class _Params:
    fuse_width: float
    wing_span: float
    wing_root_y: float
    wing_chord_root: float
    wing_tip_y: float
    wing_chord_tip: float
    tail_span: float
    tail_y: float
    tail_chord: float
    engines: int = 0
    engine_x: float = 0.0
    engine_r: float = 0.0


def _mirror(points: Iterable[Point]) -> tuple[Point, ...]:
    return tuple((1.0 - x, y) for x, y in points)


def _taper_fuselage(width: float, nose_y: float, tail_y: float) -> Part:
    """Rounded nose, straight cabin section, tapered tail cone."""
    cx = 0.5
    half = width / 2.0
    length = tail_y - nose_y
    nose_r = min(half * 0.60, length * 0.06)
    shoulder = nose_y + 0.10 * length
    aft = tail_y - 0.16 * length
    points = (
        (cx - half * 0.62, nose_y + nose_r * 0.60),
        (cx - half * 0.28, nose_y + nose_r * 0.12),
        (cx, nose_y),
        (cx + half * 0.28, nose_y + nose_r * 0.12),
        (cx + half * 0.62, nose_y + nose_r * 0.60),
        (cx + half, shoulder),
        (cx + half * 0.95, aft),
        (cx + half * 0.30, tail_y - 0.01 * length),
        (cx, tail_y),
        (cx - half * 0.30, tail_y - 0.01 * length),
        (cx - half * 0.95, aft),
        (cx - half, shoulder),
    )
    return Part(points, "fuselage")


def _panel(span: float, root_y: float, chord_root: float, tip_y: float, chord_tip: float) -> tuple[Part, Part]:
    right = (
        (0.5, root_y),
        (0.5 + span, tip_y),
        (0.5 + span, tip_y + chord_tip),
        (0.5, root_y + chord_root),
    )
    return Part(right, "wing"), Part(_mirror(right), "wing")


def _disc(cx: float, cy: float, radius: float, label: str, segments: int = 18) -> Part:
    points = tuple(
        (
            cx + radius * math.cos(2.0 * math.pi * i / segments),
            cy + radius * math.sin(2.0 * math.pi * i / segments),
        )
        for i in range(segments)
    )
    return Part(points, label)


def _fixed_wing(params: _Params) -> tuple[Part, ...]:
    parts: list[Part] = [_taper_fuselage(params.fuse_width, 0.0, 0.97)]
    parts.extend(_panel(params.wing_span, params.wing_root_y, params.wing_chord_root, params.wing_tip_y, params.wing_chord_tip))
    parts.extend(
        _panel(
            params.tail_span,
            params.tail_y,
            params.tail_chord,
            params.tail_y + 0.02,
            params.tail_chord * 0.55,
        )
    )
    if params.engines:
        # Nacelles must sit on the wing, not float ahead of it: follow the
        # leading edge at the engine's spanwise station.
        station = params.engine_x / params.wing_span
        leading_edge = params.wing_root_y + (params.wing_tip_y - params.wing_root_y) * station
        chord = params.wing_chord_root + (params.wing_chord_tip - params.wing_chord_root) * station
        for side in (-1.0, 1.0):
            parts.append(
                _disc(
                    0.5 + side * params.engine_x,
                    leading_edge + chord * 0.30,
                    params.engine_r,
                    "engine",
                    14,
                )
            )
    return tuple(parts)


def _helicopter() -> tuple[Part, ...]:
    return (
        _taper_fuselage(0.140, 0.22, 0.68),
        Part(((0.455, 0.60), (0.462, 0.955), (0.50, 0.975), (0.538, 0.955), (0.545, 0.60)), "tail boom"),
        Part(((0.5, 0.90), (0.558, 0.958), (0.5, 0.988), (0.442, 0.958)), "tail fin"),
        _disc(0.5, 0.398, 0.392, "main rotor", 28),
        _disc(0.5, 0.935, 0.050, "tail rotor", 12),
    )


SPECS: Mapping[str, _Params] = {
    "narrowbody": _Params(0.105, 0.470, 0.400, 0.100, 0.500, 0.030, 0.185, 0.870, 0.050, 2, 0.250, 0.030),
    "widebody": _Params(0.135, 0.495, 0.380, 0.115, 0.485, 0.045, 0.205, 0.850, 0.055, 2, 0.270, 0.036),
    "regional": _Params(0.085, 0.440, 0.420, 0.085, 0.475, 0.025, 0.165, 0.880, 0.045, 2, 0.220, 0.024),
    "turboprop": _Params(0.090, 0.450, 0.420, 0.095, 0.435, 0.070, 0.175, 0.880, 0.050, 2, 0.200, 0.026),
    "general_aviation": _Params(0.090, 0.420, 0.280, 0.075, 0.300, 0.060, 0.170, 0.840, 0.045),
    "generic": _Params(0.095, 0.420, 0.410, 0.090, 0.490, 0.030, 0.165, 0.870, 0.045, 2, 0.220, 0.026),
}

SYMBOLS: dict[str, Symbol] = {
    name: Symbol(name, _fixed_wing(params)) for name, params in SPECS.items()
}
SYMBOLS["helicopter"] = Symbol("helicopter", _helicopter())

#: ICAO type designators mapped to a drawing class. Unknown codes fall back to
#: "generic", which is intentional: local reception often cannot resolve a type.
TYPE_CLASSES: Mapping[str, str] = {
    "A19N": "narrowbody", "A20N": "narrowbody", "A21N": "narrowbody",
    "A318": "narrowbody", "A319": "narrowbody", "A320": "narrowbody",
    "A321": "narrowbody", "B37M": "narrowbody", "B38M": "narrowbody",
    "B39M": "narrowbody", "B733": "narrowbody", "B735": "narrowbody",
    "B736": "narrowbody", "B737": "narrowbody", "B738": "narrowbody",
    "B739": "narrowbody", "B752": "narrowbody", "MD82": "narrowbody",
    "A332": "widebody", "A333": "widebody", "A339": "widebody",
    "A342": "widebody", "A343": "widebody", "A345": "widebody",
    "A346": "widebody", "A359": "widebody", "A35K": "widebody",
    "A388": "widebody", "B741": "widebody", "B744": "widebody",
    "B748": "widebody", "B762": "widebody", "B763": "widebody",
    "B772": "widebody", "B773": "widebody", "B77W": "widebody",
    "B788": "widebody", "B789": "widebody", "B78X": "widebody",
    "CRJ2": "regional", "CRJ7": "regional", "CRJ9": "regional",
    "E170": "regional", "E175": "regional", "E190": "regional",
    "E195": "regional", "E290": "regional", "E295": "regional",
    "SU95": "regional",
    "AT43": "turboprop", "AT72": "turboprop", "AT75": "turboprop",
    "AT76": "turboprop", "DH8A": "turboprop", "DH8B": "turboprop",
    "DH8C": "turboprop", "DH8D": "turboprop", "D228": "turboprop",
    "D328": "turboprop", "BE20": "turboprop", "PC12": "turboprop",
    "TBM9": "turboprop", "C208": "turboprop",
    "C150": "general_aviation", "C152": "general_aviation",
    "C172": "general_aviation", "C182": "general_aviation",
    "C206": "general_aviation", "C210": "general_aviation",
    "DA40": "general_aviation", "DA42": "general_aviation",
    "M20P": "general_aviation", "PA28": "general_aviation",
    "PA32": "general_aviation", "SR22": "general_aviation",
    "BE36": "general_aviation", "RV7A": "general_aviation",
    "EC30": "helicopter", "EC35": "helicopter", "EC45": "helicopter",
    "H125": "helicopter", "H135": "helicopter", "H145": "helicopter",
    "H60": "helicopter", "R22": "helicopter", "R44": "helicopter",
    "R66": "helicopter", "AW139": "helicopter", "B06": "helicopter",
    "B407": "helicopter", "B429": "helicopter",
}


def class_for_type(type_code: str | None) -> str:
    """Map an ICAO type designator to a drawing class (never raises)."""
    if not isinstance(type_code, str):
        return "generic"
    code = type_code.strip().upper()
    return TYPE_CLASSES.get(code, "generic")


def symbol_for(size_class: str) -> Symbol:
    return SYMBOLS.get(size_class, SYMBOLS["generic"])