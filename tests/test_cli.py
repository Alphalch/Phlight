"""Tests for the command-line interface used by the repository workflows."""

from __future__ import annotations

from pathlib import Path

import pytest

from phlight.render.cli import main

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_cli_renders_a_snapshot_to_png(tmp_path: Path) -> None:
    out = tmp_path / "portrait.png"

    code = main([str(FIXTURES / "overhead_snapshot.json"), "--out", str(out)])

    assert code == 0
    assert out.read_bytes().startswith(b"\x89PNG")


def test_cli_accepts_size_and_palette_options(tmp_path: Path) -> None:
    out = tmp_path / "small.png"

    code = main(
        [
            str(FIXTURES / "overhead_snapshot.json"),
            "--out",
            str(out),
            "--width",
            "240",
            "--height",
            "400",
            "--palette",
            "dusk",
        ]
    )

    assert code == 0
    from PIL import Image

    with Image.open(out) as image:
        assert image.size == (240, 400)


def test_cli_renders_the_empty_sky_state(tmp_path: Path) -> None:
    out = tmp_path / "empty.png"

    code = main([str(FIXTURES / "empty_sky_snapshot.json"), "--out", str(out)])

    assert code == 0


def test_cli_force_empty_sky_ignores_aircraft(tmp_path: Path) -> None:
    out = tmp_path / "forced.png"

    code = main(
        [
            str(FIXTURES / "overhead_snapshot.json"),
            "--out",
            str(out),
            "--empty-sky",
            "--captured-at",
            "1762500600",
        ]
    )

    assert code == 0


def test_cli_reports_unknown_palette(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            str(FIXTURES / "overhead_snapshot.json"),
            "--out",
            str(tmp_path / "x.png"),
            "--palette",
            "neon",
        ]
    )

    assert code == 2
    assert "neon" in capsys.readouterr().err


def test_cli_reports_missing_snapshot(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(tmp_path / "missing.json"), "--out", str(tmp_path / "x.png")])

    assert code == 2
    assert "missing.json" in capsys.readouterr().err


def test_cli_lists_palettes(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--list-palettes"])

    assert code == 0
    out = capsys.readouterr().out
    assert "ink" in out and "spectra6" in out and "dusk" in out