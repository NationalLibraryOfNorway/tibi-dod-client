"""The Playlist of an EPUB 3 book with media overlays (ADR 0009).

`META-INF/container.xml` names the package document; its spine gives the order
of the content documents, and each one's `media-overlay` attribute names the
manifest item that is its SMIL overlay. Every `audio` element of those overlays,
nested `seq` included, becomes a Clip in document order; an overlay that several
content documents name is played once, where it first comes. Spine items
without an overlay are skipped, but a book where none has one is refused: there
is nothing to play, and `dod` does not read the text aloud. Untrusted input, as
for DAISY 2.02.
"""

from __future__ import annotations

from dod.domain.book._daisy202 import (
    Reader,
    _name,
    _parse,
    _require,
    join_path,
    smil_clips,
)
from dod.domain.book._model import BookError, BookErrorKind, Playlist

CONTAINER = "META-INF/container.xml"


def epub3_playlist(read: Reader) -> Playlist:
    """The Playlist of a book, or `BookError` saying why it has none."""
    package = _package_path(read)
    root = _parse(package, _require(read, package), strict=True)
    base = package.rpartition("/")[0]
    manifest: dict[str, tuple[str, str | None]] = {}
    spine: list[str] = []
    for element in root.iter():
        name = _name(element)
        if name == "item" and (id := element.get("id")):
            manifest.setdefault(
                id, (element.get("href", ""), element.get("media-overlay"))
            )
        elif name == "itemref":
            spine.append(element.get("idref", ""))
    overlays: dict[str, None] = {}
    for idref in spine:
        entry = manifest.get(idref)
        if entry is None:
            raise BookError(
                BookErrorKind.MALFORMED,
                f"{package}: the spine names {idref[:40]!r}, not in the manifest",
            )
        if entry[1] is None:
            continue
        target = manifest.get(entry[1])
        if target is None:
            raise BookError(
                BookErrorKind.MALFORMED,
                f"{package}: the media-overlay {entry[1][:40]!r} of {idref[:40]!r} "
                "is not in the manifest",
            )
        overlays[join_path(base, target[0], package, parents=True)] = None
    if not overlays:
        raise BookError(
            BookErrorKind.NO_SMIL,
            "the EPUB has no media overlay on any item of its spine, so there is "
            "no audio to play (a text-only EPUB cannot be played)",
        )
    return Playlist(smil_clips(read, list(overlays), parents=True))


def _package_path(read: Reader) -> str:
    container = read(CONTAINER)
    if container is None:
        raise BookError(
            BookErrorKind.NO_SMIL,
            f"the book has no {CONTAINER}, so there is no package document to "
            "take an order from",
        )
    for element in _parse(CONTAINER, container, strict=True).iter():
        if _name(element) == "rootfile" and (path := element.get("full-path")):
            return join_path("", path, CONTAINER)
    raise BookError(BookErrorKind.MALFORMED, f"{CONTAINER} names no package document")
