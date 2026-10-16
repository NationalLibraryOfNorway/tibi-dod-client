"""Presentation layer: the CLI (and later the TUI).

May import the application and domain packages, never `dod.infrastructure`.
"""

from dod.presentation.cli import create_app

__all__ = ["create_app"]
