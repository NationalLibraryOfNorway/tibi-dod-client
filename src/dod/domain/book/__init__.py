"""Pure: turns the bytes of a book's own structure into a Playlist (ADR 0009).

Knows nothing about DODP, files or audio. May import no other `dod` package.
"""

from dod.domain.book._daisy202 import Reader, daisy202_playlist
from dod.domain.book._epub3 import epub3_playlist
from dod.domain.book._model import BookError, BookErrorKind, Clip, Playlist
from dod.domain.book._paths import local_uri_segments

__all__ = [
    "BookError",
    "BookErrorKind",
    "Clip",
    "Playlist",
    "Reader",
    "daisy202_playlist",
    "epub3_playlist",
    "local_uri_segments",
]
