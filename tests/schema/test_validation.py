"""Schema validation through `dod.infrastructure`, offline (ADR 0003).

All documents are hand-written and synthetic.
"""

import socket
from collections.abc import Iterator
from typing import NoReturn

import pytest

from dod.infrastructure import validate_document

VALID_RESOURCES = """\
<resources xmlns="http://www.daisy.org/ns/daisy-online/">
  <resource uri="https://service.example/books/b1/a1.mp3"
            mimeType="audio/mpeg" size="1024" localURI="audio/a1.mp3"/>
</resources>
"""

# `size` is not a number and the required `localURI` is missing.
INVALID_RESOURCES = """\
<resources xmlns="http://www.daisy.org/ns/daisy-online/">
  <resource uri="https://service.example/books/b1/a1.mp3"
            mimeType="audio/mpeg" size="large"/>
</resources>
"""

# Exercises the Dublin Core schema, which in turn imports the XML namespace one.
VALID_CONTENT_METADATA = """\
<contentMetadata xmlns="http://www.daisy.org/ns/daisy-online/"
                 xmlns:dc="http://purl.org/dc/elements/1.1/"
                 requiresReturn="false">
  <metadata>
    <dc:title xml:lang="nb">Synthetic title</dc:title>
    <dc:identifier>b1</dc:identifier>
    <dc:format>Daisy 2.02</dc:format>
    <size>2048</size>
  </metadata>
</contentMetadata>
"""

# Exercises KeyExchange, which imports the XML Encryption and XML Signature
# schemas: the issuer's uid contains characters its pattern forbids.
INVALID_KEY_EXCHANGE = """\
<KeyExchange xmlns="http://www.daisy.org/DRM/2005/KeyExchange">
  <Issuer uid="not a valid id">Synthetic issuer</Issuer>
  <Keys/>
</KeyExchange>
"""


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def refuse(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("validation attempted a network lookup")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    yield


def test_a_valid_document_has_no_findings() -> None:
    assert validate_document(VALID_RESOURCES) == ()


def test_an_invalid_document_is_reported_as_findings() -> None:
    findings = validate_document(INVALID_RESOURCES)

    assert len(findings) >= 2
    assert all(finding.line == 3 for finding in findings)
    messages = " ".join(finding.message for finding in findings)
    assert "size" in messages
    assert "localURI" in messages


def test_a_document_that_is_not_well_formed_is_a_finding_not_an_exception() -> None:
    findings = validate_document("<resources>")

    assert len(findings) == 1
    assert findings[0].line == 1


def test_bytes_are_accepted_as_well_as_text() -> None:
    assert validate_document(VALID_RESOURCES.encode("utf-8")) == ()


def test_a_dublin_core_document_validates_through_the_local_copies(
    no_network: None,
) -> None:
    assert validate_document(VALID_CONTENT_METADATA) == ()


def test_the_key_exchange_schema_and_its_imports_are_loaded_locally(
    no_network: None,
) -> None:
    findings = validate_document(INVALID_KEY_EXCHANGE)

    assert any("uid" in finding.message for finding in findings)


def test_validation_makes_no_network_lookups(no_network: None) -> None:
    assert validate_document(VALID_RESOURCES) == ()
    assert validate_document(INVALID_RESOURCES) != ()
