"""Presentation layer: the CLI (and later the TUI).

May import the application and domain packages, never `dod.infrastructure`.
"""

from dod.presentation._globals import Terminal
from dod.presentation._masking import MaskPolicy, mask, mask_url
from dod.presentation.cli import create_app

__all__ = ["MaskPolicy", "Terminal", "create_app", "mask", "mask_url"]
