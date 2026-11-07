"""Command-line entry point: render a portrait from a local snapshot file.

Examples
--------
Render the recorded fixture at the default preview size::

    python -m phlight.render.cli fixtures/overhead_snapshot.json --out out/portrait.png

Render a different canvas and palette, marking 15-minute-old data as stale::

    python -m phlight.render.cli snapshot.json --out out/x.png \
        --width 800 --height 480 --palette spectra6 --now 1762501800 --stale-after 300

Force the empty-sky state (useful for copy review and for a panel smoke test)::

    python -m phlight.render.cli snapshot.json --out out/empty.png --empty-sky
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from typing import Sequence

from .config import MIN_CANVAS_PX, RenderConfig
from .models import SnapshotError, load_snapshot
from .palette import PALETTES, palette_by_name
from .renderer import render_to_path

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phlight-render",
        description="Render a Phlight aircraft portrait from a local snapshot JSON file.",
    )
    parser.add_argument("snapshot", nargs="?", help="local aircraft snapshot JSON file")
    parser.add_argument(
        "--out",
        default="-",
        help="output PNG path, or '-' for stdout metadata only (default: -)",
    )
    parser.add_argument("--width", type=int, default=RenderConfig.width, help="canvas width in pixels")
    parser.add_argument("--height", type=int, default=RenderConfig.height, help="canvas height in pixels")
    parser.add_argument(
        "--palette",
        default="ink",
        help="colour palette preset (see --list-palettes)",
    )
    parser.add_argument("--max-fleet", type=int, default=RenderConfig.max_fleet, help="extra aircraft shown under the hero")
    parser.add_argument("--empty-sky", action="store_true", help="force the empty-sky state regardless of the snapshot")
    parser.add_argument("--now", type=float, default=None, help="reference epoch seconds used to judge staleness")
    parser.add_argument(
        "--captured-at",
        type=float,
        default=None,
        help="override the snapshot capture time (pins the displayed stamp for previews)",
    )
    parser.add_argument(
        "--stale-after",
        type=float,
        default=RenderConfig.stale_after_seconds,
        help="seconds after which a snapshot is marked stale",
    )
    parser.add_argument("--no-caption", action="store_true", help="omit the footer caption line")
    parser.add_argument("--font", default=None, help="path to a TTF file to override the bundled font")
    parser.add_argument("--list-palettes", action="store_true", help="list palette presets and exit")
    parser.add_argument("--quiet", action="store_true", help="suppress the summary line")
    return parser


def _fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list_palettes:
        for name in sorted(PALETTES):
            palette = PALETTES[name]
            print(f"{name}: {palette.description}")
        return 0

    if not args.snapshot:
        return _fail("a snapshot JSON path is required (or use --list-palettes)")

    try:
        config = RenderConfig(
            width=args.width,
            height=args.height,
            palette=palette_by_name(args.palette),
            max_fleet=args.max_fleet,
            force_empty_sky=args.empty_sky,
            show_caption=not args.no_caption,
            font_path=args.font,
            now=args.now,
            stale_after_seconds=args.stale_after,
        )
    except ValueError as exc:
        return _fail(str(exc))

    try:
        snapshot = load_snapshot(args.snapshot)
    except SnapshotError as exc:
        return _fail(str(exc))

    if args.captured_at is not None:
        snapshot = replace(snapshot, captured_at=float(args.captured_at))

    print(
        f"loaded {len(snapshot.aircraft)} aircraft"
        + (f", dropped {len(snapshot.dropped)}" if snapshot.dropped else ""),
        file=sys.stderr,
    )
    for issue in snapshot.issues:
        print(f"warning: {issue}", file=sys.stderr)

    if args.out == "-":
        from .renderer import render_snapshot

        result = render_snapshot(snapshot, config)
        if not args.quiet:
            print(
                f"status={result.status} size={result.image.width}x{result.image.height} "
                f"palette={config.palette.name} rendered={','.join(result.rendered_ids) or '-'}"
            )
        return 0

    result = render_to_path(snapshot, args.out, config)
    if not args.quiet:
        print(
            f"wrote {args.out} status={result.status} "
            f"size={result.image.width}x{result.image.height} palette={config.palette.name}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())