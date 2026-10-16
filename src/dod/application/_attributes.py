"""Reading the Reading System declaration from a file.

The XML parsing itself is an adapter's job (it needs lxml and the local
schemas); the application layer only names what it must do and what can go
wrong. Use cases do not print and do not exit.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from dod.domain.v1 import ReadingSystemAttributes


class ReadingSystemError(Exception):
    """A Reading System declaration could not be read or does not conform."""


type ReadingSystemParser = Callable[[bytes], ReadingSystemAttributes]
"""Parses and schema-validates a `readingSystemAttributes` document.

Raises `ReadingSystemError`, naming every finding, when it does not conform.
"""


class Finding(Protocol):
    """One way in which a document does not conform to a schema."""

    @property
    def line(self) -> int: ...

    @property
    def message(self) -> str: ...


type DocumentValidator = Callable[[bytes], Sequence[Finding]]
"""Checks a document against the local schemas; no findings means it is valid.

Used for the bookmark set file `dod bookmarks set` sends.
"""
