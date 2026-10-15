"""The synchronous HTTP adapter for `ServicePort` (HTTPX and lxml).

It owns everything the specification says about the wire: SOAP 1.1
document/literal, the namespace, the soapAction values and the order of
parameters. The domain models know none of it (ADR 0004). Answers are read
leniently into the models and always validated against the local schemas.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from lxml import etree

from dod.domain.service import (
    Deviation,
    Exchange,
    Fault,
    FaultKind,
    Observation,
    Ok,
    Password,
    Reply,
    SchemaViolation,
    SessionState,
    TransportError,
)
from dod.domain.v1 import ReadingSystemAttributes, ServiceAttributes
from dod.infrastructure._schema import SchemaUnavailableError, validate_document
from dod.infrastructure._spec import FAULTS_REFERENCE, operation_reference

_NS = "http://www.daisy.org/ns/daisy-online/"
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_TIMEOUT_SECONDS = 30.0


def _dodp(name: str) -> str:
    return f"{{{_NS}}}{name}"


def _text_element(parent: etree._Element, name: str, text: str) -> etree._Element:
    child = etree.SubElement(parent, _dodp(name))
    child.text = text
    return child


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _reading_system_element(
    parent: etree._Element, attributes: ReadingSystemAttributes
) -> None:
    root = etree.SubElement(parent, _dodp("readingSystemAttributes"))
    _text_element(root, "manufacturer", attributes.manufacturer)
    _text_element(root, "model", attributes.model)
    if attributes.serial_number is not None:
        _text_element(root, "serialNumber", attributes.serial_number)
    _text_element(root, "version", attributes.version)
    config = etree.SubElement(root, _dodp("config"))
    cfg = attributes.config
    _text_element(
        config,
        "supportsMultipleSelections",
        _bool_text(cfg.supports_multiple_selections),
    )
    _text_element(config, "preferredUILanguage", cfg.preferred_ui_language)
    formats = etree.SubElement(config, _dodp("supportedContentFormats"))
    for item in cfg.supported_content_formats:
        _text_element(formats, "contentFormat", item)
    protection = etree.SubElement(config, _dodp("supportedContentProtectionFormats"))
    for item in cfg.supported_content_protection_formats:
        _text_element(protection, "protectionFormat", item)
    mime_types = etree.SubElement(config, _dodp("supportedMimeTypes"))
    for item in cfg.supported_mime_types:
        etree.SubElement(mime_types, _dodp("mimeType")).set("type", item)
    inputs = etree.SubElement(config, _dodp("supportedInputTypes"))
    for item in cfg.supported_input_types:
        etree.SubElement(inputs, _dodp("input")).set("type", item)
    _text_element(config, "requiresAudioLabels", _bool_text(cfg.requires_audio_labels))


def _envelope(operation: str, fill: Callable[[etree._Element], None]) -> bytes:
    envelope = etree.Element(f"{{{_SOAP}}}Envelope", nsmap={"soap": _SOAP})
    body = etree.SubElement(envelope, f"{{{_SOAP}}}Body")
    namespaces: dict[str | None, str] = {None: _NS}
    fill(etree.SubElement(body, _dodp(operation), nsmap=namespaces))  # type: ignore[arg-type]
    return etree.tostring(envelope, xml_declaration=True, encoding="utf-8")


def _children_text(element: etree._Element, name: str) -> tuple[str, ...]:
    return tuple((child.text or "").strip() for child in element.iter(_dodp(name)))


def _flag(element: etree._Element, name: str) -> bool | None:
    text = element.findtext(_dodp(name))
    if text is None:
        return None
    return text.strip().lower() in {"true", "1"}


def _service_attributes(element: etree._Element) -> ServiceAttributes:
    def identifier(name: str) -> str | None:
        child = element.find(_dodp(name))
        return None if child is None else child.get("id")

    return ServiceAttributes(
        service_provider_id=identifier("serviceProvider"),
        service_id=identifier("service"),
        supported_content_selection_methods=_children_text(element, "method"),
        supports_server_side_back=_flag(element, "supportsServerSideBack"),
        supports_search=_flag(element, "supportsSearch"),
        supported_uplink_audio_codecs=_children_text(element, "codec"),
        supports_audio_labels=_flag(element, "supportsAudioLabels"),
        supported_optional_operations=_children_text(element, "operation"),
    )


class HttpServicePort:
    """A `ServicePort` that talks SOAP over HTTP to one Service URL.

    Redirects are never followed: a Service that redirects gives no usable
    answer, which also keeps credentials and cookies on the host the user named.
    """

    def __init__(self, url: str, *, client: httpx.Client | None = None) -> None:
        self._url = url
        self._client = client or httpx.Client(
            timeout=_TIMEOUT_SECONDS, follow_redirects=False
        )
        self._observations: tuple[Observation, ...] = ()
        if urlsplit(url).scheme == "http":
            self._observations = (
                Observation(
                    id="transport-security",
                    message=(
                        "the Service is addressed over unencrypted http; "
                        "credentials and the Session cookie are sent in clear text"
                    ),
                ),
            )

    @property
    def session(self) -> SessionState | None:
        cookies = tuple((c.name, c.value or "") for c in self._client.cookies.jar)
        return SessionState(cookies=cookies) if cookies else None

    def log_on(self, username: str, password: Password) -> Reply[bool]:
        def fill(parent: etree._Element) -> None:
            _text_element(parent, "username", username)
            _text_element(parent, "password", password.reveal())

        return self._call("logOn", fill, self._result("logOn"))

    def log_off(self) -> Reply[bool]:
        reply = self._call("logOff", lambda parent: None, self._result("logOff"))
        if isinstance(reply, Ok) and reply.value:
            self._client.cookies.clear()
        return reply

    def get_service_attributes(self) -> Reply[ServiceAttributes]:
        def read(
            response: etree._Element,
        ) -> tuple[ServiceAttributes, tuple[SchemaViolation, ...]] | Deviation | None:
            element = response.find(_dodp("serviceAttributes"))
            if element is None:
                return None
            return _service_attributes(element), self._validate(element)

        return self._call("getServiceAttributes", lambda parent: None, read)

    def set_reading_system_attributes(
        self, attributes: ReadingSystemAttributes
    ) -> Reply[bool]:
        return self._call(
            "setReadingSystemAttributes",
            lambda parent: _reading_system_element(parent, attributes),
            self._result("setReadingSystemAttributes"),
        )

    def close(self) -> None:
        self._client.close()

    # -- internals --------------------------------------------------------

    def _result(
        self, operation: str
    ) -> Callable[
        [etree._Element], tuple[bool, tuple[SchemaViolation, ...]] | Deviation | None
    ]:
        def read(
            response: etree._Element,
        ) -> tuple[bool, tuple[SchemaViolation, ...]] | Deviation | None:
            text = response.findtext(_dodp(f"{operation}Result"))
            if text is None or text.strip() not in {"true", "false", "1", "0"}:
                return None
            return text.strip() in {"true", "1"}, ()

        return read

    def _validate(self, element: etree._Element) -> tuple[SchemaViolation, ...]:
        try:
            findings = validate_document(etree.tostring(element))
        except SchemaUnavailableError:
            return ()
        return tuple(SchemaViolation(f.line, f.message) for f in findings)

    def _call[T](
        self,
        operation: str,
        fill: Callable[[etree._Element], None],
        read: Callable[
            [etree._Element],
            tuple[T, tuple[SchemaViolation, ...]] | Deviation | None,
        ],
    ) -> Reply[T]:
        request_body = _envelope(operation, fill)
        started = time.perf_counter()
        try:
            response = self._client.post(
                self._url,
                content=request_body,
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"/{operation}"',
                },
            )
        except httpx.HTTPError as error:
            raise TransportError(
                f"{operation}: no answer from the Service: {error}"
            ) from error
        exchange = Exchange(
            method="POST",
            url=self._url,
            request_headers=tuple(response.request.headers.items()),
            request_body=request_body.decode("utf-8"),
            status=response.status_code,
            response_headers=tuple(response.headers.items()),
            response_body=response.content.decode("utf-8", errors="replace"),
            duration_seconds=time.perf_counter() - started,
        )
        if 300 <= response.status_code < 400:
            raise TransportError(
                f"{operation}: the Service redirected (HTTP {response.status_code}); "
                "redirects are not followed",
                exchange=exchange,
            )
        body = self._soap_body(operation, response.content, exchange)
        payload = body[0] if len(body) else None
        if payload is None:
            return Deviation(
                description="the SOAP body is empty",
                spec_reference=operation_reference(operation),
                exchange=exchange,
                observations=self._observations,
            )
        if payload.tag == f"{{{_SOAP}}}Fault":
            return self._fault(
                payload, exchange=exchange, observations=self._observations
            )
        if payload.tag != _dodp(f"{operation}Response"):
            return Deviation(
                description=(
                    f"expected {operation}Response, got "
                    f"{etree.QName(payload).localname}"
                ),
                spec_reference=operation_reference(operation),
                exchange=exchange,
                observations=self._observations,
            )
        parsed = read(payload)
        if parsed is None:
            return Deviation(
                description=f"{operation}Response lacks a usable result",
                spec_reference=operation_reference(operation),
                exchange=exchange,
                observations=self._observations,
            )
        if isinstance(parsed, Deviation):
            return parsed
        value, violations = parsed
        return Ok(
            value=value,
            schema_violations=violations,
            exchange=exchange,
            observations=self._observations,
        )

    @staticmethod
    def _soap_body(
        operation: str, content: bytes, exchange: Exchange
    ) -> etree._Element:
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        try:
            root = etree.fromstring(content, parser)
        except etree.XMLSyntaxError as error:
            raise TransportError(
                f"{operation}: the answer is not XML ({error.msg})",
                exchange=exchange,
            ) from error
        body = root.find(f"{{{_SOAP}}}Body")
        if root.tag != f"{{{_SOAP}}}Envelope" or body is None:
            raise TransportError(
                f"{operation}: the answer is not a SOAP 1.1 envelope",
                exchange=exchange,
            )
        return body

    @staticmethod
    def _fault(
        payload: etree._Element,
        *,
        exchange: Exchange,
        observations: tuple[Observation, ...],
    ) -> Fault | Deviation:
        detail = payload.find("detail")
        for child in () if detail is None else detail:
            if not isinstance(child.tag, str):
                continue
            name = etree.QName(child)
            if name.namespace == _NS and name.localname.endswith("Fault"):
                try:
                    kind = FaultKind(name.localname.removesuffix("Fault"))
                except ValueError:
                    continue
                reason = child.findtext(_dodp("reason"))
                return Fault(
                    kind=kind,
                    reason=reason,
                    exchange=exchange,
                    observations=observations,
                )
        return Deviation(
            description="a SOAP fault without a recognisable DODP fault element",
            spec_reference=FAULTS_REFERENCE,
            exchange=exchange,
            observations=observations,
        )
