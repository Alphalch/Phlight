"""Phlight: a framed portrait of the aircraft flying overhead.

The first component is :mod:`phlight.aircraft`, which turns a local ADS-B
decoder's ``aircraft.json`` into a single proximity selection. No network or
vendor service is involved.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"