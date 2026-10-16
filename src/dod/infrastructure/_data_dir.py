"""Where downloaded books live: `DOD_DATA_DIR`, else the platform's data directory."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from platformdirs import user_data_dir


def data_directory(environ: Mapping[str, str]) -> Path:
    """The data directory for `DOD_DATA_DIR`, or the platform default without it."""
    return Path(environ.get("DOD_DATA_DIR") or user_data_dir("dod", appauthor=False))
