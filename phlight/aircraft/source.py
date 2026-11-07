"""Read one local decoder snapshot from disk.

Filesystem only: one path, read once, no discovery, no caching, no retries and
no clock access. ``readsb`` and ``dump1090-fa`` both write ``aircraft.json`` by
writing a temporary file and renaming it, so a read either sees a whole
document or fails outright.

See ``docs/aircraft-selection-contract.md`` sections 2 and 8.2.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .model import (
    REASON_AIRCRAFT_NOT_LIST,
    REASON_FILE_NOT_FOUND,
    REASON_INVALID_NOW,
    REASON_IO_ERROR,
    REASON_JSON_DECODE,
    REASON_NOT_AN_OBJECT,
    REASON_PERMISSION_DENIED,
    STATE_INVALID_INPUT,
    STATE_MISSING_INPUT,
    STATE_OK,
    SourceSnapshot,
    in_epoch_range,
)


def _failure(state: str, reason: str) -> SourceSnapshot:
    # A failed snapshot never carries partial data.
    return SourceSnapshot(state=state, file_now=None, aircraft=(), error=reason)


def read_snapshot(path: str | os.PathLike[str]) -> SourceSnapshot:
    """Read and parse ``path`` into a :class:`SourceSnapshot`.

    File-system and JSON problems are returned as states, never raised: a
    missing file is ``missing_input``, an unparsable or structurally wrong file
    is ``invalid_input``. Only wrong argument *types* raise (from
    :class:`pathlib.Path`).
    """

    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return _failure(STATE_MISSING_INPUT, REASON_FILE_NOT_FOUND)
    except PermissionError:
        return _failure(STATE_MISSING_INPUT, REASON_PERMISSION_DENIED)
    except OSError:
        # Includes IsADirectoryError, ENOSPC on a weird mount, EIO, ...
        return _failure(STATE_MISSING_INPUT, REASON_IO_ERROR)

    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _failure(STATE_INVALID_INPUT, REASON_JSON_DECODE)
    except RecursionError:  # pathological nesting; still not valid input
        return _failure(STATE_INVALID_INPUT, REASON_JSON_DECODE)

    if not isinstance(document, dict):
        return _failure(STATE_INVALID_INPUT, REASON_NOT_AN_OBJECT)

    aircraft = document.get("aircraft")
    if not isinstance(aircraft, list):
        return _failure(STATE_INVALID_INPUT, REASON_AIRCRAFT_NOT_LIST)

    file_now = document.get("now")
    if not in_epoch_range(file_now):
        return _failure(STATE_INVALID_INPUT, REASON_INVALID_NOW)

    return SourceSnapshot(
        state=STATE_OK,
        file_now=float(file_now),
        aircraft=tuple(aircraft),
        error=None,
    )