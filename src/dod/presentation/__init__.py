"""Presentation layer: the CLI and the TUI.

May import the application and domain packages, never `dod.infrastructure`.
"""

from dod.presentation._diagnostics import ActivityLog
from dod.presentation._globals import Terminal
from dod.presentation._launch import DownloadSettings, create_tui
from dod.presentation._masking import MaskPolicy, mask, mask_url
from dod.presentation.cli import create_app

__all__ = [
    "ActivityLog",
    "DownloadSettings",
    "MaskPolicy",
    "Terminal",
    "create_app",
    "create_tui",
    "mask",
    "mask_url",
]
