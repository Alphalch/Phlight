"""Package init: the renderer's public surface.

Downstream code (refresh loop, preview tools, tests) should import from here::

    from phlight.render import load_snapshot, RenderConfig, render_snapshot
    result = render_snapshot(load_snapshot("snapshot.json"), RenderConfig(width=480, height=800))
    result.image.save("portrait.png")
"""

from __future__ import annotations

from .config import MIN_CANVAS_PX, RenderConfig
from .models import Aircraft, AircraftSnapshot, SnapshotError, load_snapshot
from .palette import PALETTES, ROLES, Palette, palette_by_name
from .renderer import RenderResult, render_snapshot, render_to_path
from . import silhouettes

__all__ = [
    "Aircraft",
    "AircraftSnapshot",
    "MIN_CANVAS_PX",
    "PALETTES",
    "Palette",
    "ROLES",
    "RenderConfig",
    "RenderResult",
    "SnapshotError",
    "load_snapshot",
    "palette_by_name",
    "render_snapshot",
    "render_to_path",
    "silhouettes",
]

__version__ = "0.1.0"