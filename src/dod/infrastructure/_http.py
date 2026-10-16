"""The synchronous HTTP adapter for `ServicePort` (HTTPX and lxml).

It owns everything the specification says about the wire: SOAP 1.1
document/literal, the namespace, the soapAction values and the order of
parameters. The domain models know none of it (ADR 0004). Answers are read
leniently into the models and always validated against the local schemas.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Sequence
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
from dod.domain.v1 import (
    BARE_500_AS_INVALID_OPERATION,
    OBSERVATION_ID,
    QUIRKS,
    SPEC_REFS,
    Announcement,
    ContentItem,
    ContentList,
    ContentMetadata,
    ReadingSystemAttributes,
    ServiceAttributes,
    operation_ref,
)
from dod.infrastructure._schema import SchemaUnavailableError, validate_document

_NS = "http://www.daisy.org/ns/daisy-online/"
_DC = "http://purl.org/dc/elements/1.1/"
_SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
_TIMEOUT_SECONDS = 30.0
_BEFORE_INITIALISATION = frozenset(
    {"logOn", "logOff", "getServiceAttributes", "setReadingSystemAttributes"}
)
"""Operations that are valid before the initialisation sequence is complete."""


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
    if cfg.bandwidth is not None:
        _text_element(config, "bandwidth", str(cfg.bandwidth))
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
    if cfg.additional_transfer_protocols:
        protocols = etree.SubElement(config, _dodp("additionalTransferProtocols"))
        for item in cfg.additional_transfer_protocols:
            _text_element(protocols, "protocol", item)


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


_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def _announcements(element: etree._Element) -> tuple[Announcement, ...]:
    found: list[Announcement] = []
    for item in element.findall(_dodp("announcement")):
        label = item.find(_dodp("label"))
        priority = (item.get("priority") or "3").strip()
        found.append(
            Announcement(
                id=item.get("id") or "",
                text=(label.findtext(_dodp("text")) or "") if label is not None else "",
                lang=label.get(_XML_LANG) if label is not None else None,
                type=item.get("type") or "INFORMATION",
                priority=int(priority) if priority.isdigit() else 3,
            )
        )
    return tuple(found)


def _int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except ValueError:
        return None


def _label(element: etree._Element) -> tuple[str, str | None] | None:
    label = element.find(_dodp("label"))
    if label is None:
        return None
    return (label.findtext(_dodp("text")) or ""), label.get(_XML_LANG)


def _content_list(element: etree._Element) -> ContentList:
    items: list[ContentItem] = []
    for item in element.findall(_dodp("contentItem")):
        text, lang = _label(item) or ("", None)
        items.append(
            ContentItem(
                id=item.get("id") or "",
                label=text,
                lang=lang,
                last_modified=item.get("lastModifiedDate"),
            )
        )
    heading = _label(element)
    return ContentList(
        id=element.get("id") or "",
        total_items=_int(element.get("totalItems")) or 0,
        items=tuple(items),
        label=heading[0] if heading else None,
        first_item=_int(element.get("firstItem")),
        last_item=_int(element.get("lastItem")),
    )


def _content_metadata(element: etree._Element) -> ContentMetadata:
    metadata = element.find(_dodp("metadata"))
    if metadata is None:
        metadata = etree.Element(_dodp("metadata"))

    def dc(name: str) -> tuple[str, ...]:
        return tuple(
            (c.text or "").strip() for c in metadata.findall(f"{{{_DC}}}{name}")
        )

    def first(name: str) -> str | None:
        found = dc(name)
        return found[0] if found else None

    sample = element.find(_dodp("sample"))
    requires = element.get("requiresReturn")
    return ContentMetadata(
        title=first("title"),
        identifier=first("identifier"),
        format=first("format"),
        size=_int(metadata.findtext(_dodp("size"))),
        requires_return=(
            None if requires is None else requires.strip().lower() in {"true", "1"}
        ),
        category=element.get("category"),
        sample_id=sample.get("id") if sample is not None else None,
        publisher=first("publisher"),
        date=first("date"),
        source=first("source"),
        types=dc("type"),
        subjects=dc("subject"),
        rights=dc("rights"),
        relations=dc("relation"),
        languages=dc("language"),
        descriptions=dc("description"),
        creators=dc("creator"),
        coverage=dc("coverage"),
        contributors=dc("contributor"),
        narrators=tuple(
            (n.text or "").strip() for n in metadata.findall(_dodp("narrator"))
        ),
        meta=tuple(
            (m.get("name") or "", m.get("content") or "")
            for m in metadata.findall(_dodp("meta"))
        ),
    )


class HttpServicePort:
    """A `ServicePort` that talks SOAP over HTTP to one Service URL.

    Redirects are never followed: a Service that redirects gives no usable
    answer, which also keeps credentials and cookies on the host the user named.
    """

    def __init__(
        self,
        url: str,
        *,
        client: httpx.Client | None = None,
        quirks: Collection[str] = (),
    ) -> None:
        unknown = sorted(set(quirks) - QUIRKS.keys())
        if unknown:
            raise ValueError(f"unknown Quirk: {', '.join(unknown)}")
        self._quirks = frozenset(quirks)
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

    def resume(self, session: SessionState) -> None:
        host = urlsplit(self._url).hostname or ""
        self._client.cookies.clear()
        for name, value in session.cookies:
            self._client.cookies.set(name, value, domain=host)

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

    def get_service_announcements(self) -> Reply[tuple[Announcement, ...]]:
        def read(
            response: etree._Element,
        ) -> (
            tuple[tuple[Announcement, ...], tuple[SchemaViolation, ...]]
            | Deviation
            | None
        ):
            element = response.find(_dodp("announcements"))
            if element is None:
                return None
            return _announcements(element), self._validate(element)

        return self._call("getServiceAnnouncements", lambda parent: None, read)

    def mark_announcements_as_read(self, ids: Sequence[str]) -> Reply[bool]:
        def fill(parent: etree._Element) -> None:
            read = etree.SubElement(parent, _dodp("read"))
            for identifier in ids:
                _text_element(read, "item", identifier)

        return self._call(
            "markAnnouncementsAsRead", fill, self._result("markAnnouncementsAsRead")
        )

    def get_content_list(
        self, id: str, first_item: int, last_item: int
    ) -> Reply[ContentList]:
        def fill(parent: etree._Element) -> None:
            _text_element(parent, "id", id)
            _text_element(parent, "firstItem", str(first_item))
            _text_element(parent, "lastItem", str(last_item))

        def read(
            response: etree._Element,
        ) -> tuple[ContentList, tuple[SchemaViolation, ...]] | Deviation | None:
            element = response.find(_dodp("contentList"))
            if element is None:
                return None
            return _content_list(element), self._validate(element)

        return self._call("getContentList", fill, read)

    def get_content_metadata(self, content_id: str) -> Reply[ContentMetadata]:
        def read(
            response: etree._Element,
        ) -> tuple[ContentMetadata, tuple[SchemaViolation, ...]] | Deviation | None:
            element = response.find(_dodp("contentMetadata"))
            if element is None:
                return None
            return _content_metadata(element), self._validate(element)

        def fill(parent: etree._Element) -> None:
            _text_element(parent, "contentID", content_id)

        return self._call("getContentMetadata", fill, read)

    def send_raw(self, operation: str, body: str) -> Reply[str]:
        """`RawChannel`: send `operation` and `body` as given, unchecked."""
        request_body = (
            f'<soap:Envelope xmlns:soap="{_SOAP}"><soap:Body>'
            f'<{operation} xmlns="{_NS}">{body}</{operation}>'
            "</soap:Body></soap:Envelope>"
        ).encode()

        def read(
            response: etree._Element,
        ) -> tuple[str, tuple[SchemaViolation, ...]] | Deviation | None:
            return etree.tostring(response, encoding="unicode"), ()

        return self._transact(operation, request_body, read, expect_response=False)

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
        return self._transact(operation, _envelope(operation, fill), read)

    def _transact[T](
        self,
        operation: str,
        request_body: bytes,
        read: Callable[
            [etree._Element],
            tuple[T, tuple[SchemaViolation, ...]] | Deviation | None,
        ],
        *,
        expect_response: bool = True,
    ) -> Reply[T]:
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
        observations = self._observations + self._cookie_observations(response)
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
                spec_reference=operation_ref(operation),
                exchange=exchange,
                observations=observations,
            )
        if payload.tag == f"{{{_SOAP}}}Fault":
            return self._fault(
                operation, payload, exchange=exchange, observations=observations
            )
        if expect_response and payload.tag != _dodp(f"{operation}Response"):
            return Deviation(
                description=(
                    f"expected {operation}Response, got "
                    f"{etree.QName(payload).localname}"
                ),
                spec_reference=operation_ref(operation),
                exchange=exchange,
                observations=observations,
            )
        parsed = read(payload)
        if parsed is None:
            return Deviation(
                description=f"{operation}Response lacks a usable result",
                spec_reference=operation_ref(operation),
                exchange=exchange,
                observations=observations,
            )
        if isinstance(parsed, Deviation):
            return parsed
        value, violations = parsed
        return Ok(
            value=value,
            schema_violations=violations,
            exchange=exchange,
            observations=observations,
        )

    def _cookie_observations(self, response: httpx.Response) -> tuple[Observation, ...]:
        """`cookie-hardening`: a Session cookie set without protective attributes."""
        weaknesses: list[str] = []
        for header in response.headers.get_list("set-cookie"):
            attributes = {
                part.strip().split("=", 1)[0].lower() for part in header.split(";")[1:]
            }
            if "httponly" not in attributes:
                weaknesses.append("HttpOnly")
            if "secure" not in attributes and self._url.lower().startswith("https:"):
                weaknesses.append("Secure")
        if not weaknesses:
            return ()
        missing = " and ".join(dict.fromkeys(weaknesses))
        return (
            Observation(
                id="cookie-hardening",
                message=f"the Service sets a cookie without {missing}",
            ),
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

    def _fault(
        self,
        operation: str,
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
        if (
            BARE_500_AS_INVALID_OPERATION in self._quirks
            and exchange.status == 500
            and operation not in _BEFORE_INITIALISATION
        ):
            return Fault(
                kind=FaultKind.INVALID_OPERATION,
                reason=None,
                exchange=exchange,
                observations=(
                    *observations,
                    Observation(
                        id=OBSERVATION_ID,
                        message=(
                            f"Quirk {BARE_500_AS_INVALID_OPERATION}: an HTTP 500 "
                            "without a DODP fault element was read as an "
                            "invalidOperation fault"
                        ),
                    ),
                ),
            )
        return Deviation(
            description="a SOAP fault without a recognisable DODP fault element",
            spec_reference=SPEC_REFS["faults"],
            exchange=exchange,
            observations=observations,
        )
