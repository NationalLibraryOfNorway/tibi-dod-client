"""What only the HTTP adapter does: the wire format, tolerance and transport errors.

The contract suite covers behaviour shared with the in-memory adapter; this
file covers the SOAP details through the fake Service's recorded requests.
"""

import pytest

from dod.domain.service import Deviation, Fault, FaultKind, Ok, Password, TransportError
from dod.infrastructure import HttpServicePort
from support import FakeService

from lxml import etree  # isort: skip


@pytest.fixture
def service():  # type: ignore[no-untyped-def]
    fake = FakeService()
    fake.add_user("synthetic-user", "synthetic-secret")
    yield fake
    fake.stop()


@pytest.fixture
def port(service: FakeService):  # type: ignore[no-untyped-def]
    port = HttpServicePort(service.url)
    yield port
    port.close()


def log_on(port: HttpServicePort):  # type: ignore[no-untyped-def]
    return port.log_on("synthetic-user", Password("synthetic-secret"))


def test_log_on_is_soap_11_document_literal_with_username_before_password(
    service: FakeService, port: HttpServicePort
) -> None:
    log_on(port)

    request = service.requests[0]
    assert request.headers["SOAPAction"] == '"/logOn"'
    assert request.headers["Content-Type"].startswith("text/xml")
    envelope = etree.fromstring(request.body)
    payload = envelope[0][0]
    assert payload.tag == "{http://www.daisy.org/ns/daisy-online/}logOn"
    assert [child.text for child in payload] == ["synthetic-user", "synthetic-secret"]


def test_the_session_cookie_is_sent_on_later_calls(
    service: FakeService, port: HttpServicePort
) -> None:
    log_on(port)

    port.get_service_attributes()

    assert service.requests[1].headers["Cookie"].startswith("session=")


def test_an_http_address_gives_a_transport_security_observation(
    port: HttpServicePort,
) -> None:
    reply = log_on(port)

    assert [o.id for o in reply.observations] == ["transport-security"]


def test_the_exchange_is_the_unmasked_wire_traffic(port: HttpServicePort) -> None:
    reply = log_on(port)

    assert "synthetic-secret" in reply.exchange.request_body
    assert "<logOnResult>true</logOnResult>" in reply.exchange.response_body


def test_an_answer_that_breaks_the_schema_is_read_leniently_with_violations(
    service: FakeService, port: HttpServicePort
) -> None:
    log_on(port)
    service.allow_invalid_attributes = True
    service.service_attributes_xml = service.service_attributes_xml.replace(
        "<supportsSearch>false</supportsSearch>",
        "<supportsSearch>maybe</supportsSearch>",
    )

    reply = port.get_service_attributes()

    assert isinstance(reply, Ok)
    assert reply.value.service_id == "synthetic-service"
    assert reply.schema_violations != ()
    assert "supportsSearch" in reply.schema_violations[0].message


def test_a_soap_fault_without_a_dodp_element_is_a_deviation(
    service: FakeService, port: HttpServicePort
) -> None:
    service.respond_with(
        500,
        b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        b"<s:Fault><faultcode>s:Server</faultcode><faultstring>boom</faultstring>"
        b"</s:Fault></s:Body></s:Envelope>",
    )

    reply = log_on(port)

    assert isinstance(reply, Deviation)
    assert reply.spec_reference.section == "5.3"


def test_a_dodp_fault_is_classified_by_its_element(
    service: FakeService, port: HttpServicePort
) -> None:
    service.inject_fault("logOn", "internalServerError", "synthetic")

    reply = log_on(port)

    assert isinstance(reply, Fault)
    assert reply.kind is FaultKind.INTERNAL_SERVER_ERROR


@pytest.mark.parametrize(
    ("status", "body", "headers"),
    [
        pytest.param(200, b"<html>not soap</html>", {}, id="xml-but-not-soap"),
        pytest.param(502, b"Bad gateway", {}, id="not-xml"),
        pytest.param(302, b"", {"Location": "http://other.example/"}, id="redirect"),
    ],
)
def test_no_usable_answer_raises_transport_error(
    service: FakeService,
    port: HttpServicePort,
    status: int,
    body: bytes,
    headers: dict[str, str],
) -> None:
    service.respond_with(status, body, headers)

    with pytest.raises(TransportError):
        log_on(port)


def test_a_service_that_does_not_answer_raises_transport_error() -> None:
    port = HttpServicePort("http://127.0.0.1:9/dodp")

    with pytest.raises(TransportError):
        log_on(port)


def test_reading_system_attributes_go_out_as_a_schema_valid_document(
    service: FakeService, port: HttpServicePort
) -> None:
    from dod.domain.v1 import ReadingSystemAttributes, ReadingSystemConfig

    log_on(port)
    attributes = ReadingSystemAttributes(
        manufacturer="Synthetic Maker",
        model="dod",
        version="0.0.0",
        serial_number="0001",
        config=ReadingSystemConfig(
            supports_multiple_selections=False,
            preferred_ui_language="nb",
            supported_content_formats=("Daisy 2.02",),
            supported_content_protection_formats=("PDTB2",),
            supported_mime_types=("audio/mpeg",),
            supported_input_types=("TEXT_NUMERIC", "AUDIO"),
            requires_audio_labels=False,
        ),
    )

    reply = port.set_reading_system_attributes(attributes)

    assert isinstance(reply, Ok)
    assert service.invalid_documents == []
