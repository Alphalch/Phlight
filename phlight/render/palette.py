"""Colour palettes.

A palette is a named set of RGB roles. The renderer only ever paints with
colours drawn from the palette, which keeps output representable on a limited
colour e-paper panel and makes the "only palette colours on the canvas"
guarantee testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

__all__ = ["Palette", "PALETTES", "palette_by_name", "ROLES"]

RGB = tuple[int, int, int]

#: Roles every palette must define.
ROLES = (
    "paper",       # background of the caption panel and the fleet strip
    "ink",         # primary text and aircraft fill
    "sky_top",     # top of the dithered sky gradient
    "sky_bottom",  # bottom of the dithered sky gradient
    "accent",      # aircraft outline, sun, empty-sky headline
    "accent_alt",  # secondary marks such as motion ticks and rules
    "muted",       # secondary text and separators
)


@dataclass(frozen=True)
class Palette:
    name: str
    colors: Mapping[str, RGB]
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "colors", MappingProxyType(dict(self.colors)))
        missing = [role for role in ROLES if role not in self.colors]
        if missing:
            raise ValueError(f"palette {self.name!r} is missing roles: {', '.join(missing)}")

    def __getitem__(self, role: str) -> RGB:
        return self.colors[role]

    @property
    def inks(self) -> tuple[RGB, ...]:
        """Distinct colours in the palette, in role order."""
        seen: list[RGB] = []
        for role in (*ROLES, *self.colors):
            colour = self.colors[role]
            if colour not in seen:
                seen.append(colour)
        return tuple(seen)


PALETTES: dict[str, Palette] = {
    "ink": Palette(
        name="ink",
        description="monochrome, for single-ink or grayscale panels",
        colors={
            "paper": (255, 255, 255),
            "ink": (17, 17, 17),
            "sky_top": (198, 202, 206),
            "sky_bottom": (255, 255, 255),
            "accent": (17, 17, 17),
            "accent_alt": (122, 122, 122),
            "muted": (122, 122, 122),
        },
    ),
    "spectra6": Palette(
        name="spectra6",
        description="six-ink limited set typical of 7-colour e-paper, as an idealised reference",
        colors={
            "paper": (255, 255, 255),
            "ink": (0, 0, 0),
            "sky_top": (43, 74, 145),
            "sky_bottom": (255, 255, 255),
            "accent": (196, 32, 28),
            "accent_alt": (232, 191, 42),
            "muted": (74, 114, 78),
        },
    ),
    "dusk": Palette(
        name="dusk",
        description="warm evening sky",
        colors={
            "paper": (247, 240, 229),
            "ink": (28, 26, 38),
            "sky_top": (46, 34, 78),
            "sky_bottom": (205, 118, 88),
            "accent": (226, 128, 62),
            "accent_alt": (120, 158, 190),
            "muted": (116, 104, 100),
        },
    ),
}


def palette_by_name(name: str) -> Palette:
    """Resolve a preset name, case-insensitively."""
    key = str(name).strip().lower()
    try:
        return PALETTES[key]
    except KeyError:
        choices = ", ".join(sorted(PALETTES))
        raise ValueError(f"unknown palette {name!r}; choose from: {choices}") from None