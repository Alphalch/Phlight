# Aircraft selection contract

Status: proposed specification for implementation (card `t_c28b4251`) and
independent fixture tests (card `t_a39b0346`). Normative unless marked
non-normative. Derived from [project-brief.md](project-brief.md) success
criterion 2: *"Select aircraft using a documented home position and distance
rule; reject stale or positionless reports instead of representing them as
overhead."*

This document fixes the public interface, the data rules and the defaults. The
internal file layout is **not** normative; `phlight/aircraft/` in §8 is a
suggested shape, and any layout that exports the same names satisfies the
contract.

## 1. Design decisions at a glance

| Question | Decision | Default |
| --- | --- | --- |
| Input | Local decoder JSON file, explicit path, no probing | `/run/readsb/aircraft.json` |
| Transport | Filesystem only (no HTTP, no vendor API) | — |
| Snapshot clock | The file's own `now`, compared to an injected caller clock | — |
| Timestamp unit | Unix epoch **seconds** (float) | — |
| Position freshness | `seen_pos` + age of the snapshot itself | 10 s |
| Message freshness | `seen` + age of the snapshot itself | 30 s |
| Feed liveness | Snapshot age must stay small | 15 s |
| Home | Required explicit WGS84 decimal degrees, never inferred | none |
| Proximity | Haversine ground distance, single distance gate | 15 km |
| Ground traffic | Excluded unless configured otherwise | excluded |
| Ranking | Total order: rounded metres, then position age, then hex | — |
| Failure mode | Always return a result object; never raise on data | empty sky |

## 2. Input contract

### 2.1 Location

The component reads one JSON file written by a local ADS-B decoder. The path is
configuration, not discovery.

- Default: `/run/readsb/aircraft.json` — readsb's `--write-json` default
  directory.
- Documented alternates, set explicitly by the operator, never auto-probed:
  `/run/dump1090-fa/aircraft.json` and
  `/run/dump1090-mutability/aircraft.json`.
- No probing: two decoders can run on one host, and a silently chosen file makes
  selection depend on install order. If the configured path is absent the
  result is `missing_input`, not a fallback.
- readsb's HTTP endpoint (`http://<host>/tar1090/data/aircraft.json`) is out of
  scope for v1. The source protocol in §8 leaves room for it without changing
  `select()`.

### 2.2 Top-level document

```json
{
  "now": 1760000000.42,
  "messages": 123456,
  "aircraft": [ { "hex": "780abc", "lat": 22.31, "lon": 114.17, "seen_pos": 0.4, "seen": 0.1 } ]
}
```

Used fields: `now` (required, number) and `aircraft` (required, array of
objects). `messages` is ignored. Unknown keys, including readsb's `lastPosition`,
`rr_lat`/`rr_lon`, MLAT and TIS-B sub-objects, are ignored.

Both readsb and dump1090-fa write the file to a temporary name and atomically
rename it, so a partial read should not occur on ext4. A read that nevertheless
yields invalid JSON is treated as `invalid_input` (`reason="json_decode"`); the
refresh loop may retry once on the next cycle, and that retry policy lives
outside this component.

### 2.3 Per-aircraft fields

Field meanings follow the upstream docs
([readsb](https://github.com/wiedehopf/readsb/blob/dev/README-json.md),
[dump1090 `README-json.md`](https://github.com/flightaware/dump1090/blob/master/README-json.md)).

| Field | Type | Use |
| --- | --- | --- |
| `hex` | string, `^~?[0-9a-f]{6}$` | identity, dedupe, final tie-break |
| `lat`, `lon` | number, degrees | position; both required |
| `seen_pos` | number, seconds before `now` | position freshness |
| `seen` | number, seconds before `now` | message freshness |
| `flight` | string | callsign for artwork; optional |
| `alt_baro` | number **or** the string `"ground"` | on-ground detection, altitude for artwork |
| `track` | number, degrees | artwork; optional |
| `gs` | number, knots | artwork; optional |
| `category` | string, `A0`–`D7` | artwork; optional |
| `type` | string, decoder source tag | annotation only, never filtered on |

Absent keys are normal: both decoders omit unavailable fields. Missing optional
fields never reject an aircraft; missing `lat`, `lon` or `seen_pos` always do.

Two upstream behaviours matter here and are handled by the rules in §6 rather
than assumed away:

1. readsb drops an aircraft from `aircraft` once no message has arrived for
   ~60 s, and moves positions older than 60 s into `lastPosition` while
   omitting top-level `lat`/`lon`.
2. dump1090-fa keeps a track for ~5 minutes after the last message, so top-level
   `lat`/`lon` can be far staler than 60 s.

Consequently `seen` and `seen_pos` are always evaluated explicitly. The
contract never infers freshness from the presence of the aircraft in the array.
readsb's `lastPosition` object deliberately holds a position it considers no
longer valid; it must not be used to resurrect one.

## 3. Timestamps and freshness

Units are **seconds**. `now`, `seen` and `seen_pos` are floating-point seconds;
`now` is Unix epoch, and `seen`/`seen_pos` are ages relative to that same `now`.
Milliseconds are not accepted anywhere.

Because decoder ages are relative to the file's `now` rather than to the wall
clock, a frozen decoder file must not look fresh. Age is measured in two steps:

```text
snapshot_age_s = max(0.0, now - file_now)          # caller clock vs file clock
message_age_s  = snapshot_age_s + max(0.0, seen)
position_age_s = snapshot_age_s + max(0.0, seen_pos)
```

- `now` is a required argument of `select()` — an injected Unix-seconds clock.
  Nothing inside the component reads the system clock.
- Negative `seen`/`seen_pos` values (float rounding, slight clock skew between
  decoder and caller) are clamped to `0.0`; they are not an error.
- `file_now` must be a finite number in `[1e9, 1e11)` (2001-09-09 through
  5138-11-16). Outside that range, or absent, the whole snapshot is
  `invalid_input` with `reason="invalid_now"`. This rejects a millisecond value
  (`1.76e12`) instead of silently rejecting every aircraft as stale.
- Feed liveness: if `snapshot_age_s > max_snapshot_age_s` the result is
  `stale_input` (`reason="feed_stalled"`) and no aircraft is selected, even if
  the file still lists plausible traffic. A dead decoder must produce an empty
  sky, not a portrait of an aircraft that left ten minutes ago.
- Boundary rule, applied to every threshold: a value is **stale when it is
  strictly greater than** the limit. `position_age_s == max_position_age_s` is
  fresh. Tests assert both sides of each boundary.

Freshness gates, and why these numbers:

| Config | Default | Rationale |
| --- | --- | --- |
| `max_position_age_s` | 10.0 | 500 kt is 257 m/s, so 10 s of staleness is ≤ 2.6 km of position error inside a 15 km gate. |
| `max_message_age_s` | 30.0 | An aircraft transmitting but not updating position is either a Mode S-only track or one we should not draw. readsb's 60 s retention is twice this. |
| `max_snapshot_age_s` | 15.0 | The file is rewritten about once per second; 15 s of silence means the decoder is stalled. |

## 4. Home coordinates

```toml
[home]
lat = 22.3193    # decimal degrees, WGS84, -90..90
lon = 114.1694   # decimal degrees, WGS84, -180..180
```

- Home is **required and explicit**. There is no default and no inference. If it
  is absent the result is `unconfigured` (`reason="home_not_configured"`); the
  renderer draws the empty-sky state. Guessing a location would silently produce
  a wrong portrait.
- `receiver.json`'s `lat`/`lon` are **not** used, even when present: they are
  optional, describe the receiver rather than the viewer, are unset on many
  installs, and would make selection change whenever a feeder is reconfigured.
- Values are validated as finite numbers in range, and rejected rather than
  clamped. `-0.0`, integers and floats are all accepted. A string such as
  `"22.3"` is a configuration problem (`unconfigured`, `reason="config_invalid"`),
  not something to coerce.
- Home elevation is not part of v1. Distance is ground distance; elevation is
  only relevant to altitude filtering, which is explicitly out of scope (§11).

## 5. Proximity and ranking

### 5.1 Distance

Great-circle (haversine) distance on a sphere of mean Earth radius
**6 371 008.8 m**:

```text
φ1, λ1 = radians(home.lat), radians(home.lon)
φ2, λ2 = radians(lat),      radians(lon)
a  = sin((φ2-φ1)/2)² + cos(φ1)·cos(φ2)·sin((λ2-λ1)/2)²
d  = 2 · 6 371 008.8 · asin(min(1.0, sqrt(a)))
```

- The `min(1.0, …)` clamp guards against floating-point overshoot for nearby and
  antipodal points. Identical coordinates give exactly `0.0`.
- Reported as `distance_m` (float, metres) and `distance_nm = distance_m / 1852`.
- Accuracy: the spherical model differs from WGS84 geodesics by a few tenths of
  a percent, i.e. tens of metres at 15 km. That is well inside a gate whose
  inputs are already ±2.6 km uncertain, and it is deterministic across platforms.
  A geodesic (Vincenty/Karney) implementation is not required and would add a
  dependency for no selection benefit.
- `max_distance_km` default **15.0** (8.099 nmi): at 10 000 m altitude, 15 km
  ground distance is 33.7° above the horizon; at 3 000 m it is 11.3°. Closer
  would drop most genuine overflights, farther would draw aircraft that are not
  overhead.

### 5.2 Ranking

Candidates that survive §6 are ordered by this key, ascending:

1. `distance_key_m = floor(distance_m + 0.5)` — integer metres, half-up.
   Rounding to the nearest metre absorbs sub-metre float noise for aircraft at
   practically the same position. Half-up is specified because Python's
   `round()` is banker's rounding and would make `.5` cases surprising.
2. `position_age_s` — the fresher position wins.
3. `hex` — lowercase, lexicographic, ascending.

`hex` is unique after deduplication (§6), so the key is a **total order**: the
winner is a pure function of the inputs, independent of array order, dict order,
locale, or Python hash seed. No randomness, no "first seen", no "largest
aircraft".

## 6. Rejection rules

Each entry in `aircraft` is evaluated once and either becomes a candidate or is
counted under exactly one reason. Reasons are checked in the order below; the
first match wins, so overlapping defects produce a stable count.

| # | Reason | Condition |
| --- | --- | --- |
| 1 | `invalid_record` | entry is not a JSON object |
| 2 | `invalid_hex` | `hex` missing, not a string, or not `^~?[0-9a-f]{6}$` (after lowercasing) |
| 3 | `duplicate_hex` | a valid record with this `hex` was already processed in this snapshot; the earlier record wins |
| 4 | `no_position` | `lat` or `lon` key absent (this is the positionless report) |
| 5 | `invalid_position` | `lat`/`lon` not a number (bools rejected), not finite, or out of range |
| 6 | `invalid_timestamp` | `seen_pos` absent or not a finite number; `seen` present but not a finite number |
| 7 | `stale_message` | `message_age_s > max_message_age_s` |
| 8 | `stale_position` | `position_age_s > max_position_age_s` |
| 9 | `ground` | on the ground and `ignore_ground` is true |
| 10 | `out_of_range` | `distance_m > max_distance_km × 1000` |

Notes:

- **Positionless reports are never rendered as overhead.** A Mode S track with
  no position cannot be placed, so it is excluded and counted, not dropped
  silently.
- A stale position is excluded even when the message stream is fresh: an
  aircraft whose `seen` is 0.2 s but whose `seen_pos` is 45 s is drawn from a
  position it left 45 s ago.
- `on_ground` is true iff `alt_baro == "ground"` (readsb documents this string
  sentinel; dump1090-fa emits it too) or `alt_baro` is a number ≤ 0 **and**
  `gs` is present and ≤ 30 kt —
  the second clause covers decoders that emit `0` instead of `"ground"` for
  surface traffic. Ground vehicles near the receiver would otherwise win every
  proximity contest.
- `alt_baro` being absent, `"ground"`, or a number does not affect eligibility
  beyond the on-ground test above. Altitude filtering is out of scope (§11).
- `type` is carried for annotation only. `tisb_*`, `adsr_*`, `mlat` and
  non-ICAO `~` addresses are **not** filtered: readsb's `type` is the best
  source tag, not a quality verdict, and a TIS-B target can still be a real
  overflight. Sites that must exclude them can filter downstream.
- An aircraft with more than one defect is not double-counted; the ordered table
  above is the tie-breaker.

## 7. Result states and graceful degradation

`select()` always returns a result. File-system, JSON, schema and configuration
problems are data outcomes, not exceptions; only wrong argument *types* raise
(`TypeError`/`ValueError` from `__post_init__`).

| `state` | `reason` | Meaning |
| --- | --- | --- |
| `ok` | `None` | exactly one aircraft selected |
| `empty_sky` | `None` | input valid, nothing eligible |
| `stale_input` | `feed_stalled` | snapshot older than `max_snapshot_age_s` |
| `missing_input` | `file_not_found`, `permission_denied`, `io_error` | decoder file unreadable |
| `invalid_input` | `json_decode`, `not_an_object`, `aircraft_not_list`, `invalid_now` | file readable but unusable |
| `unconfigured` | `home_not_configured`, `config_invalid` | no usable home position |

Rules:

- Exactly one state per result. Precedence when several conditions hold:
  `unconfigured` → `missing_input` / `invalid_input` → `stale_input` →
  `empty_sky` / `ok`.
- Every state other than `ok` is rendered as the empty-sky artwork. States are
  for logging and diagnostics, not for drawing error text on a 7.3-inch panel.
- `aircraft` is `None` unless `state == "ok"`. Never a partial or mocked value.
- `rejected` is a mapping of reason → count containing only non-zero entries,
  so its sum plus `eligible_count` equals `considered_count`.
- An empty `aircraft` array is valid input and yields `empty_sky`, not
  `invalid_input`. Missing keys, wrong types, `null`, truncated JSON and an
  empty file are `invalid_input`/`missing_input` respectively.
- `stale_input` outranks `empty_sky`: a dead feed and a quiet sky are different
  operator problems and the state must distinguish them.
- `unconfigured` outranks the input states: with no home there is nothing to
  evaluate, and the message should point at configuration.

## 8. Component interface

Python 3.11+ (Raspberry Pi OS Bookworm). Suggested layout; only the exported
names in §8.5 are normative.

```text
phlight/aircraft/__init__.py      # public exports
phlight/aircraft/model.py         # dataclasses, state and reason constants
phlight/aircraft/source.py        # read_snapshot()
phlight/aircraft/selection.py     # distance_m(), select(), select_from_file()
phlight/aircraft/config.py        # load_config()
tests/aircraft/                   # fixture tests (other card)
tests/fixtures/aircraft/*.json
```

### 8.1 Data model

```python
@dataclass(frozen=True, slots=True)
class HomeLocation:
    lat: float
    lon: float

@dataclass(frozen=True, slots=True)
class SelectionConfig:
    home: HomeLocation | None = None
    max_distance_km: float = 15.0
    max_position_age_s: float = 10.0
    max_message_age_s: float = 30.0
    max_snapshot_age_s: float = 15.0
    ignore_ground: bool = True

@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    state: str                 # "ok" | "missing_input" | "invalid_input"
    file_now: float | None
    aircraft: tuple[dict, ...] # raw entries, undocumented order, may be empty
    error: str | None          # reason code when state != "ok"

@dataclass(frozen=True, slots=True)
class AircraftReport:
    hex: str
    callsign: str | None
    lat: float
    lon: float
    distance_m: float
    distance_nm: float
    position_age_s: float
    message_age_s: float
    altitude_ft: int | None    # None for absent or "ground"
    on_ground: bool
    track_deg: float | None
    ground_speed_kt: float | None
    category: str | None
    source_type: str | None

@dataclass(frozen=True, slots=True)
class SelectionResult:
    state: str
    aircraft: AircraftReport | None
    reason: str | None
    snapshot_time: float | None   # the file's now
    evaluated_at: float           # the injected now
    snapshot_age_s: float | None
    considered_count: int
    eligible_count: int
    rejected: Mapping[str, int]
```

`callsign` is `flight` with trailing spaces stripped (`"BAW123  "` →
`"BAW123"`); an all-blank `flight` becomes `None`. `altitude_ft` is
`alt_baro` rounded half-up to `int` when numeric, else `None`.

### 8.2 Source

```python
def read_snapshot(path: str | os.PathLike[str]) -> SourceSnapshot: ...
```

- Reads and parses `path` once. No caching, no watching, no retries, no clock
  access.
- `FileNotFoundError` → `missing_input`/`file_not_found`;
  `PermissionError` → `missing_input`/`permission_denied`; any other `OSError`
  → `missing_input`/`io_error`; `json.JSONDecodeError` or a non-object document
  → `invalid_input`/`json_decode`/`not_an_object`; `aircraft` absent or not a
  list → `invalid_input`/`aircraft_not_list`; `now` missing or out of range →
  `invalid_input`/`invalid_now`.
- A snapshot in a non-`ok` state has `file_now=None` and `aircraft=()`.

### 8.3 Selection

```python
def distance_m(home_lat: float, home_lon: float, lat: float, lon: float) -> float: ...

def select(snapshot: SourceSnapshot, config: SelectionConfig, *, now: float) -> SelectionResult: ...

def select_from_file(
    path: str | os.PathLike[str], config: SelectionConfig, *, now: float
) -> SelectionResult: ...
```

`now` is keyword-only and mandatory: tests cannot forget to control time, and
production code must pass `time.time()` explicitly. `select_from_file` is
`select(read_snapshot(path), config, now=now)`.

A snapshot whose `state` is not `"ok"` propagates that state and reason
unchanged, with `evaluated_at=now` and zero counts. A hand-built snapshot with
`state="ok"` but `file_now=None` is treated as `invalid_input`/`invalid_now`
rather than raising: the component must not depend on `read_snapshot` having
been the only producer.

Validation order inside `select()` follows §7: `unconfigured` first, then the
input states, then `stale_input`, then `empty_sky`/`ok`.

### 8.4 Configuration

```python
def load_config(mapping: Mapping[str, Any], *, environ: Mapping[str, str] | None = None
) -> tuple[SelectionConfig, tuple[str, ...]]: ...
```

Returns the config plus a tuple of problem codes (`"home_lat_invalid"`,
`"max_distance_invalid"`, …). It never raises and never coerces a
stringly-typed number; an invalid field falls back to its default with
`home=None` when the home block itself is unusable. `select()` treats a
non-empty problem tuple as `unconfigured`/`config_invalid`.

Precedence, highest first: explicit argument to the caller's own CLI →
environment → config file → defaults.

| Setting | Config key | Environment variable |
| --- | --- | --- |
| source path | `source.aircraft_json` | `PHLIGHT_AIRCRAFT_JSON` |
| home latitude | `home.lat` | `PHLIGHT_HOME_LAT` |
| home longitude | `home.lon` | `PHLIGHT_HOME_LON` |
| distance gate | `selection.max_distance_km` | `PHLIGHT_MAX_DISTANCE_KM` |
| position freshness | `selection.max_position_age_s` | — |
| message freshness | `selection.max_message_age_s` | — |
| snapshot freshness | `selection.max_snapshot_age_s` | — |
| ground traffic | `selection.ignore_ground` | — |

Default `/etc/phlight/config.toml`, overridable with `--config`:

```toml
[source]
aircraft_json = "/run/readsb/aircraft.json"

[home]
lat = 22.3193
lon = 114.1694

[selection]
max_distance_km = 15.0
max_position_age_s = 10.0
max_message_age_s = 30.0
max_snapshot_age_s = 15.0
ignore_ground = true
```

`load_config` takes the already-parsed mapping so that file discovery, TOML
parsing and CLI plumbing stay outside the selection component and can be tested
separately.

### 8.5 Public exports

`from phlight.aircraft import ...` must provide: `HomeLocation`,
`SelectionConfig`, `SourceSnapshot`, `AircraftReport`, `SelectionResult`,
`read_snapshot`, `select`, `select_from_file`, `distance_m`, `load_config`, and
the reason/state constants. State and reason values are plain lowercase strings
so tests may compare against literals; a `StrEnum` is acceptable only if its
values are identical.

## 9. Determinism

- Same `(snapshot, config, now)` ⇒ identical `SelectionResult` on any platform
  and any run. Nothing consults the system clock, the environment, the file
  mtime, `dict` iteration order or randomness.
- Array order affects only which duplicate record wins (`duplicate_hex` keeps
  the first) and the order of `rejected` counts, never the winner.
- Distance assertions in tests should use a tolerance (`abs=0.5` m); ranking
  assertions must use exact equality on `hex`.

## 10. Fixture requirements

The test card writes these against §8 only, with `now = 1760000000.0` and no
network, no receiver, no sleeping. Minimum coverage:

1. straightforward nearest-aircraft win with several in range;
2. two candidates at the same `distance_key_m` ⇒ fresher position wins, then
   lower `hex`;
3. array order reversed ⇒ same winner;
4. `lat`/`lon` absent ⇒ `no_position`, empty sky;
5. `seen_pos` 9.9 s fresh vs 10.0 s fresh vs 10.1 s stale;
6. `seen` 30.1 s ⇒ `stale_message` while position is fresh;
7. `alt_baro: "ground"` and `alt_baro: 0` with `gs: 5` ⇒ `ground`;
8. `distance_m` just inside and just outside 15 km;
9. `now` in the file 20 s behind the injected clock ⇒ `stale_input`;
10. `now` absent, `now` in milliseconds, `aircraft` not a list, truncated JSON,
    empty file, missing file ⇒ each documented state;
11. home absent, home out of range, home as a string ⇒ `unconfigured`;
12. empty `aircraft` array and `aircraft: []` with all entries rejected ⇒
    `empty_sky` with `rejected` accounting that sums to `considered_count`;
13. a real recorded `aircraft.json` excerpt committed as a fixture, exercising
    the same code paths as live data.

## 11. Out of scope / separate work

- **Real receiver validation.** Fixtures prove logic, not reception. Card
  `t_92dd4604` criterion 1 — antenna in the intended wall position, observed
  aircraft, documented range — needs hardware and is not satisfied by anything
  here.
- Network and vendor sources: readsb HTTP API, FlightAware/ADS-B Exchange,
  any third-party service. The local file is the only source in v1.
- Aircraft type, operator, registration or livery lookup, and any `--db-file`
  metadata. Note the upstream database flag `LADD` before adding metadata
  lookups later.
- Altitude/elevation filtering, range rings, multi-receiver fusion, history
  files (`history_N.json`), trace files, persistence of past selections.
- Display cadence and e-paper refresh policy; this contract only answers "which
  aircraft, if any".
- Anything that assumes a specific panel resolution or artwork layout.

## 12. Rejected alternatives

| Alternative | Why rejected |
| --- | --- |
| Read `receiver.json` for home | Optional, may be unset, describes the receiver not the viewer (§4). |
| Use aircraft `seen` as position freshness | A fresh message can carry a stale position; `seen_pos` exists for this. |
| Trust the array membership as "recent" | Retention is ~60 s (readsb) vs ~5 min (dump1090-fa) (§2.3). |
| Auto-probe `/run/*/aircraft.json` | Two decoders can coexist; selection would depend on install order. |
| `round()` for the distance key | Banker's rounding makes `.5` ties non-obvious (use `floor(x+0.5)`). |
| Geodesic distance (Vincenty/Karney) | Tens of metres of gain against ±2.6 km position uncertainty; extra dependency. |
| Return `None` / raise on missing data | Callers would each invent an empty-sky policy; states keep it in one place. |
| Pick the highest / fastest / most interesting aircraft | Not what "overhead" means; the brief asks for a documented distance rule. |