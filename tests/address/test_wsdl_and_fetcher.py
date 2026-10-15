"""Reading a Service's WSDL safely and fetching it without credentials (ADR 0002).

Tests use the public `parse_wsdl` and `HttpFetcher` of the infrastructure layer
and the fake Service on localhost. Addresses are synthetic.
"""

from collections.abc import Iterator

import pytest

from dod.application import WsdlError
from dod.domain.service import TransportError
from dod.infrastructure import HttpFetcher, parse_wsdl
from support import FakeService, service_wsdl

ADDRESS = "https://dod.example.org/service"
DODP = "http://www.daisy.org/ns/daisy-online/"
WSDL = "http://schemas.xmlsoap.org/wsdl/"
SOAP11 = "http://schemas.xmlsoap.org/wsdl/soap/"
SOAP12 = "http://schemas.xmlsoap.org/wsdl/soap12/"


@pytest.fixture
def service() -> Iterator[FakeService]:
    fake = FakeService()
    yield fake
    fake.stop()


def test_the_dodp_port_of_a_service_wsdl_is_found() -> None:
    ports = parse_wsdl(service_wsdl(ADDRESS))

    assert [(p.name, p.address, p.is_dodp, p.is_soap11) for p in ports] == [
        ("SyntheticPort", ADDRESS, True, True)
    ]


def test_a_binding_defined_in_the_document_counts_when_it_uses_the_dodp_port_type() -> (
    None
):
    document = (
        f'<definitions xmlns="{WSDL}" xmlns:soap="{SOAP11}" xmlns:d="{DODP}" '
        'xmlns:t="urn:t" targetNamespace="urn:t">'
        '<binding name="B" type="d:daisy-online"><soap:binding style="document" '
        'transport="http://schemas.xmlsoap.org/soap/http"/></binding>'
        '<service name="S"><port name="P" binding="t:B">'
        f'<soap:address location="{ADDRESS}"/></port></service></definitions>'
    ).encode()

    (port,) = parse_wsdl(document)

    assert port.is_dodp and port.is_soap11


def test_a_soap_1_2_or_foreign_port_is_not_a_dodp_soap_1_1_port() -> None:
    document = (
        f'<definitions xmlns="{WSDL}" xmlns:s12="{SOAP12}" xmlns:soap="{SOAP11}" '
        'xmlns:t="urn:t" targetNamespace="urn:t">'
        '<binding name="Twelve" type="t:Other"><s12:binding/></binding>'
        '<service name="S"><port name="P" binding="t:Twelve">'
        f'<s12:address location="{ADDRESS}"/></port>'
        f'<port name="Q" binding="t:Missing"><soap:address location="{ADDRESS}"/>'
        "</port></service></definitions>"
    ).encode()

    ports = parse_wsdl(document)

    assert [(p.name, p.is_dodp, p.is_soap11) for p in ports] == [
        ("P", False, False),
        ("Q", False, False),
    ]


@pytest.mark.parametrize(
    "document",
    [
        b'<!DOCTYPE definitions SYSTEM "http://127.0.0.1:9/x.dtd"><definitions/>',
        b'<!DOCTYPE d [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><d>&b;</d>',
        b'<!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/hostname">]><d>&x;</d>',
        b"<definitions",
        b"",
        b"<html/>",
    ],
)
def test_unsafe_or_unusable_documents_are_refused(document: bytes) -> None:
    with pytest.raises(WsdlError):
        parse_wsdl(document)


def test_a_wsdl_is_fetched_without_credentials_or_cookies(
    service: FakeService,
) -> None:
    response = HttpFetcher().get(service.wsdl_url, max_bytes=1024 * 1024)

    assert response.status == 200
    assert b"soap:address" in response.body
    (fetch,) = service.fetches
    assert {name.lower() for name in fetch.headers}.isdisjoint(
        {"authorization", "cookie"}
    )


def test_redirects_are_reported_not_followed(service: FakeService) -> None:
    service.wsdl_redirect = "http://127.0.0.2:9/elsewhere"

    response = HttpFetcher().get(service.wsdl_url, max_bytes=1024)

    assert response.status == 302
    assert response.headers["location"] == "http://127.0.0.2:9/elsewhere"


def test_a_document_over_the_size_limit_is_refused(service: FakeService) -> None:
    service.serve_wsdl(b"<x>" + b"a" * 5000 + b"</x>")

    with pytest.raises(TransportError, match="larger than"):
        HttpFetcher().get(service.wsdl_url, max_bytes=1000)


def test_a_slow_answer_times_out(service: FakeService) -> None:
    service.wsdl_delay = 5

    with pytest.raises(TransportError, match="no answer"):
        HttpFetcher(timeout=0.2).get(service.wsdl_url, max_bytes=1024)
