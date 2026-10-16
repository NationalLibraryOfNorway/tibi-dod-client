"""Builds the terminal user interface without importing Textual up front."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from dod.application import SessionManager

if TYPE_CHECKING:
    from textual.app import App


@dataclass(frozen=True)
class DownloadSettings:
    """Where and under which trust the TUI downloads, as `dod download` decides."""

    service_url: str
    directory_for: Callable[[str], Path | None]
    """The book directory for a contentID; none when there is no place for it."""
    trust_host: bool = False
    insecure: bool = False


def create_tui(
    manager: SessionManager, downloads: DownloadSettings | None = None
) -> App[None]:
    """The terminal user interface over `manager`'s Service and user.

    Without `downloads` the resource screen lists files but cannot download.
    Needs the optional Textual (`dod-client[tui]`) and raises `ImportError`
    without it; Textual is imported here and not at the top so that the rest of
    `dod` works without it.
    """
    from dod.presentation._tui import DodTui

    return DodTui(manager, downloads)
