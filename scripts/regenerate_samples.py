"""Regenerate the documented sample PNGs from the committed fixtures.

Fixtures and configuration fix timestamps; byte-identical regeneration was
verified locally with Pillow 13.0.0, not across machines. Writes
docs/samples/ and a SHA-256 manifest (docs/samples/SHA256SUMS).

    python scripts/regenerate_samples.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phlight.render import RenderConfig, load_snapshot, render_to_path  # noqa: E402

SAMPLES = ROOT / "docs" / "samples"
FIXTURES = ROOT / "fixtures"

# (output name, fixture, config overrides, pinned captured_at override or None)
JOBS = [
    ("portrait-spectra6.png", "overhead_snapshot.json",
     dict(palette="spectra6"), None),
    ("portrait-ink.png", "overhead_snapshot.json",
     dict(palette="ink"), None),
    ("empty-sky-dusk.png", "empty_sky_snapshot.json",
     dict(palette="dusk", width=800, height=480), None),
    ("landscape-spectra6.png", "overhead_snapshot.json",
     dict(palette="spectra6", width=800, height=480), None),
    ("stale-portrait-dusk.png", "overhead_snapshot.json",
     dict(palette="dusk", now=1762501800.0, stale_after_seconds=300.0), None),
]


def main() -> int:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, fixture, overrides, _ in JOBS:
        snapshot = load_snapshot(FIXTURES / fixture)
        config = RenderConfig(**overrides)
        out = SAMPLES / name
        result = render_to_path(snapshot, out, config)
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        manifest.append(f"{digest}  {name}")
        print(f"{name}: status={result.status} size={result.image.width}x{result.image.height} sha256={digest[:16]}")
    # Explicit LF bytes: write_text() would emit CRLF on Windows and break sha256sum -c.
    (SAMPLES / "SHA256SUMS").write_bytes(("\n".join(manifest) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
