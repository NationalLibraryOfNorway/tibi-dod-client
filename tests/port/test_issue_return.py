"""Contract tests for `issueContent` and `returnContent`, on every adapter."""

import pytest

from dod.domain.service import Deviation, Fault, FaultKind, Ok, Password
from dod.domain.v1 import ContentResource, ServicePort
from support import Harness

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")
CHAPTER = ContentResource(
    uri="files/chapter1.mp3",
    mime_type="audio/mpeg",
    size=11,
    local_uri="chapter1.mp3",
)


@pytest.fixture
def adapter_with_books(adapter: Harness) -> Harness:
    adapter.add_user(USER, PASSWORD.reveal())
    adapter.offer_resources("issued-book", [CHAPTER])
    adapter.offer_resources("returned-book", [CHAPTER], issued=False)
    return adapter


@pytest.fixture
def port(adapter_with_books: Harness) -> ServicePort:
    port = adapter_with_books.open_port()
    port.log_on(USER, PASSWORD)
    return port


def test_issuing_content_makes_its_resources_available(port: ServicePort) -> None:
    reply = port.issue_content("returned-book")

    assert isinstance(reply, Ok), reply
    assert reply.value is True
    assert reply.schema_violations == ()
    assert isinstance(port.get_content_resources("returned-book"), Ok)


def test_issuing_unknown_content_is_an_invalid_parameter(port: ServicePort) -> None:
    reply = port.issue_content("no-such-book")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


def test_issue_content_without_a_session_is_no_active_session(
    adapter_with_books: Harness,
) -> None:
    reply = adapter_with_books.open_port().issue_content("returned-book")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.NO_ACTIVE_SESSION


def test_returning_content_ends_the_access_and_answers_true(port: ServicePort) -> None:
    reply = port.return_content("issued-book")

    assert isinstance(reply, Ok), reply
    assert reply.value is True
    assert reply.schema_violations == ()
    assert isinstance(port.get_content_resources("issued-book"), Fault)


def test_returning_content_again_still_answers_true(port: ServicePort) -> None:
    port.return_content("issued-book")

    for book in ("issued-book", "returned-book"):
        reply = port.return_content(book)

        assert isinstance(reply, Ok), reply
        assert reply.value is True


def test_returning_unknown_content_is_an_invalid_parameter(port: ServicePort) -> None:
    reply = port.return_content("no-such-book")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


def test_return_content_without_a_session_is_no_active_session(
    adapter_with_books: Harness,
) -> None:
    reply = adapter_with_books.open_port().return_content("issued-book")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.NO_ACTIVE_SESSION


def test_a_false_return_result_is_a_deviation_citing_the_operation(
    adapter_with_books: Harness, port: ServicePort
) -> None:
    adapter_with_books.inject_false("returnContent")

    reply = port.return_content("issued-book")

    assert isinstance(reply, Deviation), reply
    assert "false" in reply.description
    assert reply.spec_reference.section == "5.2.3"
