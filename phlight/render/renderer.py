"""Compose the aircraft portrait.

Design notes that matter downstream:

* The renderer is a pure function of (snapshot, config). It never reads the wall
  clock, the network, or a panel driver, so the same inputs always produce the
  same pixels - that is what makes the tests meaningful.
* Every pixel is painted from the configured palette, so output stays inside a
  limited-ink e-paper gamut and can be checked mechanically.
* Three explicit states exist: ``current``, ``empty`` (nothing heard, or forced)
  and ``stale`` (aircraft present but the snapshot is older than the caller's
  threshold). Nothing here assumes a physical panel has been chosen or tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont

from . import silhouettes
from .config import RenderConfig
from .models import Aircraft, AircraftSnapshot
from .palette import Palette, palette_by_name

__all__ = ["RenderResult", "render_snapshot", "render_to_path"]

#: Ordered 8x8 Bayer matrix used for the sky gradient. Ordered dithering keeps
#: the gradient reproducible and limits it to two palette colours at once.
BAYER8: tuple[tuple[int, ...], ...] = (
    (0, 32, 8, 40, 2, 34, 10, 42),
    (48, 16, 56, 24, 50, 18, 58, 26),
    (12, 44, 4, 36, 14, 46, 6, 38),
    (60, 28, 52, 20, 62, 30, 54, 22),
    (3, 35, 11, 43, 1, 33, 9, 41),
    (51, 19, 59, 27, 49, 17, 57, 25),
    (15, 47, 7, 39, 13, 45, 5, 37),
    (63, 31, 55, 23, 61, 29, 53, 21),
)

#: How much of the canvas width the hero silhouette spans, per drawing class.
HERO_WIDTH_FRACTION = {
    "widebody": 0.80,
    "narrowbody": 0.68,
    "regional": 0.62,
    "turboprop": 0.66,
    "general_aviation": 0.36,
    "helicopter": 0.58,
    "generic": 0.62,
}

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class RenderResult:
    image: Image.Image
    status: str  # "current" | "empty" | "stale"
    empty_sky: bool
    stale: bool
    rendered_ids: tuple[str, ...]
    age_seconds: float | None
    config: RenderConfig
    #: y coordinate where sky meets caption panel; useful for downstream
    #: drawing or for asserting layout when a panel is finally chosen.
    horizon_y: int = 0


@dataclass(frozen=True)
class _Layout:
    width: int
    height: int
    pad: int
    footer_h: int
    sky_bottom_y: int
    panel_top: int
    fleet_top: int
    panel_bottom: int

    @classmethod
    def for_config(cls, config: RenderConfig) -> "_Layout":
        width, height = config.width, config.height
        pad = max(6, round(min(width, height) * 0.055))
        footer_h = max(10, round(height * 0.028)) if config.show_caption else 0
        sky_bottom_y = round(height * 0.50)
        panel_top = sky_bottom_y
        fleet_top = round(height * 0.780)
        panel_bottom = height - footer_h
        if fleet_top >= panel_bottom:
            fleet_top = max(panel_top + 1, panel_bottom - max(1, panel_bottom // 6))
        return cls(
            width=width,
            height=height,
            pad=pad,
            footer_h=footer_h,
            sky_bottom_y=sky_bottom_y,
            panel_top=panel_top,
            fleet_top=fleet_top,
            panel_bottom=panel_bottom,
        )


# --------------------------------------------------------------------------- #
# small drawing helpers
# --------------------------------------------------------------------------- #


def _font(size: int, font_path: str | None) -> Any:
    pixels = max(6, int(size))
    if font_path:
        return ImageFont.truetype(font_path, pixels)
    try:
        return ImageFont.load_default(size=pixels)
    except TypeError:  # very old Pillow: bitmap fallback, still deterministic
        return ImageFont.load_default()


def _text_mask(text: str, font) -> Image.Image:
    """Rasterise text to a 1-bit mask so no anti-aliased tints leak in."""
    left, top, right, bottom = font.getbbox(text)
    width = max(1, right - left)
    height = max(1, bottom - top)
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).text((-left, -top), text, font=font, fill=255)
    return mask.point([0] * 128 + [255] * 128)


def _text_width(text: str, font) -> int:
    left, _, right, _ = font.getbbox(text)
    return right - left


def _fit_font(
    text: str,
    size: int,
    max_width: int,
    font_path: str | None,
    min_size: int = 7,
) -> ImageFont.FreeTypeFont:
    if max_width <= 0:
        return _font(min_size, font_path)
    candidate = max(min_size, int(size))
    font = _font(candidate, font_path)
    while candidate > min_size and _text_width(text, font) > max_width:
        candidate -= 1
        font = _font(candidate, font_path)
    return font


def _paint_text(
    canvas: Image.Image,
    xy: tuple[float, float],
    text: str,
    font,
    colour: tuple[int, int, int],
    align: str = "left",
) -> tuple[int, int]:
    """Paste a crisp text mask onto the canvas; returns its (width, height)."""
    if not text:
        return 0, 0
    mask = _text_mask(text, font)
    x, y = int(xy[0]), int(xy[1])
    if align == "right":
        x -= mask.width
    elif align == "center":
        x -= mask.width // 2
    canvas.paste(colour, (int(x), int(y)), mask)
    return mask.width, mask.height


def _paint_polygon(canvas: Image.Image, points: Sequence[tuple[float, float]], colour) -> None:
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).polygon(list(points), fill=255)
    canvas.paste(colour, (0, 0), mask)


# --------------------------------------------------------------------------- #
# background
# --------------------------------------------------------------------------- #


def _paint_sky(canvas: Image.Image, layout: _Layout, palette: Palette) -> None:
    top = palette["sky_top"]
    bottom = palette["sky_bottom"]
    height = layout.sky_bottom_y
    width = layout.width
    if height <= 0:
        return
    band = Image.new("RGB", (width, height))
    pixels: list[tuple[int, int, int]] = []
    span = max(1, height - 1)
    for y in range(height):
        ratio = y / span
        row = BAYER8[y % 8]
        for x in range(width):
            threshold = (row[x % 8] + 0.5) / 64.0
            pixels.append(top if ratio < threshold else bottom)
    band.putdata(pixels)
    canvas.paste(band, (0, 0))


def _paint_sun(canvas: Image.Image, layout: _Layout, palette: Palette) -> None:
    radius = max(4, round(min(layout.width, layout.sky_bottom_y) * 0.045))
    centre = (round(layout.width * 0.74), round(layout.sky_bottom_y * 0.15))
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).ellipse(
        (centre[0] - radius, centre[1] - radius, centre[0] + radius, centre[1] + radius),
        fill=255,
    )
    canvas.paste(palette["accent"], (0, 0), mask)


def _paint_rule(
    canvas: Image.Image,
    layout: _Layout,
    palette: Palette,
    y: float,
    role: str = "muted",
) -> None:
    y = int(y)
    if not 0 <= y < canvas.height:
        return
    thickness = max(1, round(layout.width * 0.004))
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).rectangle((layout.pad, y, layout.width - layout.pad, y + thickness - 1), fill=255)
    canvas.paste(palette[role], (0, 0), mask)


# --------------------------------------------------------------------------- #
# aircraft
# --------------------------------------------------------------------------- #


def _silhouette_mask(symbol: silhouettes.Symbol, target_width: int) -> Image.Image:
    min_x, min_y, max_x, max_y = symbol.bbox
    width_units = max(1e-6, max_x - min_x)
    height_units = max(1e-6, max_y - min_y)
    width = max(8, int(target_width))
    height = max(8, round(width * height_units / width_units))
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    for part in symbol.parts:
        points = [
            (
                (x - min_x) / width_units * (width - 1),
                (y - min_y) / height_units * (height - 1),
            )
            for x, y in part.points
        ]
        draw.polygon(points, fill=255)
    return mask


def _paint_hero(
    canvas: Image.Image,
    aircraft: Aircraft,
    layout: _Layout,
    palette: Palette,
) -> tuple[int, int]:
    size_class = silhouettes.class_for_type(aircraft.type_code)
    symbol = silhouettes.symbol_for(size_class)
    fraction = HERO_WIDTH_FRACTION.get(size_class, 0.62)
    target_width = max(24, round(layout.width * fraction))
    mask = _silhouette_mask(symbol, target_width)

    # Keep the airframe comfortably inside the sky band, whatever the canvas
    # shape: 78% of the band leaves air around it and keeps it off the horizon.
    max_height = max(16, round(layout.sky_bottom_y * 0.78))
    if mask.height > max_height:
        scaled = max(12, round(target_width * max_height / mask.height))
        mask = _silhouette_mask(symbol, scaled)

    if aircraft.track_deg is not None:
        rotated = mask.rotate(
            -aircraft.track_deg, expand=True, resample=Image.Resampling.BILINEAR
        )
        # Re-binarise: smooth diagonal edges, still no anti-aliased tint that
        # would fall outside the palette.
        mask = rotated.point([0] * 128 + [255] * 128)

    centre = (layout.width // 2, round(layout.sky_bottom_y * 0.50))
    origin = (centre[0] - mask.width // 2, centre[1] - mask.height // 2)
    canvas.paste(palette["ink"], origin, mask)
    return centre


# --------------------------------------------------------------------------- #
# text formatting
# --------------------------------------------------------------------------- #


def _stamp(epoch: float | None) -> str:
    if epoch is None:
        return "TIME UNKNOWN"
    moment = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "UNKNOWN"
    total = int(max(0, round(seconds)))
    if total < 90:
        return f"{total} S"
    if total < 5400:
        return f"{total // 60} MIN"
    if total < 172_800:
        return f"{total // 3600} H"
    return f"{total // 86400} D"


def _format_altitude(altitude_ft: int | None) -> str:
    return "-- FT" if altitude_ft is None else f"{altitude_ft:,} FT"


def _format_distance(distance_km: float | None) -> str:
    return "-- KM" if distance_km is None else f"{distance_km:.1f} KM"


def _format_bearing(bearing_deg: float | None) -> str:
    if bearing_deg is None:
        return "--"
    normalised = bearing_deg % 360.0
    point = COMPASS[int((normalised + 22.5) % 360 // 45) % 8]
    return f"{int(round(normalised)) % 360:03d} {point}"


def _format_speed(speed_kt: float | None) -> str:
    return "-- KT" if speed_kt is None else f"{round(speed_kt):,} KT"


# --------------------------------------------------------------------------- #
# panels
# --------------------------------------------------------------------------- #


def _paint_caption(
    canvas: Image.Image,
    aircraft: Aircraft,
    layout: _Layout,
    palette: Palette,
    config: RenderConfig,
    age_seconds: float | None,
    stale: bool,
) -> None:
    band_height = max(1, layout.fleet_top - layout.panel_top)
    pad = layout.pad
    limit = layout.fleet_top - pad // 3
    x = pad
    max_width = layout.width - 2 * pad
    y = layout.panel_top + max(2, round(band_height * 0.07))

    if stale:
        bar_height = max(10, round(band_height * 0.19))
        mask = Image.new("L", canvas.size, 0)
        ImageDraw.Draw(mask).rectangle(
            (pad, y, layout.width - pad, y + bar_height), fill=255
        )
        canvas.paste(palette["accent"], (0, 0), mask)
        banner_font = _fit_font(
            f"STALE - LAST UPDATE {_format_age(age_seconds)} AGO",
            round(bar_height * 0.60),
            max_width - 2 * pad,
            config.font_path,
        )
        _paint_text(
            canvas,
            (x + pad // 2, y + max(1, (bar_height - banner_font.size) // 2)),
            f"STALE - LAST UPDATE {_format_age(age_seconds)} AGO",
            banner_font,
            palette["paper"],
        )
        y += bar_height + max(2, round(band_height * 0.05))

    call_sign = aircraft.label.upper()
    call_size = max(9, round(band_height * 0.34))
    call_font = _fit_font(call_sign, call_size, max_width, config.font_path)
    if y + call_font.size > limit:
        return
    _paint_text(canvas, (x, y), call_sign, call_font, palette["ink"])
    y += round(call_font.size * 1.18)

    type_line = aircraft.type_label.upper()
    if aircraft.operator:
        type_line = f"{type_line} - {aircraft.operator.upper()}"
    type_size = max(7, round(call_font.size * 0.32))
    type_font = _fit_font(type_line, type_size, max_width, config.font_path)
    if y + type_font.size <= limit:
        _paint_text(canvas, (x, y), type_line, type_font, palette["accent"])
        y += round(type_font.size * 1.30)

    # One row of four readings: it keeps the panel airy in portrait and still
    # fits when the canvas is small.
    stats = (
        ("ALTITUDE", _format_altitude(aircraft.altitude_ft)),
        ("DISTANCE", _format_distance(aircraft.distance_km)),
        ("BEARING", _format_bearing(aircraft.bearing_deg)),
        ("SPEED", _format_speed(aircraft.ground_speed_kt)),
    )
    label_size = max(6, round(call_font.size * 0.20))
    value_size = max(8, round(call_font.size * 0.30))
    label_font = _font(label_size, config.font_path)
    column_width = max_width // len(stats)
    row_height = round(label_size * 1.45) + round(value_size * 1.15)
    if y + row_height <= limit:
        for column, (label, value) in enumerate(stats):
            cell_x = x + column * column_width
            _paint_text(canvas, (cell_x, y), label, label_font, palette["muted"])
            value_font = _fit_font(
                value, value_size, column_width - max(2, pad // 3), config.font_path
            )
            _paint_text(
                canvas,
                (cell_x, y + round(label_size * 1.45)),
                value,
                value_font,
                palette["ink"],
            )
        y += row_height


def _paint_fleet(
    canvas: Image.Image,
    fleet: Sequence[Aircraft],
    layout: _Layout,
    palette: Palette,
    config: RenderConfig,
) -> tuple[Aircraft, ...]:
    if not fleet:
        return ()
    available = layout.panel_bottom - layout.fleet_top - layout.pad // 2
    if available < 18:
        return ()
    pad = layout.pad
    rule_y = layout.fleet_top - max(3, pad // 3)
    _paint_rule(canvas, layout, palette, rule_y, "muted")

    rows = min(len(fleet), max(1, config.max_fleet))
    row_height = max(28, available // rows)
    rows = max(1, min(rows, available // row_height))
    x = pad
    drawn: list[Aircraft] = []
    for index, aircraft in enumerate(fleet[:rows]):
        top = layout.fleet_top + index * row_height
        size_class = silhouettes.class_for_type(aircraft.type_code)
        symbol = silhouettes.symbol_for(size_class)
        width = max(12, round(layout.width * 0.12))
        mask = _silhouette_mask(symbol, width)
        if mask.height > row_height - 4:
            mask = _silhouette_mask(symbol, max(10, round(width * (row_height - 4) / mask.height)))
        icon_top = top + max(0, (row_height - mask.height) // 2)
        canvas.paste(palette["ink"], (x, icon_top), mask)

        label = aircraft.label.upper()
        detail = f"{_format_distance(aircraft.distance_km)}  {aircraft.type_label.upper()}"
        label_size = max(7, round(row_height * 0.34))
        detail_size = max(6, round(row_height * 0.24))
        label_x = x + mask.width + max(6, pad // 2)
        label_font = _fit_font(label, label_size, layout.width - label_x - pad, config.font_path)
        detail_font = _fit_font(detail, detail_size, layout.width - label_x - pad, config.font_path)
        text_y = top + max(0, (row_height - (label_font.size + detail_font.size)) // 2)
        if text_y + label_font.size < layout.panel_bottom:
            _paint_text(canvas, (label_x, text_y), label, label_font, palette["ink"])
            _paint_text(
                canvas,
                (label_x, text_y + round(label_font.size * 1.15)),
                detail,
                detail_font,
                palette["muted"],
            )
        drawn.append(aircraft)
    return tuple(drawn)


def _paint_empty_sky(
    canvas: Image.Image,
    layout: _Layout,
    palette: Palette,
    config: RenderConfig,
    snapshot: AircraftSnapshot,
) -> None:
    top = layout.sky_bottom_y + layout.pad
    bottom = layout.panel_bottom - layout.pad
    headline_font = _fit_font(
        config.empty_sky_headline.upper(),
        max(10, round((bottom - top) * 0.20)),
        layout.width - 2 * layout.pad,
        config.font_path,
    )
    detail_font = _fit_font(
        config.empty_sky_detail.upper(),
        max(7, round(headline_font.size * 0.40)),
        layout.width - 2 * layout.pad,
        config.font_path,
    )
    block = headline_font.size + round(headline_font.size * 0.55) + detail_font.size
    y = max(top, top + ((bottom - top) - block) // 2)
    _paint_text(
        canvas,
        (layout.width // 2, y),
        config.empty_sky_headline.upper(),
        headline_font,
        palette["accent"],
        align="center",
    )
    y += round(headline_font.size * 1.35)
    _paint_text(
        canvas,
        (layout.width // 2, y),
        config.empty_sky_detail.upper(),
        detail_font,
        palette["muted"],
        align="center",
    )
    rule_y = min(bottom, y + round(detail_font.size * 1.8))
    _paint_rule(canvas, layout, palette, rule_y, "muted")
    stamp = _stamp(snapshot.captured_at)
    stamp_font = _font(max(6, round(detail_font.size * 0.9)), config.font_path)
    _paint_text(
        canvas,
        (layout.width // 2, min(layout.panel_bottom - stamp_font.size - 2, rule_y + layout.pad // 2)),
        f"AS OF {stamp}",
        stamp_font,
        palette["muted"],
        align="center",
    )


def _paint_footer(
    canvas: Image.Image,
    layout: _Layout,
    palette: Palette,
    snapshot: AircraftSnapshot,
    config: RenderConfig,
) -> None:
    if layout.footer_h <= 0:
        return
    size = max(6, round(layout.footer_h * 0.52))
    font = _font(size, config.font_path)
    y = layout.panel_bottom + max(0, (layout.footer_h - font.size) // 2)
    left = f"CAPTURED {_stamp(snapshot.captured_at)}"
    _paint_text(canvas, (layout.pad, y), left, font, palette["muted"])
    mark_font = _font(size, config.font_path)
    _paint_text(
        canvas,
        (layout.width - layout.pad, y),
        "PHLIGHT",
        mark_font,
        palette["muted"],
        align="right",
    )


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #


def _age_seconds(snapshot: AircraftSnapshot, config: RenderConfig) -> float | None:
    if config.now is None or snapshot.captured_at is None:
        return None
    return float(config.now) - float(snapshot.captured_at)


def _select(
    snapshot: AircraftSnapshot, config: RenderConfig
) -> tuple[Aircraft | None, tuple[Aircraft, ...]]:
    ordered = snapshot.by_distance()
    if not ordered:
        return None, ()
    hero = ordered[0]
    fleet = ordered[1 : 1 + max(0, config.max_fleet)]
    return hero, tuple(fleet)


def render_snapshot(
    snapshot: AircraftSnapshot,
    config: RenderConfig | None = None,
) -> RenderResult:
    """Render one portrait. Pure: same snapshot + config gives identical pixels."""
    config = config or RenderConfig()
    palette = config.palette if isinstance(config.palette, Palette) else palette_by_name(config.palette)

    layout = _Layout.for_config(config)
    age = _age_seconds(snapshot, config)
    empty = config.force_empty_sky or snapshot.is_empty
    hero, fleet = (None, ()) if empty else _select(snapshot, config)
    stale = bool(hero is not None and age is not None and age > config.stale_after_seconds)

    canvas = Image.new("RGB", (layout.width, layout.height), palette["paper"])
    _paint_sky(canvas, layout, palette)
    _paint_sun(canvas, layout, palette)
    _paint_rule(canvas, layout, palette, layout.panel_top, "accent")

    if hero is None:
        _paint_empty_sky(canvas, layout, palette, config, snapshot)
        drawn_fleet: tuple[Aircraft, ...] = ()
    else:
        _paint_hero(canvas, hero, layout, palette)
        _paint_caption(canvas, hero, layout, palette, config, age, stale)
        drawn_fleet = _paint_fleet(canvas, fleet, layout, palette, config)

    if config.show_caption:
        _paint_footer(canvas, layout, palette, snapshot, config)

    rendered_ids: tuple[str, ...] = ()
    if hero is not None:
        rendered_ids = (hero.hex, *(a.hex for a in drawn_fleet))
    status = "empty" if hero is None else ("stale" if stale else "current")

    return RenderResult(
        image=canvas,
        status=status,
        empty_sky=hero is None,
        stale=stale,
        rendered_ids=rendered_ids,
        age_seconds=age,
        config=config,
        horizon_y=layout.panel_top,
    )


def render_to_path(
    snapshot: AircraftSnapshot,
    path: str | Path,
    config: RenderConfig | None = None,
) -> RenderResult:
    """Render and write a PNG, creating the parent directory if needed."""
    result = render_snapshot(snapshot, config)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result.image.save(destination, format="PNG", optimize=False)
    return result