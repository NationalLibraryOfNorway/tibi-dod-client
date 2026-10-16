"""Reading the Reading System declaration from a file.

The XML parsing itself is an adapter's job (it needs lxml and the local
schemas); the application layer only names what it must do and what can go
wrong. Use cases do not print and do not exit.
"""

from __future__ import annotations

from collections.abc import Callable

from dod.domain.v1 import ReadingSystemAttributes


class ReadingSystemError(Exception):
    """A Reading System declaration could not be read or does not conform."""


type ReadingSystemParser = Callable[[bytes], ReadingSystemAttributes]
"""Parses and schema-validates a `readingSystemAttributes` document.

Raises `ReadingSystemError`, naming every finding, when it does not conform.
"""
