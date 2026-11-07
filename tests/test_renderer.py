"""Behavioural tests for the portrait renderer.

Every assertion runs against real rendering output; nothing here needs a
receiver, a network lookup, or a display panel.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from phlight.render import (
    MIN_CANVAS_PX,
    PALETTES,
    Aircraft,
    AircraftSnapshot,
    Palette,
    RenderConfig,
    load_snapshot,
    palette_by_name,
    render_snapshot,
    render_to_path,
    silhouettes,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def snapshot(name: str = "overhead_snapshot.json"):
    return load_snapshot(FIXTURES / name)


def test_output_matches_configured_canvas_size() -> None:
    config = RenderConfig(width=320, height=640)

    result = render_snapshot(snapshot(), config)

    assert result.image.size == (320, 640)


def test_default_canvas_is_a_portrait_orientation() -> None:
    config = RenderConfig()

    assert config.height > config.width


def test_empty_snapshot_sets_the_empty_sky_flag() -> None:
    result = render_snapshot(snapshot("empty_sky_snapshot.json"))

    assert result.empty_sky is True
    assert result.rendered_ids == ()


def test_populated_snapshot_is_not_empty_sky() -> None:
    result = render_snapshot(snapshot())

    assert result.empty_sky is False
    assert result.rendered_ids


def test_empty_sky_state_looks_different_from_populated_state() -> None:
    populated = render_snapshot(snapshot())
    empty = render_snapshot(snapshot("empty_sky_snapshot.json"))

    assert populated.image.tobytes() != empty.image.tobytes()


def test_same_input_renders_identically() -> None:
    first = render_snapshot(snapshot())
    second = render_snapshot(snapshot())

    assert hashlib.sha256(first.image.tobytes()).hexdigest() == hashlib.sha256(
        second.image.tobytes()
    ).hexdigest()


def test_render_is_reproducible_across_new_snapshot_objects() -> None:
    a = render_snapshot(snapshot(), RenderConfig(width=300, height=500))
    b = render_snapshot(snapshot(), RenderConfig(width=300, height=500))

    assert a.image.tobytes() == b.image.tobytes()


@pytest.mark.parametrize("palette_name", sorted(PALETTES))
def test_output_uses_only_palette_colours(palette_name: str) -> None:
    palette = palette_by_name(palette_name)
    result = render_snapshot(snapshot(), RenderConfig(palette=palette))

    colours = {colour for _, colour in result.image.getcolors(maxcolors=1_000_000)}
    assert colours <= set(palette.inks)


def test_switching_palette_changes_the_pixels() -> None:
    ink = render_snapshot(snapshot(), RenderConfig(palette=palette_by_name("ink")))
    dusk = render_snapshot(snapshot(), RenderConfig(palette=palette_by_name("dusk")))

    assert ink.image.tobytes() != dusk.image.tobytes()


def test_palette_can_be_passed_by_name() -> None:
    config = RenderConfig(palette="dusk")

    assert config.palette.name == "dusk"


def test_hero_is_the_closest_aircraft_and_fleet_is_ordered() -> None:
    result = render_snapshot(snapshot(), RenderConfig(max_fleet=3))

    assert result.rendered_ids[0] == "780912"
    assert result.rendered_ids[1:] == ("7c9b1f", "780a1b", "7c1a2b")


def test_fleet_strip_respects_configured_limit() -> None:
    result = render_snapshot(snapshot(), RenderConfig(max_fleet=1))

    assert len(result.rendered_ids) == 2


def test_fleet_strip_can_be_disabled() -> None:
    with_strip = render_snapshot(snapshot(), RenderConfig(max_fleet=3))
    without_strip = render_snapshot(snapshot(), RenderConfig(max_fleet=0))

    assert len(without_strip.rendered_ids) == 1
    assert with_strip.image.size == without_strip.image.size


def test_aircraft_without_distance_or_altitude_still_renders() -> None:
    from phlight.render import Aircraft, AircraftSnapshot

    partial = AircraftSnapshot(
        captured_at=1762500000,
        aircraft=(Aircraft(hex="abcdef", callsign="TEST1", type_code="ZZZZ"),),
    )

    result = render_snapshot(partial)

    assert result.empty_sky is False
    assert result.rendered_ids == ("abcdef",)


def test_custom_empty_sky_text_changes_output() -> None:
    default = render_snapshot(snapshot("empty_sky_snapshot.json"))
    custom = render_snapshot(
        snapshot("empty_sky_snapshot.json"),
        RenderConfig(empty_sky_headline="NO TRAFFIC", empty_sky_detail="QUIET SKY"),
    )

    assert default.image.tobytes() != custom.image.tobytes()


def test_empty_sky_override_forces_the_state() -> None:
    result = render_snapshot(snapshot(), RenderConfig(force_empty_sky=True))

    assert result.empty_sky is True
    assert result.rendered_ids == ()


def test_canvas_must_be_big_enough() -> None:
    with pytest.raises(ValueError, match="canvas"):
        RenderConfig(width=40, height=40)


def test_canvas_rejects_non_positive_dimensions() -> None:
    with pytest.raises(ValueError):
        RenderConfig(width=0, height=800)


def test_render_to_path_writes_a_png(tmp_path: Path) -> None:
    out = tmp_path / "portrait.png"

    result = render_to_path(snapshot(), out, RenderConfig(width=240, height=400))

    assert out.exists()
    assert out.read_bytes().startswith(b"\x89PNG")
    assert result.image.size == (240, 400)


def test_odd_canvas_sizes_are_accepted() -> None:
    result = render_snapshot(snapshot(), RenderConfig(width=333, height=527))

    assert result.image.size == (333, 527)


def test_age_is_reported_only_when_a_reference_time_is_given() -> None:
    without_reference = render_snapshot(snapshot())
    with_reference = render_snapshot(snapshot(), RenderConfig(now=1762500060))

    assert without_reference.age_seconds is None
    assert with_reference.age_seconds == pytest.approx(60.0)


def test_no_reference_time_never_uses_the_wall_clock() -> None:
    result = render_snapshot(snapshot())

    assert result.stale is False
    assert result.status == "current"


def test_fresh_snapshot_is_not_stale() -> None:
    result = render_snapshot(snapshot(), RenderConfig(now=1762500060, stale_after_seconds=300))

    assert result.stale is False
    assert result.status == "current"


def test_old_snapshot_is_flagged_stale() -> None:
    result = render_snapshot(snapshot(), RenderConfig(now=1762501800, stale_after_seconds=300))

    assert result.stale is True
    assert result.status == "stale"


def test_stale_threshold_is_configurable() -> None:
    config = RenderConfig(now=1762500600, stale_after_seconds=86_400)

    assert render_snapshot(snapshot(), config).stale is False


def test_stale_render_is_marked_differently_from_a_current_one() -> None:
    current = render_snapshot(snapshot(), RenderConfig(now=1762500060))
    stale = render_snapshot(snapshot(), RenderConfig(now=1762501800))

    assert current.image.tobytes() != stale.image.tobytes()


def test_empty_sky_is_reported_as_empty_not_stale() -> None:
    result = render_snapshot(
        snapshot("empty_sky_snapshot.json"),
        RenderConfig(now=1762500600 + 90_000),
    )

    assert result.status == "empty"
    assert result.empty_sky is True


def test_negative_age_from_a_clock_skewed_snapshot_is_not_stale() -> None:
    result = render_snapshot(snapshot(), RenderConfig(now=1762499000))

    assert result.age_seconds is not None
    assert result.stale is False


def test_horizon_sits_at_the_configured_canvas_midpoint() -> None:
    result = render_snapshot(snapshot(), RenderConfig(width=300, height=500))

    assert result.horizon_y == 250


def test_hero_is_drawn_inside_the_sky_band() -> None:
    palette = palette_by_name("ink")
    result = render_snapshot(snapshot(), RenderConfig(palette=palette))

    sky = result.image.crop((0, 0, result.image.width, result.horizon_y))

    assert palette["ink"] in {colour for _, colour in sky.getcolors(maxcolors=1_000_000)}


@pytest.mark.parametrize("size", [(480, 800), (800, 480), (240, 400)])
def test_airframe_never_bleeds_into_the_caption_panel(size) -> None:
    palette = palette_by_name("spectra6")
    result = render_snapshot(
        snapshot(), RenderConfig(width=size[0], height=size[1], palette=palette)
    )
    image = result.image
    forbidden = {palette["ink"], palette["accent_alt"]}

    for y in range(result.horizon_y + 4, result.horizon_y + 8):
        row = {image.getpixel((x, y)) for x in range(image.width)}
        assert not (row & forbidden), f"aircraft or trail at row {y}"


def test_renders_every_representative_aircraft_class_as_hero_deterministically() -> None:
    rep = snapshot("representative_classes_snapshot.json")
    palette = palette_by_name("spectra6")
    config = RenderConfig(width=320, height=480, palette=palette, max_fleet=0)

    seen_classes: set[str] = set()
    sky_digests: dict[str, str] = {}

    for aircraft in rep.aircraft:
        size_class = silhouettes.class_for_type(aircraft.type_code)
        seen_classes.add(size_class)
        single = AircraftSnapshot(captured_at=rep.captured_at, aircraft=(aircraft,))

        first = render_snapshot(single, config)
        second = render_snapshot(single, config)

        assert first.status == "current"
        assert first.rendered_ids == (aircraft.hex,)
        assert first.image.tobytes() == second.image.tobytes()

        colours = {colour for _, colour in (first.image.getcolors(maxcolors=1_000_000) or ())}
        assert colours <= set(palette.inks)

        sky_crop = first.image.crop((0, 0, first.image.width, first.horizon_y))
        sky_digests[size_class] = hashlib.sha256(sky_crop.tobytes()).hexdigest()

    assert seen_classes == set(silhouettes.SYMBOLS.keys())
    assert len(set(sky_digests.values())) == len(silhouettes.SYMBOLS)


def test_input_aircraft_array_order_invariance_produces_identical_pixels() -> None:
    rep = snapshot("representative_classes_snapshot.json")
    reversed_rep = AircraftSnapshot(
        captured_at=rep.captured_at,
        aircraft=tuple(reversed(rep.aircraft)),
        home=rep.home,
        source=rep.source,
    )
    config = RenderConfig(width=320, height=520, palette="dusk", max_fleet=3)

    forward_result = render_snapshot(rep, config)
    reverse_result = render_snapshot(reversed_rep, config)

    assert forward_result.rendered_ids == reverse_result.rendered_ids
    assert forward_result.image.tobytes() == reverse_result.image.tobytes()


def test_minimum_canvas_boundary_and_invalid_config_parameters(tmp_path: Path) -> None:
    min_cfg = RenderConfig(width=MIN_CANVAS_PX, height=MIN_CANVAS_PX, palette="spectra6")
    result = render_snapshot(snapshot("representative_classes_snapshot.json"), min_cfg)

    assert result.image.size == (MIN_CANVAS_PX, MIN_CANVAS_PX)
    colours = {colour for _, colour in (result.image.getcolors(maxcolors=1_000_000) or ())}
    assert colours <= set(palette_by_name("spectra6").inks)

    with pytest.raises(ValueError, match="canvas"):
        RenderConfig(width=MIN_CANVAS_PX - 1, height=MIN_CANVAS_PX)
    with pytest.raises(ValueError, match="canvas"):
        RenderConfig(width=MIN_CANVAS_PX, height=MIN_CANVAS_PX - 1)
    with pytest.raises(ValueError, match="integer"):
        RenderConfig(width=True, height=400)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="integer"):
        RenderConfig(width=400, height=400.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_fleet"):
        RenderConfig(max_fleet=-1)
    with pytest.raises(ValueError, match="palette"):
        RenderConfig(palette=123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="font_path"):
        RenderConfig(font_path=str(tmp_path / "missing.ttf"))


def test_custom_palette_renders_strictly_with_custom_inks_across_all_states() -> None:
    custom_colors = {
        "paper": (250, 248, 240),
        "ink": (12, 18, 24),
        "sky_top": (30, 60, 90),
        "sky_bottom": (220, 230, 240),
        "accent": (180, 40, 30),
        "accent_alt": (210, 160, 40),
        "muted": (90, 100, 110),
    }
    palette = Palette(name="custom_test", colors=custom_colors)

    for snap_name, now in (
        ("representative_classes_snapshot.json", None),
        ("empty_sky_snapshot.json", None),
        ("representative_classes_snapshot.json", 1762501200 + 3600),
    ):
        result = render_snapshot(
            snapshot(snap_name),
            RenderConfig(width=240, height=360, palette=palette, now=now),
        )
        colours = {colour for _, colour in (result.image.getcolors(maxcolors=1_000_000) or ())}
        assert colours <= set(palette.inks)


def test_all_dropped_snapshot_renders_empty_sky_state() -> None:
    dropped_only = AircraftSnapshot.from_dict(
        {
            "captured_at": 1762500000,
            "aircraft": [{"hex": "bad"}, {"callsign": "NOHEX"}],
        }
    )

    result = render_snapshot(dropped_only)

    assert dropped_only.is_empty is True
    assert len(dropped_only.dropped) == 2
    assert result.status == "empty"
    assert result.empty_sky is True
    assert result.rendered_ids == ()


def test_rendering_snapshot_with_non_finite_fields_does_not_crash() -> None:
    edge_snapshot = load_snapshot(FIXTURES / "non_finite_and_edge_snapshot.json")
    palette = palette_by_name("spectra6")

    result = render_snapshot(
        edge_snapshot,
        RenderConfig(width=240, height=400, palette=palette, now=1762501260),
    )

    assert result.status == "current"
    assert result.empty_sky is False
    colours = {colour for _, colour in (result.image.getcolors(maxcolors=1_000_000) or ())}
    assert colours <= set(palette.inks)

    for field_name, bad_val in (
        ("distance_km", "nan"),
        ("track_deg", "inf"),
        ("track_deg", "-inf"),
        ("track_deg", "nan"),
        ("bearing_deg", "nan"),
        ("bearing_deg", "inf"),
        ("ground_speed_kt", "inf"),
        ("ground_speed_kt", "nan"),
    ):
        single = AircraftSnapshot.from_dict(
            {
                "captured_at": "nan",
                "aircraft": [{"hex": "abc199", "type_code": "B738", field_name: bad_val}],
            }
        )
        single_res = render_snapshot(single, RenderConfig(width=200, height=320, palette=palette))
        assert single_res.status == "current"
        assert single_res.rendered_ids == ("abc199",)