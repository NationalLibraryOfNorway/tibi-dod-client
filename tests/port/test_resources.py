"""Contract tests for `getContentResources` and `fetch_resource`, on every adapter."""

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
    last_modified="2024-01-02T03:04:05Z",
)
NCC = ContentResource(
    uri="files/ncc.html", mime_type="text/html", size=5, local_uri="sub/ncc.html"
)


@pytest.fixture
def adapter_with_book(adapter: Harness) -> Harness:
    adapter.add_user(USER, PASSWORD.reveal())
    adapter.offer_resources("book0", [CHAPTER, NCC])
    adapter.offer_resources("book1", [CHAPTER], issued=False)
    adapter.offer_file("files/chapter1.mp3", b"hello world")
    adapter.offer_file("files/ncc.html", b"<html")
    return adapter


@pytest.fixture
def port(adapter_with_book: Harness) -> ServicePort:
    port = adapter_with_book.open_port()
    port.log_on(USER, PASSWORD)
    return port


def test_the_resources_of_issued_content_are_read_into_the_model(
    port: ServicePort,
) -> None:
    reply = port.get_content_resources("book0")

    assert isinstance(reply, Ok), reply
    assert reply.schema_violations == ()
    assert reply.value.resources == (CHAPTER, NCC)


def test_the_resources_of_content_that_is_not_issued_are_an_invalid_parameter(
    port: ServicePort,
) -> None:
    reply = port.get_content_resources("book1")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INVALID_PARAMETER


def test_get_content_resources_without_a_session_is_no_active_session(
    adapter_with_book: Harness,
) -> None:
    reply = adapter_with_book.open_port().get_content_resources("book0")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.NO_ACTIVE_SESSION


def test_a_resource_is_streamed_to_the_sink_and_the_reply_counts_the_bytes(
    adapter_with_book: Harness, port: ServicePort
) -> None:
    received: list[bytes] = []

    reply = port.fetch_resource(
        adapter_with_book.file_url("files/chapter1.mp3"), received.append
    )

    assert isinstance(reply, Ok), reply
    assert reply.value == 11
    assert b"".join(received) == b"hello world"
    assert reply.exchange.method == "GET"
    assert reply.exchange.status == 200
    assert reply.exchange.response_body == "hello world"
    assert reply.exchange.response_truncated is False


def test_a_byte_range_gets_partial_content(
    adapter_with_book: Harness, port: ServicePort
) -> None:
    received: list[bytes] = []

    reply = port.fetch_resource(
        adapter_with_book.file_url("files/chapter1.mp3"), received.append, (6, 10)
    )

    assert isinstance(reply, Ok), reply
    assert reply.exchange.status == 206
    assert b"".join(received) == b"world"


def test_a_status_other_than_2xx_is_a_deviation_and_nothing_reaches_the_sink(
    adapter_with_book: Harness, port: ServicePort
) -> None:
    received: list[bytes] = []

    reply = port.fetch_resource(
        adapter_with_book.file_url("files/missing.mp3"), received.append
    )

    assert isinstance(reply, Deviation), reply
    assert reply.exchange.status == 404
    assert reply.spec_reference.section == "6.10"
    assert received == []


def test_the_exchange_keeps_only_the_first_4_kib_of_the_body_marked_truncated(
    adapter_with_book: Harness, port: ServicePort
) -> None:
    body = b"abcdefghij" * 1024  # 10 240 bytes
    adapter_with_book.offer_file("files/big.bin", body)
    received: list[bytes] = []

    reply = port.fetch_resource(
        adapter_with_book.file_url("files/big.bin"), received.append
    )

    assert isinstance(reply, Ok), reply
    assert reply.value == 10240
    assert b"".join(received) == body
    assert reply.exchange.response_body == body[:4096].decode("ascii")
    assert reply.exchange.response_truncated is True
