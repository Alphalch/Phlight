# Phlight

Phlight is a planned framed 7.3-inch color e-paper portrait showing aircraft detected overhead by an integrated ADS-B receiver. Inspired by [FlightPortrait](https://flightportrait.com/), it is intended to be a single hangable object, not a dashboard or an external receiver box.

## Initial direction

- **Power:** USB-powered for continuous reception; not a battery-life commitment.
- **Hardware:** a small Linux computer, a 1090 MHz ADS-B receiver, and antenna mounted inside or on the back of the frame. A Raspberry Pi Zero 2 W and a compact RTL-SDR-class receiver are candidates, not confirmed parts.
- **Display:** 7.3-inch color e-paper and an appropriate driver; select and verify an exact panel before fixing resolution or enclosure dimensions.
- **Software:** receive aircraft positions locally, select nearby/overhead traffic, compose original artwork, and periodically refresh the display. The intended initial prototype uses Linux and Python with an existing ADS-B decoder.
- **Enclosure:** allow a radio-transparent antenna area, cooling, service access, and space for power and receiver hardware. Reception and wall placement must be tested in the finished enclosure.

These choices are provisional until the hardware is tested. Aircraft outside receiver coverage or without usable position reports will not appear. A continuously powered receiver does not imply continuous e-paper refresh.

## Aircraft selection

`phlight.aircraft` reads one local decoder file — readsb's or dump1090-fa's
`aircraft.json` — and chooses at most one aircraft: the nearest one inside a
15 km gate around an explicitly configured home position. Stale, positionless
and out-of-range reports are rejected with counted reasons rather than being
drawn as overhead, and a dead feed is distinguishable from a quiet sky. The
component never reads the system clock: the caller injects `now`, which makes
every decision reproducible from a fixture.

```python
import time

from phlight.aircraft import load_config, load_source_path, select_from_file

config, problems = load_config(config_mapping)
path, path_problems = load_source_path(config_mapping)
result = select_from_file(path, config, now=time.time())

if result.state == "ok":
    aircraft = result.aircraft          # nearest, freshest, lowest hex on ties
else:
    ...                                 # render the empty-sky portrait
```

Every state other than `ok` — `empty_sky`, `stale_input`, `missing_input`,
`invalid_input`, `unconfigured` — draws the same empty-sky artwork; the state
and reason exist for logs and diagnostics. No network or vendor service is
involved. The selection component has no third-party runtime dependency; the
renderer uses Pillow.

Selection rules, thresholds, configuration keys and environment variables are
specified in [docs/aircraft-selection-contract.md](docs/aircraft-selection-contract.md);
§13 records the amendments made during implementation.

## Offline portrait renderer

The renderer creates configurable PNG previews from local JSON. See
[renderer configuration](docs/renderer-configuration.md) and
[renderer details](docs/portrait-renderer.md). It is not an automated live
receiver-to-display pipeline. Its generic silhouettes are not finished
hand-drawn artwork, and physical display validation has not been performed.

## Work tracking

The dedicated Hermes Kanban board is `phlight`. The first tasks cover hardware research, receiver ingestion, artwork/rendering, enclosure integration, and end-to-end verification. See [project brief](docs/project-brief.md) for acceptance criteria.

## Reference and licensing

[FlightPortrait's firmware and device protocol](https://github.com/flightportrait/frame) are useful architectural references. Do not copy proprietary artwork; create original art or use assets with verified compatible licenses. If upstream code or data is reused, check and preserve the applicable license and attribution first.

## Status

Offline renderer previews and aircraft selection software exist; no working receiver, display driver, finished artwork, enclosure, or end-to-end prototype has been physically verified. No hardware has been purchased.
