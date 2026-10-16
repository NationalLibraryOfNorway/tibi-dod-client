"""The TUI's player: the `Playback` of `dod play`, kept between screens.

No audio logic lives here: opening the Player, the Playlist, the checks and the
playing all come from the application layer, exactly as `dod play` uses them.
Only files that are already on disk are played (ADR 0009). Preparing a book
opens files and measures them, so it is meant for a worker thread; everything
else is called from the screen's thread.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from dod.application import (
    AudioError,
    BookError,
    OpenPlayer,
    Playback,
    PlaybackState,
    Player,
    PlayerUnavailable,
    PlayRefused,
    missing_files,
    open_book,
    prepare_playback,
)
from dod.presentation._diagnostics import ActivityLog
from dod.presentation._play import JUMP_SECONDS, status_line
from dod.presentation._text import plain

IDLE = "player: nothing playing (P plays the selected book)"


class PlayerControl:
    def __init__(
        self,
        open_player: OpenPlayer | None,
        directory_for: Callable[[str], Path | None] | None,
        log: ActivityLog | None = None,
    ) -> None:
        self._open_player = open_player
        self._directory_for = directory_for
        self._log = log
        self._player: Player | None = None
        self._playback: Playback | None = None
        self._problem: str | None = None

    def prepare(self, content_id: str) -> Playback | str:
        """The Playback of the book's local copy, or the reason there is none."""
        if self._open_player is None:
            return "audio playback is not available here"
        directory = (
            self._directory_for(content_id) if self._directory_for is not None else None
        )
        if directory is None:
            return (
                "no directory to play from: choose an Environment and a data "
                "directory (DOD_DATA_DIR) for `dod tui`"
            )
        if not directory.is_dir():
            return "there is no local copy of the book: download it first (f, then d)"
        try:
            if self._player is None:
                self._player = self._open_player()
            playlist = open_book(directory)
            absent = missing_files(directory, playlist)
            if absent:
                return (
                    f"{len(absent)} audio file(s) of the book are not on disk: "
                    "download them first (f, then d); nothing is streamed"
                )
            return prepare_playback(directory, playlist, self._player)
        except PlayerUnavailable as error:
            return plain(str(error))
        except PlayRefused as error:
            if self._log is not None:
                self._log.observe(error.observations)
            return plain(str(error))
        except BookError as error:
            return plain(str(error))
        except AudioError as error:
            return plain(f"playback failed: {error}")

    def adopt(self, playback: Playback) -> None:
        """Play `playback` instead of whatever plays now."""
        self.stop()
        self._playback = playback
        self._problem = None
        playback.start()

    def note(self, problem: str | None) -> None:
        self._problem = problem

    def line(self) -> str:
        if self._playback is None:
            return f"player: {self._problem}" if self._problem else IDLE
        status = self._playback.status()
        line = f"{status.state.value}  {status_line(status, plain)}"
        return f"{line}  ({self._problem})" if self._problem else line

    def stop(self) -> None:
        if self._playback is not None:
            self._playback.stop()

    def close(self) -> None:
        self.stop()
        if self._player is not None:
            self._player.close()
            self._player = None

    def tick(self) -> None:
        if self._playback is not None:
            self._playback.tick()

    def toggle(self) -> None:
        if self._playback is None:
            return
        if self._playback.status().state is PlaybackState.PAUSED:
            self._playback.resume()
        else:
            self._playback.pause()

    def next(self) -> None:
        if self._playback is not None:
            self._playback.next()

    def previous(self) -> None:
        if self._playback is not None:
            self._playback.previous()

    def forward(self) -> None:
        if self._playback is not None:
            self._playback.jump(JUMP_SECONDS)

    def back(self) -> None:
        if self._playback is not None:
            self._playback.jump(-JUMP_SECONDS)
