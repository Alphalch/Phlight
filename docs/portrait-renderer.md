# Aircraft portrait renderer

The renderer turns a local aircraft snapshot into one portrait image: dithered
sky, a plan-view silhouette of the closest aircraft, a caption panel, and a
short list of the other aircraft in range. It is the "composition" stage of the
intended pipeline in the [project brief](project-brief.md). Only the offline
JSON-to-PNG portion is implemented here; the parts are not automatically connected:

```text
ADS-B receiver → decoder → local snapshot JSON → this renderer → PNG → (future) display refresh
```

**Scope.** This document describes code that exists and is tested. It does not
describe a working device: no display panel has been selected, nothing has been
shown on e-paper hardware, and no physical validation has been performed. The
default 480×800 canvas is a preview size, not a chosen panel resolution.

## Quick start

```bash
python -m pip install pillow pytest    # or: uv pip install pillow pytest

# portrait, default palette (monochrome)
python -m phlight.render.cli fixtures/overhead_snapshot.json --out out/portrait.png

# force the empty-sky state, warm palette, landscape canvas
python -m phlight.render.cli fixtures/empty_sky_snapshot.json \
    --out out/empty.png --palette dusk --width 800 --height 480

# mark a 30-minute-old snapshot as stale
python -m phlight.render.cli fixtures/overhead_snapshot.json \
    --out out/stale.png --palette spectra6 --now 1762501800 --stale-after 300

python -m pytest
```

Run these from the repository root, or `pip install -e .` first. Requirements:
Python ≥ 3.11 and Pillow ≥ 10.1.

## Local data model

The renderer reads one JSON document. Nothing else is required; there is no
network call, database, or vendor service in this path. The selector and renderer
are not automatically connected. The model accepts a serialized selector result
for tested cases, but no live pipeline or display refresh loop exists. Raw decoder
records are not filtered by the renderer; select eligible aircraft first.

```json
{
  "captured_at": 1762500000,
  "source": "dump1090",
  "home": {"lat": 22.3375, "lon": 114.1831},
  "aircraft": [
    {
      "hex": "780a1b", "callsign": "CPA715", "registration": "B-KPF",
      "type_code": "A333", "type_name": "Airbus A330-300",
      "operator": "Cathay Pacific", "altitude_ft": 11250,
      "distance_km": 4.2, "bearing_deg": 38.0, "track_deg": 52.0,
      "ground_speed_kt": 287, "seen_at": 1762499994.0
    }
  ]
}
```

| field | meaning |
| --- | --- |
| `captured_at` | epoch seconds (UTC) when the snapshot was taken; used for the footer stamp and for staleness |
| `source` | free-text provenance, e.g. decoder name |
| `home` | receiver reference point, if known (not drawn; kept for later use) |
| `aircraft[].hex` | six hex characters, optionally prefixed `~` for a non-ICAO address — **the only required aircraft field** |
| `callsign`, `registration` | identity as heard, may be absent |
| `type_code` | ICAO type designator (`A21N`, `B738`, `C172`, `EC35`…), drives which silhouette is drawn |
| `type_name`, `operator` | human-readable enrichment (may come from a licensed static database later) |
| `altitude_ft`, `distance_km`, `bearing_deg`, `track_deg`, `ground_speed_kt` | numbers; `track_deg` rotates the drawing, the rest are printed |
| `seen_at` | epoch seconds of the last message for that aircraft |

Loading is deliberately tolerant, because receivers produce partial records:

* an entry without a usable 6-character `hex` is dropped (`AircraftSnapshot.dropped`);
* a non-numeric optional field becomes `None` and is reported in
  `AircraftSnapshot.issues` instead of raising;
* `"aircraft": []` is a valid snapshot and produces the empty-sky state;
* an unreadable file, invalid JSON, or a non-object document raises `SnapshotError`.

Records without `distance_km` still render (they sort last and print `--`).
Rejecting stale or positionless reports is the **ingest/selection** stage's job;
the renderer only refuses to *imply* freshness (see below).

## Python interface

```python
from phlight.render import RenderConfig, load_snapshot, render_snapshot, render_to_path

snapshot = load_snapshot("snapshot.json")
result = render_snapshot(snapshot, RenderConfig(width=480, height=800, palette="ink"))

result.image          # PIL.Image, RGB, exactly config.width × config.height
result.status         # "current" | "empty" | "stale"
result.empty_sky      # bool
result.stale          # bool
result.age_seconds    # float or None (None unless config.now was supplied)
result.rendered_ids   # aircraft hex codes actually drawn, hero first
result.horizon_y      # y where sky meets the caption panel
result.config         # the resolved configuration

render_to_path(snapshot, "out/portrait.png", result.config)   # renders and saves
```

`render_snapshot` is pure: it never reads the clock, the network, or a driver.
The same snapshot and config always produce byte-identical pixels, which is what
the test suite asserts.

## Configuration

`RenderConfig` is a frozen dataclass:

| option | default | effect |
| --- | --- | --- |
| `width`, `height` | `480`, `800` | canvas in pixels; honoured exactly. Minimum 160 px per side, larger values may be anything (odd sizes included) |
| `palette` | `"ink"` | preset name or a `Palette` instance |
| `max_fleet` | `3` | how many other aircraft to list under the hero (0 disables the strip) |
| `empty_sky_headline` | `"NOTHING OVERHEAD"` | headline in the empty state |
| `empty_sky_detail` | `"CLEAR SKY - NO AIRCRAFT IN RANGE"` | second line in the empty state |
| `force_empty_sky` | `False` | render the empty state even when aircraft are present (useful for copy review) |
| `show_caption` | `True` | footer line with capture time and wordmark |
| `now` | `None` | reference epoch seconds for staleness. `None` means "no reference" — the wall clock is never consulted |
| `stale_after_seconds` | `300` | age above which a populated snapshot is marked stale |
| `font_path` | `None` | override the bundled font with a TTF file |

Text is rasterised to a 1-bit mask and pasted, so anti-aliasing never introduces
off-palette tints.

## Palettes

| preset | intent |
| --- | --- |
| `ink` | monochrome: white paper, near-black ink, grey sky ramp |
| `spectra6` | idealised 7-colour e-paper ink set (black, white, red, yellow, blue, green), used as a *reference*, not a panel profile |
| `dusk` | warm evening sky, cream paper |

A palette maps seven roles — `paper`, `ink`, `sky_top`, `sky_bottom`, `accent`,
`accent_alt`, `muted` — to RGB triples. Build a custom one with
`Palette(name=..., colors={...})`; every role must be present. The renderer
paints **only** palette colours, mixing at most two of them per pixel via ordered
dithering, so output stays inside a limited-ink gamut. The test suite checks this
for every preset.

## States

| state | when | what is drawn |
| --- | --- | --- |
| `current` | aircraft present, no staleness reference or age ≤ threshold | hero silhouette rotated to `track_deg`, callsign, type/operator, four readings, fleet strip |
| `empty` | `snapshot.aircraft` is empty, or `force_empty_sky` | sky and sun, headline, detail line, capture stamp — no silhouette, no fleet strip |
| `stale` | aircraft present **and** `config.now - captured_at > stale_after_seconds` | the same portrait plus an accent banner: `STALE - LAST UPDATE <age> AGO` |

A snapshot timestamped *after* `now` (clock skew) yields a negative age and is
not treated as stale. The empty state always wins over staleness: `status` is
`"empty"`, not `"stale"`.

The renderer deliberately still shows aircraft in the stale state — it labels
the data instead of hiding it — but the banner prevents a frozen image from
looking live. Whether to blank the panel after a longer outage is a refresh-loop
policy, still undecided.

## Layout

Bands are fractions of canvas height: sky `0 → 0.50`, caption panel `0.50 →
0.78`, fleet strip `0.78 → ~0.97`, footer to the bottom. `horizon_y` reports the
actual pixel boundary. Elements that do not fit (small canvases, landscape)
degrade in a fixed order: extra fleet rows, then readings, then the type line —
never by clipping the silhouette into the caption panel, which the tests assert.

## Artwork provenance

* **Silhouettes** are original: parametric plan-view polygons generated in
  `phlight/render/silhouettes.py` (fuselage, wing panel, tailplane, nacelles).
  They are not traced from photographs, icon sets, or FlightPortrait artwork.
  The project is marked proprietary; no MIT licence is asserted here.
* **Type library**: the ICAO designator → drawing-class table is factual
  reference data, independently authored here.
* **Font**: Pillow's `ImageFont.load_default(size=...)` loads an embedded subset
  of Aileron Regular. No separate font file is vendored here. Font redistribution
  terms have not been independently verified; verify them before redistribution.
  A custom font can be passed via `font_path` subject to its terms.
* **Fixtures** in `fixtures/` are hand-authored and clearly marked as such; they
  are not recordings of real traffic and no attribution applies.

No third-party artwork is redistributed with this renderer. Nothing here is
derived from FlightPortrait's proprietary posters.

## Display integration notes

* The renderer is stateless and cheap (roughly 0.2 s at 480×800); the refresh
  loop owns scheduling, reception, stale-report rejection, and the decision to
  re-render.
* Panel choice is still open. Vendor guidance for the Waveshare 7.3-inch
  e-Paper HAT (E) family — a *candidate*, not a selection — is to leave ≥180 s
  between refreshes and to refresh at least once every 24 h
  ([manual](https://waveshare.com/wiki/7.3inch_e-Paper_HAT_(E)_Manual)). A
  refresh loop should therefore treat aircraft data older than its own
  `stale_after_seconds` as stale, and treat the *display* as stale if no refresh
  has happened within 24 h.
* Colour reproduction on limited-ink panels will differ from these RGB previews.
  `spectra6` is an idealised reference set, not a measured panel profile.

## Known limitations

* Dithering is 8×8 ordered, not error-diffused; dense gradients can look like a
  printed dot screen rather than a smooth wash.
* Text below roughly 7 px is not legible; on small canvases the footer shrinks to
  that floor.
* Silhouettes are generic per class — a 737 and an A320 look alike on purpose.
* No night/inverted panel mode, no weather, no map, no historical trail.
* Nothing here validates the e-paper path, refresh timing, or physical output.

## Tests

`tests/` covers the loading contract, palette roles and lookup, silhouette
geometry bounds and type mapping, rendering behaviour (canvas size, states,
determinism, palette containment, band separation, fleet limits), and the CLI.
Run `python -m pytest` from the repository root.