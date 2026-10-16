"""What only the HTTP adapter does for a resource GET: who gets credentials."""

import base64
from collections.abc import Iterator

import pytest

from dod.domain.service import Deviation, Ok, Password, TransportError
from dod.domain.v1 import SinkRefused
from dod.infrastructure import HttpServicePort
from support import FakeService

USER = "synthetic-user"
PASSWORD = "synthetic-secret"


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user(USER, PASSWORD)
    fake.offer_file("files/a.txt", b"hello")
    yield fake
    fake.stop()


@pytest.fixture
def other() -> Iterator[FakeService]:
    """Another origin: the same address on another port."""
    fake = FakeService()
    fake.offer_file("files/a.txt", b"delegate")
    yield fake
    fake.stop()


@pytest.fixture
def port(service: FakeService) -> Iterator[HttpServicePort]:
    port = HttpServicePort(service.url)
    port.log_on(USER, Password(PASSWORD))
    yield port
    port.close()


def test_the_session_cookie_goes_to_the_service_origin(
    service: FakeService, port: HttpServicePort
) -> None:
    reply = port.fetch_resource(service.file_url("files/a.txt"), lambda chunk: None)

    assert isinstance(reply, Ok), reply
    assert service.fetches[-1].headers["Cookie"].startswith("session=")


def test_the_session_cookie_never_goes_to_another_origin(
    other: FakeService, port: HttpServicePort
) -> None:
    sent: list[bytes] = []

    reply = port.fetch_resource(other.file_url("files/a.txt"), sent.append)

    assert isinstance(reply, Ok), reply
    assert b"".join(sent) == b"delegate"
    assert "Cookie" not in other.fetches[-1].headers
    assert "Authorization" not in other.fetches[-1].headers


def test_userinfo_in_the_address_is_used_as_credentials_towards_that_host_only(
    other: FakeService, port: HttpServicePort
) -> None:
    url = other.file_url("files/a.txt").replace("http://", "http://dg-user:dg-pass@")

    reply = port.fetch_resource(url, lambda chunk: None)

    assert isinstance(reply, Ok), reply
    expected = base64.b64encode(b"dg-user:dg-pass").decode()
    assert other.fetches[-1].headers["Authorization"] == f"Basic {expected}"
    assert "Cookie" not in other.fetches[-1].headers


def test_a_range_is_sent_as_a_range_header(
    service: FakeService, port: HttpServicePort
) -> None:
    port.fetch_resource(service.file_url("files/a.txt"), lambda chunk: None, (1, None))

    assert service.fetches[-1].headers["Range"] == "bytes=1-"


def test_a_redirect_is_not_followed_and_is_a_deviation(
    service: FakeService, other: FakeService, port: HttpServicePort
) -> None:
    service.answer_file(
        "files/moved.txt", 302, headers={"Location": other.file_url("files/a.txt")}
    )
    sent: list[bytes] = []

    reply = port.fetch_resource(service.file_url("files/moved.txt"), sent.append)

    assert isinstance(reply, Deviation), reply
    assert reply.exchange.status == 302
    assert sent == []
    assert other.fetches == []


def test_a_206_to_a_request_without_a_range_is_a_deviation(
    service: FakeService, port: HttpServicePort
) -> None:
    service.answer_file("files/odd.txt", 206, b"part")
    sent: list[bytes] = []

    reply = port.fetch_resource(service.file_url("files/odd.txt"), sent.append)

    assert isinstance(reply, Deviation), reply
    assert sent == []


def test_a_compressed_answer_is_counted_as_sent(
    service: FakeService, port: HttpServicePort
) -> None:
    service.answer_file(
        "files/z.txt", 200, b"\x1f\x8b-not-really-gzip", {"Content-Encoding": "gzip"}
    )
    sent: list[bytes] = []

    reply = port.fetch_resource(service.file_url("files/z.txt"), sent.append)

    assert isinstance(reply, Ok), reply
    assert b"".join(sent) == b"\x1f\x8b-not-really-gzip"
    assert service.fetches[-1].headers["Accept-Encoding"] == "identity"


def test_a_sink_that_refuses_stops_the_transfer_with_a_deviation(
    service: FakeService, port: HttpServicePort
) -> None:
    def refuse(chunk: bytes) -> None:
        raise SinkRefused("more bytes than announced")

    reply = port.fetch_resource(service.file_url("files/a.txt"), refuse)

    assert isinstance(reply, Deviation), reply
    assert "more bytes than announced" in reply.description


def test_no_answer_raises_a_transport_error_without_credentials_in_the_message() -> (
    None
):
    port = HttpServicePort("http://127.0.0.1:9/dodp")

    with pytest.raises(TransportError) as raised:
        port.fetch_resource("http://dg-user:dg-pass@127.0.0.1:9/x", lambda c: None)

    assert "dg-pass" not in str(raised.value)
    port.close()
