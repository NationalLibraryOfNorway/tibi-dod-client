"""Playing a downloaded book: the Playlist from disk and the play controller.

Only files that are already on disk are played, never streamed (ADR 0009). The
audio device is behind the `Player` seam; `Playback` knows nothing about
`miniaudio`. A Player cannot pause or seek a running device, so pause, resume
and every jump are a stop and a restart from an offset in the file.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from dod.domain.book import (
    BookError,
    BookErrorKind,
    Playlist,
    daisy202_playlist,
    epub3_playlist,
)
from dod.domain.service import Observation

_MAX_STRUCTURE_BYTES = 16 * 1024 * 1024
_CONTINUOUS = 0.05
"""Clips of one file that are this close (seconds) play on without a restart."""


class AudioError(Exception):
    """A Player cannot play a file; the message says why."""


class PlayerUnavailable(Exception):
    """There is no audio playback on this system; the message says what is missing."""


class Player(Protocol):
    """One audio device. Positions are seconds from the start of the file."""

    def duration(self, path: Path) -> float:
        """The length of a file, or `AudioError` if it cannot be decoded."""
        ...

    def start(self, path: Path, offset: float) -> None:
        """Play `path` from `offset`, replacing what plays; returns at once."""
        ...

    def stop(self) -> None: ...

    def close(self) -> None:
        """Release the device."""
        ...

    def position(self) -> float:
        """Where in the file the playing has got to (a little ahead of what is
        heard: it counts the frames handed to the device)."""
        ...

    def finished(self) -> bool:
        """The playing reached the end of the file."""
        ...


OpenPlayer = Callable[[], Player]
"""Opens the Player, or raises `PlayerUnavailable`."""


class PlayRefused(Exception):
    """A book `dod` will not play as it is; the message says what to do."""

    def __init__(self, message: str, observations: tuple[Observation, ...] = ()):
        super().__init__(message)
        self.observations = observations


def open_book(directory: Path) -> Playlist:
    """The Playlist of the DAISY 2.02 or EPUB 3 book in `directory`.

    Raises `PlayRefused` if there is no such directory and `BookError` if the
    book has no usable structure. Files are read from inside the directory only.
    """
    if not directory.is_dir():
        raise PlayRefused(
            f"{directory} is not a directory: there is no local copy of the book "
            "(run `dod issue` and `dod download` first, or pass --directory)"
        )
    root = directory.resolve()

    def read(path: str) -> bytes | None:
        file = _inside(root, path)
        if file is None or not file.is_file():
            return None
        if file.stat().st_size > _MAX_STRUCTURE_BYTES:
            raise BookError(
                BookErrorKind.TOO_LARGE,
                f"{path} is larger than {_MAX_STRUCTURE_BYTES // 1024 // 1024} MiB",
            )
        return file.read_bytes()

    if (
        read("master.smil") is None
        and read("ncc.html") is None
        and read("META-INF/container.xml") is not None
    ):
        return epub3_playlist(read)
    return daisy202_playlist(read)


def _inside(root: Path, relative: str) -> Path | None:
    """The file `relative` names, if it is still inside `root` after links."""
    file = root.joinpath(*relative.split("/")).resolve()
    return file if file.is_relative_to(root) else None


class PlaybackState(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    FINISHED = "finished"


@dataclass(frozen=True)
class PlaybackStatus:
    state: PlaybackState
    clip_index: int
    """0-based, among all Clips."""
    clip_count: int
    file: str
    """The audio file's path within the book."""
    file_index: int
    """1-based, among the distinct files of the Playlist."""
    file_count: int
    elapsed: float
    """Seconds of Playlist time."""
    total: float


def prepare_playback(directory: Path, playlist: Playlist, player: Player) -> Playback:
    """Check that every audio file is there and playable, and measure them.

    Raises `PlayRefused` before anything is played: for a file that is missing
    (nothing is fetched here), one that leaves the book directory through a
    link, or one the Player cannot decode (with an Observation).
    """
    root = directory.resolve()
    paths: dict[str, Path] = {}
    missing: list[str] = []
    for name in playlist.files:
        resolved = _inside(root, name)
        if resolved is None:
            raise PlayRefused(f"{name} leaves the book directory through a link")
        if not resolved.is_file():
            missing.append(name)
        paths[name] = resolved
    if missing:
        shown = ", ".join(missing[:5]) + (
            f" (and {len(missing) - 5} more)" if len(missing) > 5 else ""
        )
        raise PlayRefused(
            f"audio files of the book are not on disk: {shown}; run "
            "`dod download` first (nothing is streamed or fetched while playing)"
        )
    durations: dict[str, float] = {}
    for name, path in paths.items():
        try:
            durations[name] = player.duration(path)
        except AudioError as error:
            raise PlayRefused(
                f"{name} cannot be played: {error}",
                (
                    Observation(
                        id="audio-format",
                        message=(
                            f"{name} is in a format the audio player cannot decode "
                            "(WAV, FLAC, MP3 and Ogg Vorbis are supported, AAC is not)"
                        ),
                    ),
                ),
            ) from None
    return Playback(playlist, paths, durations, player)


class Playback:
    """Plays a Playlist through a Player; the caller drives it with `tick`."""

    def __init__(
        self,
        playlist: Playlist,
        paths: dict[str, Path],
        durations: dict[str, float],
        player: Player,
    ) -> None:
        self._clips = playlist.clips
        self._files = playlist.files
        self._paths = paths
        self._durations = durations
        self._player = player
        self._ends: list[float] = []
        self._starts: list[float] = []
        total = 0.0
        for clip in self._clips:
            length = durations[clip.file]
            end = length if clip.end is None else min(clip.end, length)
            self._ends.append(max(end, clip.begin))
            self._starts.append(total)
            total += self._ends[-1] - clip.begin
        self._total = total
        self._state = PlaybackState.STOPPED
        self._index = 0
        self._at = 0.0
        """Where in the current file to resume while paused."""

    def start(self) -> None:
        self._begin(0, self._clips[0].begin)

    def stop(self) -> None:
        self._player.stop()
        self._state = PlaybackState.STOPPED

    def pause(self) -> None:
        if self._state is PlaybackState.PLAYING:
            self._at = self._player.position()
            self._player.stop()
            self._state = PlaybackState.PAUSED

    def resume(self) -> None:
        if self._state is PlaybackState.PAUSED:
            self._begin(self._index, self._at)

    def next(self) -> None:
        if self._state in _LIVE and self._index + 1 < len(self._clips):
            self._seek(self._index + 1, self._clips[self._index + 1].begin)

    def previous(self) -> None:
        if self._state in _LIVE:
            index = max(self._index - 1, 0)
            self._seek(index, self._clips[index].begin)

    def jump(self, seconds: float) -> None:
        """Move `seconds` (negative: back) in Playlist time, across Clips."""
        if self._state not in _LIVE:
            return
        target = min(max(self.status().elapsed + seconds, 0.0), self._total)
        if target >= self._total:
            self._player.stop()
            self._state = PlaybackState.FINISHED
            return
        for index, clip in enumerate(self._clips):
            length = self._ends[index] - clip.begin
            if self._starts[index] <= target < self._starts[index] + length:
                self._seek(index, clip.begin + target - self._starts[index])
                return

    def tick(self) -> None:
        """Move on to the next Clip if the playing has got to the end of this one."""
        if self._state is not PlaybackState.PLAYING:
            return
        position = self._player.position()
        if self._player.finished():
            position = max(position, self._durations[self._clips[self._index].file])
        while position >= self._ends[self._index]:
            if self._index + 1 == len(self._clips):
                self._player.stop()
                self._state = PlaybackState.FINISHED
                return
            current, following = self._clips[self._index], self._clips[self._index + 1]
            if (
                following.file == current.file
                and abs(following.begin - self._ends[self._index]) <= _CONTINUOUS
            ):
                self._index += 1
                continue
            self._begin(self._index + 1, following.begin)
            return

    def status(self) -> PlaybackStatus:
        clip = self._clips[self._index]
        if self._state is PlaybackState.FINISHED:
            elapsed = self._total
        else:
            position = (
                self._player.position()
                if self._state is PlaybackState.PLAYING
                else self._at
            )
            within = min(max(position, clip.begin), self._ends[self._index])
            elapsed = self._starts[self._index] + within - clip.begin
        return PlaybackStatus(
            state=self._state,
            clip_index=self._index,
            clip_count=len(self._clips),
            file=clip.file,
            file_index=self._files.index(clip.file) + 1,
            file_count=len(self._files),
            elapsed=elapsed,
            total=self._total,
        )

    def _begin(self, index: int, offset: float) -> None:
        self._index, self._at = index, offset
        self._player.start(self._paths[self._clips[index].file], offset)
        self._state = PlaybackState.PLAYING

    def _seek(self, index: int, offset: float) -> None:
        if self._state is PlaybackState.PLAYING:
            self._begin(index, offset)
        else:
            self._index, self._at = index, offset


_LIVE = frozenset({PlaybackState.PLAYING, PlaybackState.PAUSED})
