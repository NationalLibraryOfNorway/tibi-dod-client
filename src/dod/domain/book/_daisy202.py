"""The Playlist of a DAISY 2.02 book (ADR 0009).

`master.smil` gives the order of the content SMIL files if the book has one,
otherwise the order in which `ncc.html` first links to them. Every `audio`
element of those files, nested `seq` included, becomes a Clip in document
order. There is no fallback to file names or to the `resources` order. All of
it is untrusted input: parsed without entities, DTDs or network access, and
every path in it is validated like a `localURI`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

from lxml import etree

from dod.domain.book._model import BookError, BookErrorKind, Clip, Playlist
from dod.domain.book._paths import local_uri_segments

Reader = Callable[[str], bytes | None]
"""Gives the bytes of a file of the book by its path, or None if it is missing."""

MASTER = "master.smil"
NCC = "ncc.html"

_COUNT = re.compile(r"(\d+(?:\.\d+)?)(h|min|s|ms)?")
_FULL_CLOCK = re.compile(r"(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)")
_SHORT_CLOCK = re.compile(r"(\d+):(\d{1,2}(?:\.\d+)?)")
_UNIT_SECONDS = {"h": 3600.0, "min": 60.0, "s": 1.0, "ms": 0.001, None: 1.0}


def daisy202_playlist(read: Reader) -> Playlist:
    """The Playlist of a book, or `BookError` saying why it has none."""
    smils = _content_smils(read)
    clips: list[Clip] = []
    for path in smils:
        for element in _parse(path, _require(read, path), strict=True).iter():
            if _name(element) == "audio":
                clips.append(_clip(path, element))
    if not clips:
        raise BookError(
            BookErrorKind.NO_SMIL,
            "the SMIL files of the book have no audio to play",
        )
    return Playlist(tuple(clips))


def _content_smils(read: Reader) -> list[str]:
    """The content SMIL files in playing order, each once."""
    master = read(MASTER)
    if master is not None:
        found = [
            element.get("src", "")
            for element in _parse(MASTER, master, strict=True).iter()
            if _name(element) == "ref"
        ]
        origin, base = MASTER, ""
    else:
        ncc = read(NCC)
        if ncc is None:
            raise BookError(
                BookErrorKind.NO_SMIL,
                "the book has neither master.smil nor ncc.html, so there is no "
                "order to play it in (an audioOnly book has none); `dod` does not "
                "guess from file names",
            )
        found = [
            href
            for element in _parse(NCC, ncc, strict=False).iter()
            if _name(element) == "a"
            and (href := element.get("href", ""))
            .split("#", 1)[0]
            .lower()
            .endswith(".smil")
        ]
        origin, base = NCC, ""
    paths: dict[str, None] = {}
    for reference in found:
        paths[_join(base, reference.split("#", 1)[0], origin)] = None
    if not paths:
        raise BookError(
            BookErrorKind.NO_SMIL,
            f"{origin} links to no SMIL file, so it gives no order",
        )
    return list(paths)


def _clip(smil: str, element: etree._Element) -> Clip:
    base = smil.rpartition("/")[0]
    file = _join(base, element.get("src", ""), smil)
    begin = _time(smil, element, ("clip-begin", "clipBegin"))
    end = _time(smil, element, ("clip-end", "clipEnd"))
    if end is not None and end < (begin or 0.0):
        raise BookError(
            BookErrorKind.MALFORMED,
            f"{smil}: a clip of {file} ends ({end}s) before it begins ({begin}s)",
        )
    return Clip(file, begin or 0.0, end)


def _time(smil: str, element: etree._Element, names: tuple[str, ...]) -> float | None:
    for name in names:
        value = element.get(name)
        if value is not None:
            seconds = _seconds(value)
            if seconds is None:
                raise BookError(
                    BookErrorKind.MALFORMED,
                    f"{smil}: {name}={value[:40]!r} is not a time `dod` can read",
                )
            return seconds
    return None


def _seconds(value: str) -> float | None:
    """A SMIL clock or time count (`npt=` optional) in seconds; None if unreadable."""
    text = value.strip().removeprefix("npt=").strip()
    if match := _FULL_CLOCK.fullmatch(text):
        hours, minutes, seconds = match.groups()
        total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif match := _SHORT_CLOCK.fullmatch(text):
        minutes, seconds = match.groups()
        total = int(minutes) * 60 + float(seconds)
    elif match := _COUNT.fullmatch(text):
        number, unit = match.groups()
        total = float(number) * _UNIT_SECONDS[unit]
    else:
        return None
    return total if math.isfinite(total) else None


def _join(base: str, reference: str, origin: str) -> str:
    """A path inside the book named by `reference` in `origin`, or `BookError`."""
    segments, problem = local_uri_segments(reference)
    if problem is not None or segments is None:
        raise BookError(
            BookErrorKind.UNSAFE_PATH,
            f"{origin}: the path {_shown(reference)} is refused: {problem}",
        )
    return "/".join(([base] if base else []) + list(segments))


def _shown(text: str) -> str:
    return repr(text if len(text) <= 60 else text[:57] + "...")


def _require(read: Reader, path: str) -> bytes:
    content = read(path)
    if content is None:
        raise BookError(
            BookErrorKind.MISSING_FILE,
            f"{path} is named by the book's structure but is not in the book",
        )
    return content


def _name(element: etree._Element) -> str:
    """The local name of an element; comments and instructions have none."""
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def _parse(path: str, content: bytes, *, strict: bool) -> etree._Element:
    if b"<!ENTITY" in content:
        raise BookError(
            BookErrorKind.MALFORMED,
            f"{path} declares entities, which `dod` does not expand",
        )
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        recover=not strict,
    )
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError as error:
        raise BookError(
            BookErrorKind.MALFORMED, f"{path} is not well-formed XML: {error.msg}"
        ) from None
    if root is None:
        raise BookError(BookErrorKind.MALFORMED, f"{path} has no content")
    return root
