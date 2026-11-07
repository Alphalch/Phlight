"""Pytest configuration for Phlight renderer and integration tests.

Ensures ``phlight.aircraft`` (published on ``main``) is importable even when
running tests on an unmerged ``feat/aircraft-portrait-renderer`` checkout, so
selector -> renderer integration tests always exercise the real repository
selector and renderer modules without touching the working tree.
"""

from __future__ import annotations

import atexit
import importlib
import shutil
import subprocess
import tempfile
from pathlib import Path

import phlight

_AIRCRAFT_FILES = (
    "__init__.py",
    "model.py",
    "source.py",
    "selection.py",
    "config.py",
)


def _ensure_aircraft_package() -> None:
    try:
        importlib.import_module("phlight.aircraft")
        return
    except ModuleNotFoundError:
        pass

    repo_root = Path(__file__).resolve().parent.parent
    for ref in ("origin/main", "main"):
        try:
            blobs = {
                name: subprocess.check_output(
                    ["git", "show", f"{ref}:phlight/aircraft/{name}"],
                    cwd=repo_root,
                    stderr=subprocess.DEVNULL,
                )
                for name in _AIRCRAFT_FILES
            }
        except (OSError, subprocess.CalledProcessError):
            continue

        tmp_root = Path(tempfile.mkdtemp(prefix="phlight_aircraft_pkg_"))
        atexit.register(shutil.rmtree, tmp_root, True)
        pkg_dir = tmp_root / "aircraft"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        for name, content in blobs.items():
            (pkg_dir / name).write_bytes(content)
        phlight.__path__.append(str(tmp_root))
        return


_ensure_aircraft_package()
