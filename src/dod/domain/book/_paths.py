"""Paths named inside a book: untrusted, and validated like a `localURI` (ADR 0008)."""

from __future__ import annotations

import re
from urllib.parse import unquote

_MAX_SEGMENT_BYTES = 255
_UNSAFE_CHARACTERS = frozenset('<>:"\\|?*')
_RESERVED_NAME = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)


def local_uri_segments(local_uri: str) -> tuple[tuple[str, ...] | None, str | None]:
    """The path segments of a `localURI`, or what is wrong with it.

    The text is percent-decoded first. Absolute paths, `.` and `..`, control
    characters, backslashes, drive letters, reserved device names and segments
    that Windows would alter are refused, so that a path that passes stays
    inside the book directory on every platform.
    """
    if not local_uri:
        return None, "it is empty"
    try:
        text = unquote(local_uri, errors="strict")
    except UnicodeDecodeError:
        return None, "its percent-encoding is not valid UTF-8"
    if any(ord(c) < 32 or ord(c) == 127 for c in text):
        return None, "it has a control character"
    if text.startswith("/"):
        return None, "it is an absolute path"
    if bad := _UNSAFE_CHARACTERS & set(text):
        return None, f"it has the character {''.join(sorted(bad))!r}"
    segments = tuple(text.split("/"))
    for segment in segments:
        if segment == "":
            return None, "it has an empty path segment"
        if segment in {".", ".."}:
            return None, f"it has a {segment!r} segment"
        if segment != segment.strip() or segment.endswith("."):
            return None, "a segment starts or ends with a space or ends with a dot"
        if _RESERVED_NAME.match(segment):
            return None, f"{segment!r} is a reserved file name"
        if len(segment.encode()) > _MAX_SEGMENT_BYTES:
            return None, "a segment is too long"
    return segments, None


def resolve_reference(
    base: tuple[str, ...], reference: str
) -> tuple[tuple[str, ...] | None, str | None]:
    """The path segments `reference` names from the directory `base`, or what is wrong.

    Like `local_uri_segments`, except that `..` may climb out of `base` (an EPUB
    overlay in `OEBPS/smil/` names `../audio/a.mp3`), never out of the book. A
    percent-encoded `/` or `..` is refused, as it is there.
    """
    if not reference:
        return None, "it is empty"
    if reference.startswith("/"):
        return None, "it is an absolute path"
    stack = list(base)
    for raw in reference.split("/"):
        if raw == ".":
            continue
        if raw == "..":
            if not stack:
                return None, "it climbs out of the book"
            stack.pop()
            continue
        segments, problem = local_uri_segments(raw)
        if problem is not None or segments is None:
            return None, problem
        if len(segments) != 1:
            return None, "it has an encoded path separator"
        stack.append(segments[0])
    return tuple(stack), None
