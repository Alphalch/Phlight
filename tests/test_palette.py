"""Tests for palette presets and lookup."""

from __future__ import annotations

import pytest

from phlight.render import PALETTES, Palette, palette_by_name

REQUIRED_ROLES = ("paper", "ink", "sky_top", "sky_bottom", "accent", "accent_alt", "muted")


def test_every_preset_defines_the_required_roles() -> None:
    for name, palette in PALETTES.items():
        missing = [role for role in REQUIRED_ROLES if role not in palette.colors]
        assert not missing, f"{name} is missing {missing}"


def test_preset_colours_are_rgb_triples() -> None:
    for palette in PALETTES.values():
        for role, value in palette.colors.items():
            assert len(value) == 3, f"{palette.name}.{role}"
            assert all(isinstance(c, int) and 0 <= c <= 255 for c in value)


def test_spectra6_preset_is_limited_to_seven_inks() -> None:
    palette = palette_by_name("spectra6")

    assert len(palette.inks) <= 7
    assert (0, 0, 0) in palette.inks
    assert (255, 255, 255) in palette.inks


def test_lookup_is_case_insensitive() -> None:
    assert palette_by_name("Ink").name == palette_by_name("ink").name
    assert palette_by_name("  SPECTRA6 ").name == "spectra6"
    assert palette_by_name("Dusk").name == "dusk"


def test_unknown_preset_raises() -> None:
    with pytest.raises(ValueError, match="unknown palette"):
        palette_by_name("neon")


def test_palettes_have_distinct_paper_and_ink() -> None:
    for palette in PALETTES.values():
        assert palette.colors["paper"] != palette.colors["ink"]


def test_roles_resolve_to_palette_colours() -> None:
    palette = PALETTES["ink"]

    assert palette["ink"] == palette.colors["ink"]
    with pytest.raises(KeyError):
        palette["chartreuse"]


def test_custom_palette_can_be_constructed() -> None:
    palette = Palette(name="custom", colors={role: (1, 2, 3) for role in REQUIRED_ROLES})

    assert palette["paper"] == (1, 2, 3)
    assert palette.inks == ((1, 2, 3),)


def test_custom_palette_missing_role_raises_value_error() -> None:
    incomplete = {role: (10, 20, 30) for role in REQUIRED_ROLES if role != "muted"}

    with pytest.raises(ValueError, match="muted"):
        Palette(name="broken", colors=incomplete)


def test_palette_colors_mapping_is_immutable() -> None:
    palette = palette_by_name("ink")

    with pytest.raises(TypeError):
        palette.colors["paper"] = (0, 0, 0)  # type: ignore[index]
