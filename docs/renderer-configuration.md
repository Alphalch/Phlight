# Renderer configuration and sample output

How to run the offline portrait renderer on local aircraft JSON, how to change
canvas size and palette, how to render the empty-sky state, and how to
regenerate the sample images in `docs/samples/`.

**Scope.** Everything below is RGB preview output from a desktop Python
process. No display panel has been selected, nothing has been driven to
e-paper hardware, and no physical validation has been done. The 480×800 and
800×480 sizes are preview sizes, not panel resolutions.

## Limitations to read first

* **No automatic selection pipeline.** The renderer accepts serialized selector
  results for tested cases, but no automatic connection to `phlight.aircraft`
  exists. Raw decoder records are not filtered by the renderer; select eligible
  aircraft before rendering (see `docs/aircraft-selection-contract.md`).
* **No live pipeline.** Nothing here receives ADS-B, decodes messages, or
  reads a live receiver. The only inputs are the hand-authored fixtures in
  `fixtures/` or a JSON file you write yourself.
* **Fake fixture data.** `fixtures/*.json` are invented for testing. Callsigns,
  positions, registrations and operators are not recordings of real traffic.
  The sample PNGs therefore show fabricated flights.
* **Generic artwork.** The aircraft drawing is a generic parametric plan-view
  silhouette per drawing class (a 737 and an A320 look alike). It is not the
  hand-drawn style of any reference product, and it has not been reviewed as
  finished artwork.
* **Palettes are RGB approximations.** `spectra6` is an idealised reference
  set, not a measured panel profile.

## Run on local aircraft data

Requirements: Python ≥ 3.11 and Pillow ≥ 10.1.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install pillow pytest     # Windows; use .venv/bin/ on Linux/macOS
.venv/Scripts/python -m phlight.render.cli fixtures/overhead_snapshot.json --out out/portrait.png
```

Your own snapshot must be a JSON object with an `aircraft` list. Only `hex`
(6 hex characters) is required per aircraft; the other fields are optional
(see the data model in `docs/portrait-renderer.md`). Minimal valid example,
verified to render:

```json
{"aircraft": [{"hex": "abc123"}]}
```

Pin the displayed timestamp with `--captured-at <epoch>` and staleness with
`--now <epoch>`. Without `--now` the renderer never reads the clock and never
marks a snapshot stale.

## Canvas size

| flag | default | notes |
| --- | --- | --- |
| `--width` | 480 | pixels, honoured exactly; minimum 160 per side |
| `--height` | 800 | pixels, honoured exactly |

```bash
.venv/Scripts/python -m phlight.render.cli fixtures/overhead_snapshot.json --out out/landscape.png --width 800 --height 480
```

## Palette

`--palette ink | spectra6 | dusk` (default `ink`). List them with
`--list-palettes`. The renderer paints only palette colours (ordered 8×8
dithering between two of them per pixel); the test suite checks this for every
preset. Custom palettes are possible through the Python API
(`Palette(name=..., colors={...})`, every role in `ROLES` required).

## Empty-sky state

Two ways to get it:

* the snapshot has `"aircraft": []`, e.g. `fixtures/empty_sky_snapshot.json`
  (fabricated: "receiver heard nothing");
* `--empty-sky` forces it for any snapshot (copy review, layout checks).

The empty state draws a sun, the headline `NOTHING OVERHEAD`, the detail line
`CLEAR SKY - NO AIRCRAFT IN RANGE`, and the capture stamp. It has no silhouette
and no fleet strip. It takes priority over staleness.

## Stale state

A populated snapshot is marked stale when `--now − captured_at >
--stale-after` (default 300 s). The image then carries a
`STALE - LAST UPDATE <age> AGO` banner. The aircraft are still drawn.

## Regenerate the sample images

All sample inputs are committed fixtures and all timestamps are pinned, so the
renders were reproduced locally on Windows with Pillow 13.0.0 and its default
embedded font. Cross-machine byte identity has not been verified:

```bash
.venv/Scripts/python scripts/regenerate_samples.py
```

This writes `docs/samples/*.png` and `docs/samples/SHA256SUMS`. Verify with
`(cd docs/samples && sha256sum -c SHA256SUMS)` from the repository root.

Individual commands used for the samples:

| sample | command |
| --- | --- |
| `portrait-spectra6.png` | `cli fixtures/overhead_snapshot.json --palette spectra6 --captured-at 1762500000` |
| `portrait-ink.png` | `cli fixtures/overhead_snapshot.json --palette ink` |
| `empty-sky-dusk.png` | `cli fixtures/empty_sky_snapshot.json --palette dusk --width 800 --height 480` |
| `landscape-spectra6.png` | `cli fixtures/overhead_snapshot.json --palette spectra6 --width 800 --height 480` |
| `stale-portrait-dusk.png` | `cli fixtures/overhead_snapshot.json --palette dusk --now 1762501800 --stale-after 300` |

## Artwork provenance and attribution

* **Silhouettes:** original parametric polygons in `phlight/render/silhouettes.py`,
  The project is marked proprietary. Not traced from photographs, icon sets, or any
  third-party or FlightPortrait artwork.
* **Type table:** ICAO designator → drawing class, independently authored.
* **Font:** text uses the Aileron font that Pillow loads via
  `ImageFont.load_default(size=...)`. The font file is not vendored in this
  repository. Pillow's documentation credits Aileron (https://dotcolon.net/fonts/aileron).
  Pillow embeds the font data in its source; its licence was not independently
  verified here, so do not redistribute the font
  itself without confirming its terms. Pass `--font` to use another TTF.
* **Fixtures and samples:** fabricated test data. No attribution is required for
  the data; the samples are generated by this repository's code.
* No FlightPortrait artwork or proprietary poster content is included.
