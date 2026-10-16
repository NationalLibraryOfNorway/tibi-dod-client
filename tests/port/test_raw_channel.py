"""`RawChannel`: deliberately invalid requests, HTTP adapter only (ADR 0004).

The fake Service on localhost is the other end; users and passwords are
synthetic.
"""

from collections.abc import Iterator

import pytest

from dod.domain.service import (
    Deviation,
    Fault,
    FaultKind,
    Ok,
    Password,
    TransportError,
)
from dod.domain.v1 import RawChannel
from dod.infrastructure import HttpServicePort
from support import FakeService

from lxml import etree  # isort: skip

NS = "http://www.daisy.org/ns/daisy-online/"


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    fake.add_user("synthetic-user", "synthetic-secret")
    yield fake
    fake.stop()


@pytest.fixture
def channel(service: FakeService) -> Iterator[RawChannel]:
    port = HttpServicePort(service.url)
    yield port
    port.close()


def test_the_operation_and_body_go_out_exactly_as_given(
    service: FakeService, channel: RawChannel
) -> None:
    channel.send_raw("getContentList", "<id>x</id><firstItem>abc</firstItem>")

    request = service.requests[0]
    assert request.operation == "getContentList"
    assert request.headers["SOAPAction"] == '"/getContentList"'
    payload = etree.fromstring(request.body)[0][0]
    assert payload.tag == f"{{{NS}}}getContentList"
    assert [(etree.QName(c).localname, c.text) for c in payload] == [
        ("id", "x"),
        ("firstItem", "abc"),
    ]


def test_a_dodp_fault_is_a_fault_value_with_its_exchange(
    channel: RawChannel,
) -> None:
    reply = channel.send_raw("getServiceAttributes", "")

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.NO_ACTIVE_SESSION
    assert reply.exchange.status == 500
    assert "getServiceAttributes" in reply.exchange.request_body


def test_a_success_is_ok_with_the_answer_document_as_text(
    service: FakeService, channel: RawChannel
) -> None:
    assert isinstance(channel, HttpServicePort)
    channel.log_on("synthetic-user", Password("synthetic-secret"))

    reply = channel.send_raw("logOff", "")

    assert isinstance(reply, Ok)
    assert "logOffResult" in reply.value


def test_an_answer_with_no_dodp_fault_element_is_a_deviation(
    service: FakeService, channel: RawChannel
) -> None:
    service.inject_http_500("getContentList")

    reply = channel.send_raw("getContentList", "")

    assert isinstance(reply, Deviation)


def test_no_answer_is_a_transport_error(
    service: FakeService, channel: RawChannel
) -> None:
    service.inject_no_answer("getContentList")

    with pytest.raises(TransportError):
        channel.send_raw("getContentList", "")


def test_a_session_resumed_from_another_port_is_sent(
    service: FakeService, channel: RawChannel
) -> None:
    owner = HttpServicePort(service.url)
    owner.log_on("synthetic-user", Password("synthetic-secret"))
    assert owner.session is not None
    channel.resume(owner.session)

    channel.send_raw("getServiceAttributes", "")

    assert service.requests[-1].headers["Cookie"].startswith("session=")
    owner.close()
