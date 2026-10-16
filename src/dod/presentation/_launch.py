"""Builds the terminal user interface without importing Textual up front."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dod.application import OpenPlayer, SessionManager

if TYPE_CHECKING:
    from textual.app import App

    from dod.presentation._diagnostics import ActivityLog


@dataclass(frozen=True)
class DownloadSettings:
    """Where and under which trust the TUI downloads, as `dod download` decides."""

    service_url: str
    directory_for: Callable[[str], Path | None]
    """The book directory for a contentID; none when there is no place for it."""
    trust_host: bool = False
    insecure: bool = False


def create_tui(
    manager: SessionManager,
    downloads: DownloadSettings | None = None,
    *,
    open_player: OpenPlayer | None = None,
    log: ActivityLog | None = None,
) -> App[None]:
    """The terminal user interface over `manager`'s Service and user.

    Without `downloads` the resource screen lists files but cannot download,
    and no book is played (there is no directory to play from). `open_player`
    opens the audio player the first time a book is played; it may raise
    `PlayerUnavailable`, which is shown in the player bar, and without it
    nothing plays. `log` is the `ActivityLog` the manager's ports report to
    (`ActivityLog.wrap`); the log panel shows it, always masked.
    Needs the optional Textual (`dod-client[tui]`) and raises `ImportError`
    without it; Textual is imported here and not at the top so that the rest of
    `dod` works without it.
    """
    from dod.presentation._tui import DodTui

    return DodTui(manager, downloads, open_player, log)
