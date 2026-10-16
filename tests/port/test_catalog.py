"""Contract tests for the content list and metadata operations, on every adapter."""

import pytest

from dod.domain.service import Deviation, Fault, FaultKind, Ok, Password
from dod.domain.v1 import ContentItem, ContentList, ContentMetadata, ServicePort
from support import Harness

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")
ITEMS = tuple(
    ContentItem(id=f"book{n}", label=f"Synthetic book {n}", lang="en") for n in range(5)
)
NEW = ContentList(id="new", total_items=5, items=ITEMS, label="New books")
ISSUED = ContentList(id="issued", total_items=1, items=ITEMS[:1])
BOOK = ContentMetadata(
    title="Synthetic book 0",
    identifier="book0",
    format="Daisy 2.02",
    size=1234,
    requires_return=True,
    category="BORROWABLE",
    creators=("Synthetic Author",),
    languages=("nb",),
    narrators=("Synthetic Reader",),
    meta=(("synthetic:key", "value"),),
)


@pytest.fixture
def port(adapter: Harness) -> ServicePort:
    adapter.add_user(USER, PASSWORD.reveal())
    adapter.offer_catalog([NEW, ISSUED], [BOOK])
    port = adapter.open_port()
    port.log_on(USER, PASSWORD)
    return port


def listed(port: ServicePort, id: str, first: int = 0, last: int = -1) -> ContentList:
    reply = port.get_content_list(id, first, last)
    assert isinstance(reply, Ok), reply
    assert reply.schema_violations == ()
    return reply.value


def test_a_whole_list_is_read_into_the_model(port: ServicePort) -> None:
    shown = listed(port, "new")

    assert shown.id == "new"
    assert shown.total_items == 5
    assert shown.label == "New books"
    assert shown.items == ITEMS


def test_a_segment_has_its_items_and_the_total_of_the_whole_list(
    port: ServicePort,
) -> None:
    shown = listed(port, "new", 1, 2)

    assert [item.id for item in shown.items] == ["book1", "book2"]
    assert shown.total_items == 5
    assert (shown.first_item, shown.last_item) == (1, 2)


def test_an_invalid_range_is_an_empty_list_that_still_gives_the_total(
    port: ServicePort,
) -> None:
    shown = listed(port, "new", 9, 12)

    assert shown.items == ()
    assert shown.total_items == 5


def test_an_unknown_list_is_an_invalid_parameter_fault(port: ServicePort) -> None:
    reply = port.get_content_list("nope", 0, -1)

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


def test_the_metadata_of_a_book_is_read_into_the_model(port: ServicePort) -> None:
    reply = port.get_content_metadata("book0")

    assert isinstance(reply, Ok)
    assert reply.schema_violations == ()
    assert reply.value == BOOK


def test_metadata_for_an_unknown_book_is_an_invalid_parameter_fault(
    port: ServicePort,
) -> None:
    reply = port.get_content_metadata("nope")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


def test_the_operations_need_a_session(adapter: Harness) -> None:
    adapter.offer_catalog([NEW], [BOOK])
    port = adapter.open_port()

    for reply in (port.get_content_list("new", 0, -1), port.get_content_metadata("a")):
        assert isinstance(reply, Fault)
        assert reply.kind is FaultKind.NO_ACTIVE_SESSION


@pytest.mark.parametrize(
    ("operation", "section"),
    [("getContentList", "5.1.8"), ("getContentMetadata", "5.1.5")],
)
def test_an_answer_contrary_to_the_specification_is_a_deviation_with_a_reference(
    adapter: Harness, port: ServicePort, operation: str, section: str
) -> None:
    adapter.inject_deviation(operation)

    reply = (
        port.get_content_list("new", 0, -1)
        if operation == "getContentList"
        else port.get_content_metadata("book0")
    )

    assert isinstance(reply, Deviation)
    assert reply.spec_reference.section == section
