"""The Playlist and its Clips, and the typed errors of deriving one."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class Clip:
    """One stretch of audio: a file of the book, from `begin` to `end` seconds."""

    file: str
    """The path of the audio file within the book, `/`-separated and decoded."""
    begin: float = 0.0
    end: float | None = None
    """None: to the end of the file (the SMIL gave no `clip-end`)."""


@dataclass(frozen=True)
class Playlist:
    """The playing order of a book: its Clips, in the order they are played."""

    clips: tuple[Clip, ...]

    @property
    def files(self) -> tuple[str, ...]:
        """The distinct audio files, in the order they are first played."""
        return tuple(dict.fromkeys(clip.file for clip in self.clips))


class BookErrorKind(StrEnum):
    NO_SMIL = "no-smil"
    """The book has no SMIL to take an order from (for example `audioOnly`)."""
    MISSING_FILE = "missing-file"
    """A file the order depends on is not there."""
    MALFORMED = "malformed"
    """A file is not well-formed or has a value that cannot be read."""
    UNSAFE_PATH = "unsafe-path"
    """A path inside the book is not a safe relative path."""
    TOO_LARGE = "too-large"
    """A file is larger than `dod` will read."""


class BookError(Exception):
    """A book that cannot give a Playlist; the message says why and what to do."""

    def __init__(self, kind: BookErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind
