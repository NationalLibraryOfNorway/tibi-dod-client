"""Bookmark sets and key exchange objects as XML: reading, summarising, checking.

Shared by the HTTP adapter and the in-memory adapter. Everything read from a
Service is read leniently (Services store anything); everything sent is parsed
without resolving entities or touching the network.
"""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from typing import Any

from lxml import etree

from dod.application import Finding
from dod.domain.v1 import BookmarkSet, Lastmark
from dod.infrastructure._schema import validate_document

BOOKMARK_NS = "http://www.daisy.org/z3986/2005/bookmark/"
KEY_EXCHANGE_NS = "http://www.daisy.org/DRM/2005/KeyExchange"


class _Finding:
    def __init__(self, line: int, message: str) -> None:
        self.line = line
        self.message = message


def _bm(name: str) -> str:
    return f"{{{BOOKMARK_NS}}}{name}"


def _text(element: etree._Element, name: str) -> str | None:
    """The stripped text of a child; absent and `xsi:nil` are both `None`."""
    child = element.find(_bm(name))
    if child is None or child.text is None:
        return None
    return child.text.strip()


def element_text(element: etree._Element) -> str:
    """The element as text, without the namespace declarations it only inherits
    from the SOAP envelope around it."""
    copy = deepcopy(element)
    etree.cleanup_namespaces(copy)
    return etree.tostring(copy, encoding="unicode")


def bookmark_set(element: etree._Element) -> BookmarkSet:
    """A summary of a `bookmarkSet` element, with the element's text kept whole."""
    mark = element.find(_bm("lastmark"))
    title = element.find(f"{_bm('title')}/{_bm('text')}")
    return BookmarkSet(
        xml=element_text(element),
        title=None if title is None or title.text is None else title.text.strip(),
        uid=_text(element, "uid"),
        lastmark=(
            None
            if mark is None
            else Lastmark(
                ncx_ref=_text(mark, "ncxRef"),
                uri=_text(mark, "URI"),
                time_offset=_text(mark, "timeOffset"),
                char_offset=_text(mark, "charOffset"),
            )
        ),
        bookmarks=len(element.findall(_bm("bookmark"))),
        hilites=len(element.findall(_bm("hilite"))),
    )


def parse_for_sending(document: str | bytes) -> etree._Element:
    """The `bookmarkSet` root of a document, ready to be sent as it is.

    Raises `ValueError` when it is not well-formed, has a DOCTYPE or is not a
    `bookmarkSet`.
    """
    data = document.encode() if isinstance(document, str) else document
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
    )
    try:
        tree = etree.parse(BytesIO(data), parser)
    except etree.XMLSyntaxError as error:
        raise ValueError(f"not well-formed XML: {error.msg}") from error
    root = tree.getroot()
    docinfo: Any = tree.docinfo
    if docinfo.doctype:
        raise ValueError("a DOCTYPE is not allowed")
    if root.tag != _bm("bookmarkSet"):
        raise ValueError(f"the root element is not a bookmarkSet in {BOOKMARK_NS}")
    return root


def validate_bookmark_set(document: bytes) -> tuple[Finding, ...]:
    """What is wrong with a bookmark set file, checked against the local
    bookmark schema; empty when it is valid. Nothing is sent anywhere."""
    try:
        parse_for_sending(document)
    except ValueError as error:
        return (_Finding(0, str(error)),)
    return tuple(validate_document(document))
