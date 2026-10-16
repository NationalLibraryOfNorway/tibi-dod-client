"""Contract tests for the bookmark and key exchange operations, on every adapter.

Users, books, passwords and keys are synthetic.
"""

import pytest

from dod.domain.service import Fault, FaultKind, Ok
from dod.domain.v1 import ContentMetadata, ServicePort
from support import SECRET as PASSWORD
from support import Harness
from support.samples import KEY_EXCHANGE, bookmark_set

USER = "synthetic-user"
BOOK = ContentMetadata(title="Book", identifier="book0", format="Daisy 2.02", size=1)
LASTMARK = (
    "<lastmark><ncxRef>hix00023</ncxRef><URI>s023.smil#main</URI>"
    "<timeOffset>97.826</timeOffset><charOffset>0</charOffset></lastmark>"
)


@pytest.fixture
def adapter_with_books(adapter: Harness) -> Harness:
    adapter.add_user(USER, PASSWORD.reveal())
    adapter.offer_catalog([], [BOOK])
    adapter.declare_operations("GET_BOOKMARKS", "SET_BOOKMARKS", "PDTB2_KEY_PROVISION")
    return adapter


@pytest.fixture
def port(adapter_with_books: Harness) -> ServicePort:
    port = adapter_with_books.open_port()
    port.log_on(USER, PASSWORD)
    return port


def test_a_book_without_bookmarks_has_an_empty_set_with_its_id(
    port: ServicePort,
) -> None:
    reply = port.get_bookmarks("book0")

    assert isinstance(reply, Ok), reply
    assert reply.schema_violations == ()
    assert reply.value.uid == "book0"
    assert reply.value.lastmark is None
    assert (reply.value.bookmarks, reply.value.hilites) == (0, 0)


def test_the_set_is_read_leniently_and_kept_as_received(
    adapter_with_books: Harness, port: ServicePort
) -> None:
    sent = bookmark_set("book0", lastmark=LASTMARK, bookmarks=2, hilites=1)
    adapter_with_books.offer_bookmarks("book0", sent)

    reply = port.get_bookmarks("book0")

    assert isinstance(reply, Ok), reply
    got = reply.value
    assert got.title == "Synthetic title"
    assert got.lastmark is not None
    assert (got.lastmark.ncx_ref, got.lastmark.uri) == ("hix00023", "s023.smil#main")
    assert (got.lastmark.time_offset, got.lastmark.char_offset) == ("97.826", "0")
    assert (got.bookmarks, got.hilites) == (2, 1)
    assert "<timeOffset>97.826</timeOffset>" in got.xml


def test_a_nil_offset_reads_as_missing(
    adapter_with_books: Harness, port: ServicePort
) -> None:
    nil = (
        "<lastmark><ncxRef>a</ncxRef><URI>b.smil#c</URI><charOffset "
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"/>'
        "</lastmark>"
    )
    adapter_with_books.offer_bookmarks(
        "book0", bookmark_set("book0", lastmark=nil), schema_valid=False
    )

    reply = port.get_bookmarks("book0")

    assert isinstance(reply, Ok), reply
    assert reply.value.lastmark is not None
    assert reply.value.lastmark.char_offset is None


def test_bookmarks_of_unknown_content_are_an_invalid_parameter(
    port: ServicePort,
) -> None:
    reply = port.get_bookmarks("no-such-book")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


def test_a_set_is_stored_as_it_is_and_replaces_the_old_one(
    adapter_with_books: Harness, port: ServicePort
) -> None:
    adapter_with_books.offer_bookmarks("book0", bookmark_set("book0", bookmarks=3))
    replacement = bookmark_set("book0", lastmark=LASTMARK)

    stored = port.set_bookmarks("book0", replacement)

    assert isinstance(stored, Ok), stored
    assert stored.value is True
    got = port.get_bookmarks("book0")
    assert isinstance(got, Ok), got
    assert got.value.bookmarks == 0
    assert got.value.lastmark is not None
    assert got.value.lastmark.time_offset == "97.826"


def test_setting_bookmarks_of_unknown_content_is_an_invalid_parameter(
    port: ServicePort,
) -> None:
    reply = port.set_bookmarks("no-such-book", bookmark_set("no-such-book"))

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


@pytest.mark.parametrize(
    "document",
    ["<bookmarkSet", "<foo/>", '<!DOCTYPE x [<!ENTITY e "v">]><bookmarkSet/>'],
)
def test_a_document_that_is_not_a_bookmark_set_is_refused_before_sending(
    port: ServicePort, document: str
) -> None:
    with pytest.raises(ValueError):
        port.set_bookmarks("book0", document)


def test_the_bookmark_operations_need_a_session(adapter_with_books: Harness) -> None:
    bare = adapter_with_books.open_port()

    for reply in (
        bare.get_bookmarks("book0"),
        bare.set_bookmarks("book0", bookmark_set("book0")),
        bare.get_key_exchange_object("synthetic-key"),
    ):
        assert isinstance(reply, Fault)
        assert reply.kind is FaultKind.NO_ACTIVE_SESSION


def test_a_key_exchange_object_is_returned_as_it_came(
    adapter_with_books: Harness, port: ServicePort
) -> None:
    adapter_with_books.offer_key_exchange("synthetic-key", KEY_EXCHANGE)

    reply = port.get_key_exchange_object("synthetic-key")

    assert isinstance(reply, Ok), reply
    assert reply.schema_violations == ()
    assert "<UAK " in reply.value.xml
    assert "c3ludGhldGlj" in reply.value.xml


def test_an_unknown_key_name_is_an_invalid_parameter(port: ServicePort) -> None:
    reply = port.get_key_exchange_object("no-such-key")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER
