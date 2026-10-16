"""What a test author can make the fake Service do, seen through the HTTP adapter.

Each injection is per test and per operation, and is used once. Every document
the fake Service builds itself is validated against the local schemas.
"""

import httpx
import pytest

from dod.domain.service import Deviation, Fault, FaultKind, Ok, Password, TransportError
from dod.infrastructure import HttpServicePort
from support import FakeService

USER = "synthetic-user"
PASSWORD = Password("synthetic-secret")


@pytest.fixture
def service():  # type: ignore[no-untyped-def]
    fake = FakeService()
    fake.add_user(USER, PASSWORD.reveal())
    yield fake
    fake.stop()


@pytest.fixture
def port(service: FakeService):  # type: ignore[no-untyped-def]
    port = HttpServicePort(service.url)
    yield port
    port.close()


@pytest.mark.parametrize("kind", list(FaultKind))
def test_each_of_the_five_dodp_faults_can_be_injected(
    service: FakeService, port: HttpServicePort, kind: FaultKind
) -> None:
    service.inject_fault("logOn", kind, "synthetic reason")

    reply = port.log_on(USER, PASSWORD)

    assert isinstance(reply, Fault)
    assert reply.kind is kind
    assert reply.reason == "synthetic reason"
    assert reply.exchange.status == 500
    assert service.invalid_responses == []


def test_an_injection_is_used_once_and_only_for_its_operation(
    service: FakeService, port: HttpServicePort
) -> None:
    service.inject_fault("logOff", FaultKind.INVALID_OPERATION, "synthetic")

    assert isinstance(port.log_on(USER, PASSWORD), Ok)
    assert isinstance(port.log_off(), Fault)
    assert isinstance(port.log_on(USER, PASSWORD), Ok)


def test_an_unknown_fault_kind_is_refused_when_it_is_injected(
    service: FakeService,
) -> None:
    with pytest.raises(ValueError):
        service.inject_fault("logOn", "madeUpFault", "synthetic")


def test_a_response_that_breaks_the_schemas_is_recorded_by_the_fake_service(
    service: FakeService, port: HttpServicePort
) -> None:
    port.log_on(USER, PASSWORD)
    service.service_attributes_xml = service.service_attributes_xml.replace(
        "<supportsSearch>false</supportsSearch>",
        "<supportsSearch>maybe</supportsSearch>",
    )

    port.get_service_attributes()

    assert len(service.invalid_responses) == 1
    service.invalid_responses.clear()


def test_http_500_without_a_dodp_element_is_a_deviation_with_a_reference(
    service: FakeService, port: HttpServicePort
) -> None:
    service.inject_http_500("logOn")

    reply = port.log_on(USER, PASSWORD)

    assert isinstance(reply, Deviation)
    assert reply.exchange.status == 500
    assert reply.spec_reference.section == "5.3"


@pytest.mark.parametrize("body", [b"<html><body>Oops</body></html>", b"plain text"])
def test_an_answer_that_is_not_soap_gives_no_usable_answer(
    service: FakeService, port: HttpServicePort, body: bytes
) -> None:
    service.inject_not_soap("logOn", body)

    with pytest.raises(TransportError):
        port.log_on(USER, PASSWORD)


def test_a_missing_answer_gives_no_usable_answer(
    service: FakeService, port: HttpServicePort
) -> None:
    service.inject_no_answer("logOn")

    with pytest.raises(TransportError):
        port.log_on(USER, PASSWORD)


def test_a_slow_answer_times_out_without_waiting_for_it(service: FakeService) -> None:
    service.inject_delay("logOn", seconds=30)
    slow = HttpServicePort(service.url, client=httpx.Client(timeout=0.2))

    with pytest.raises(TransportError):
        slow.log_on(USER, PASSWORD)
    slow.close()


def test_a_redirect_to_another_host_is_not_followed(service: FakeService) -> None:
    elsewhere = FakeService()
    # `localhost` and `127.0.0.1` are different hosts to an HTTP client.
    service.inject_redirect("logOn", elsewhere.url.replace("127.0.0.1", "localhost"))
    port = HttpServicePort(service.url)

    with pytest.raises(TransportError) as raised:
        port.log_on(USER, PASSWORD)

    assert raised.value.exchange is not None
    assert raised.value.exchange.status == 307
    assert elsewhere.requests == []
    port.close()
    elsewhere.stop()


def test_a_redirect_from_http_to_https_is_not_followed(
    service: FakeService, port: HttpServicePort
) -> None:
    service.inject_redirect("logOn", service.url.replace("http://", "https://"))

    with pytest.raises(TransportError):
        port.log_on(USER, PASSWORD)

    assert len(service.requests) == 1
