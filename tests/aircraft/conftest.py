"""Shared test fixtures and constants for phlight.aircraft tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from phlight.aircraft import HomeLocation, SelectionConfig, SourceSnapshot

#: Controlled caller timestamp required by contract §10 for synthetic fixtures.
CONTROLLED_NOW = 1760000000.0

#: Captured file timestamp in recorded_readsb_perpignan_2022.json.
RECORDED_NOW = 1659548165.407

#: Reference viewer location in Kowloon, Hong Kong (contract §4 / §8.4).
HONG_KONG_HOME = HomeLocation(lat=22.3193, lon=114.1694)

#: Reference viewer location near Perpignan, France for recorded_readsb_perpignan_2022.json.
PERPIGNAN_HOME = HomeLocation(lat=42.54, lon=2.52)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "aircraft"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def hk_config() -> SelectionConfig:
    return SelectionConfig(home=HONG_KONG_HOME)


@pytest.fixture
def perpignan_config() -> SelectionConfig:
    return SelectionConfig(home=PERPIGNAN_HOME)


def make_snapshot(
    aircraft: list[dict[str, Any]] | tuple[Any, ...],
    *,
    file_now: float | None = CONTROLLED_NOW,
    state: str = "ok",
    error: str | None = None,
) -> SourceSnapshot:
    """Build an in-memory SourceSnapshot for controlled unit tests."""
    return SourceSnapshot(
        state=state,
        file_now=file_now,
        aircraft=tuple(aircraft) if isinstance(aircraft, (list, tuple)) else aircraft,  # type: ignore[arg-type]
        error=error,
    )
