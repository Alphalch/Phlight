"""Tests for the original aircraft silhouette geometry."""

from __future__ import annotations

from pathlib import Path

from phlight.render import load_snapshot, silhouettes

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_known_type_codes_map_to_size_classes() -> None:
    assert silhouettes.class_for_type("B738") == "narrowbody"
    assert silhouettes.class_for_type("A21N") == "narrowbody"
    assert silhouettes.class_for_type("B77W") == "widebody"
    assert silhouettes.class_for_type("A388") == "widebody"
    assert silhouettes.class_for_type("CRJ9") == "regional"
    assert silhouettes.class_for_type("AT76") == "turboprop"
    assert silhouettes.class_for_type("C172") == "general_aviation"
    assert silhouettes.class_for_type("EC35") == "helicopter"


def test_lookup_ignores_case_and_whitespace() -> None:
    assert silhouettes.class_for_type(" b738 ") == "narrowbody"


def test_unknown_or_missing_type_falls_back_to_generic() -> None:
    assert silhouettes.class_for_type("ZZZZ") == "generic"
    assert silhouettes.class_for_type(None) == "generic"
    assert silhouettes.class_for_type("") == "generic"
    assert silhouettes.class_for_type(123) == "generic"  # type: ignore[arg-type]


def test_every_class_has_a_symbol() -> None:
    for size_class in silhouettes.SYMBOLS:
        assert silhouettes.symbol_for(size_class).parts


def test_unknown_class_gets_the_generic_symbol() -> None:
    assert silhouettes.symbol_for("airship").parts == silhouettes.symbol_for("generic").parts


def test_polygons_stay_inside_the_normalised_box() -> None:
    for name, symbol in silhouettes.SYMBOLS.items():
        for part in symbol.parts:
            assert len(part.points) >= 3, name
            for x, y in part.points:
                assert 0.0 <= x <= 1.0, (name, x)
                assert 0.0 <= y <= 1.0, (name, y)


def test_symbols_are_longer_than_they_are_wide_for_fixed_wing() -> None:
    for name in ("narrowbody", "widebody", "regional", "general_aviation", "helicopter"):
        symbol = silhouettes.SYMBOLS[name]
        width = max(x for part in symbol.parts for x, _ in part.points) - min(
            x for part in symbol.parts for x, _ in part.points
        )
        height = max(y for part in symbol.parts for _, y in part.points) - min(
            y for part in symbol.parts for _, y in part.points
        )
        assert height > width * 0.75, name


def test_widebody_is_proportionally_broader_than_general_aviation() -> None:
    def aspect(name: str) -> float:
        symbol = silhouettes.SYMBOLS[name]
        xs = [x for part in symbol.parts for x, _ in part.points]
        ys = [y for part in symbol.parts for _, y in part.points]
        return (max(xs) - min(xs)) / (max(ys) - min(ys))

    assert aspect("widebody") > aspect("general_aviation")


def test_symbols_are_original_geometry_with_no_external_source() -> None:
    for symbol in silhouettes.SYMBOLS.values():
        assert symbol.attribution.startswith("original")


def test_representative_classes_fixture_covers_every_silhouette_class() -> None:
    snapshot = load_snapshot(FIXTURES / "representative_classes_snapshot.json")
    classes = {silhouettes.class_for_type(a.type_code) for a in snapshot.aircraft}

    assert classes == set(silhouettes.SYMBOLS.keys())
