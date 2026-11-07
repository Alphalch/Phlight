"""Tests for the command-line interface used by the repository workflows."""

from __future__ import annotations

from pathlib import Path

import pytest

from phlight.render import RenderConfig, load_snapshot, render_to_path
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


def test_cli_stdout_summary_and_stale_marking(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            str(FIXTURES / "representative_classes_snapshot.json"),
            "--out",
            "-",
            "--palette",
            "spectra6",
            "--now",
            "1762502000",
            "--stale-after",
            "300",
        ]
    )

    assert code == 0
    captured = capsys.readouterr()
    assert "status=stale" in captured.out
    assert "palette=spectra6" in captured.out
    assert "780912" in captured.out


def test_cli_missing_snapshot_argument_and_invalid_dimensions_fail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    assert "required" in capsys.readouterr().err

    assert main([str(FIXTURES / "overhead_snapshot.json"), "--width", "80"]) == 2
    assert "canvas" in capsys.readouterr().err


def test_cli_png_output_is_byte_identical_to_render_to_path(tmp_path: Path) -> None:
    cli_out = tmp_path / "cli.png"
    api_out = tmp_path / "api.png"
    fixture_path = FIXTURES / "representative_classes_snapshot.json"

    code = main(
        [
            str(fixture_path),
            "--out",
            str(cli_out),
            "--width",
            "240",
            "--height",
            "400",
            "--palette",
            "spectra6",
            "--quiet",
        ]
    )
    assert code == 0

    render_to_path(
        load_snapshot(fixture_path),
        api_out,
        RenderConfig(width=240, height=400, palette="spectra6"),
    )

    assert cli_out.read_bytes() == api_out.read_bytes()