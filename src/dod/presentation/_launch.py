"""Builds the terminal user interface without importing Textual up front."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dod.application import SessionManager

if TYPE_CHECKING:
    from textual.app import App


def create_tui(manager: SessionManager) -> App[None]:
    """The terminal user interface over `manager`'s Service and user.

    Needs the optional Textual (`dod-client[tui]`) and raises `ImportError`
    without it; Textual is imported here and not at the top so that the rest of
    `dod` works without it.
    """
    from dod.presentation._tui import DodTui

    return DodTui(manager)
