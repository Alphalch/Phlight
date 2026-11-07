"""Render configuration: canvas size, palette, and copy shown on the portrait."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .palette import Palette, palette_by_name

__all__ = ["RenderConfig", "MIN_CANVAS_PX"]

#: Smallest canvas the layout is willing to draw; below this text and the hero
#: silhouette collide. Nothing here assumes a particular panel.
MIN_CANVAS_PX = 160


@dataclass(frozen=True)
class RenderConfig:
    """Everything a caller can tune without editing the renderer.

    Dimensions are in pixels and are always honoured exactly, so the output can
    be matched to whatever panel (or preview size) is in use later. The default
    480x800 is a portrait preview size, not a selected panel.
    """

    width: int = 480
    height: int = 800
    palette: Palette | str = "ink"
    max_fleet: int = 3
    empty_sky_headline: str = "NOTHING OVERHEAD"
    empty_sky_detail: str = "CLEAR SKY - NO AIRCRAFT IN RANGE"
    force_empty_sky: bool = False
    show_caption: bool = True
    font_path: str | None = None
    #: Reference epoch seconds used to judge snapshot age. ``None`` means "no
    #: reference": the renderer never reads the wall clock, so output stays
    #: reproducible. A caller that knows the current time (the refresh loop)
    #: passes it in and gets explicit stale marking.
    now: float | None = None
    stale_after_seconds: float = 300.0

    def __post_init__(self) -> None:
        for label, value in (("width", self.width), ("height", self.height)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"canvas {label} must be an integer, got {value!r}")
        if self.width < MIN_CANVAS_PX or self.height < MIN_CANVAS_PX:
            raise ValueError(
                f"canvas must be at least {MIN_CANVAS_PX}px on each side, "
                f"got {self.width}x{self.height}"
            )
        if self.max_fleet < 0:
            raise ValueError(f"max_fleet must be zero or more, got {self.max_fleet}")

        palette = self.palette
        if isinstance(palette, str):
            palette = palette_by_name(palette)
        elif not isinstance(palette, Palette):
            raise ValueError(f"palette must be a Palette or preset name, got {palette!r}")
        object.__setattr__(self, "palette", palette)

        if self.font_path is not None and not Path(self.font_path).exists():
            raise ValueError(f"font_path does not exist: {self.font_path}")