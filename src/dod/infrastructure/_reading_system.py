"""Reading a `readingSystemAttributes` document into the model."""

from __future__ import annotations

from lxml import etree

from dod.application import ReadingSystemError
from dod.domain.v1 import ReadingSystemAttributes, ReadingSystemConfig
from dod.infrastructure._schema import SchemaUnavailableError, validate_document

_NS = "http://www.daisy.org/ns/daisy-online/"


def _dodp(name: str) -> str:
    return f"{{{_NS}}}{name}"


def parse_reading_system(content: bytes) -> ReadingSystemAttributes:
    """Parse and validate a declaration; the whole file is checked, offline.

    Raises `ReadingSystemError` with every finding. Elements from other
    namespaces, which the schema allows, are not sent on.
    """
    try:
        root = etree.fromstring(
            content, etree.XMLParser(resolve_entities=False, no_network=True)
        )
    except etree.XMLSyntaxError as error:
        raise ReadingSystemError(f"is not well-formed XML: {error.msg}") from None
    if root.tag != _dodp("readingSystemAttributes"):
        raise ReadingSystemError(
            f"the root element must be readingSystemAttributes in the namespace {_NS}"
        )
    try:
        findings = validate_document(content)
    except SchemaUnavailableError:
        findings = ()
    if findings:
        raise ReadingSystemError(
            "does not conform to the DODP v1 schemas: "
            + "; ".join(f"line {f.line}: {f.message}" for f in findings)
        )
    config = root.find(_dodp("config"))
    assert config is not None  # guaranteed by the schema

    def text(parent: etree._Element, name: str) -> str:
        return (parent.findtext(_dodp(name)) or "").strip()

    def flag(name: str) -> bool:
        return text(config, name).lower() in {"true", "1"}

    def items(name: str, child: str, attribute: str | None = None) -> tuple[str, ...]:
        found = config.find(_dodp(name))
        if found is None:
            return ()
        return tuple(
            (element.get(attribute) if attribute else element.text) or ""
            for element in found.findall(_dodp(child))
        )

    bandwidth = text(config, "bandwidth")
    serial = root.findtext(_dodp("serialNumber"))
    return ReadingSystemAttributes(
        manufacturer=text(root, "manufacturer"),
        model=text(root, "model"),
        version=text(root, "version"),
        serial_number=serial.strip() if serial is not None else None,
        config=ReadingSystemConfig(
            supports_multiple_selections=flag("supportsMultipleSelections"),
            preferred_ui_language=text(config, "preferredUILanguage"),
            supported_content_formats=tuple(
                t.strip() for t in items("supportedContentFormats", "contentFormat")
            ),
            supported_content_protection_formats=tuple(
                t.strip()
                for t in items("supportedContentProtectionFormats", "protectionFormat")
            ),
            supported_mime_types=items("supportedMimeTypes", "mimeType", "type"),
            supported_input_types=items("supportedInputTypes", "input", "type"),
            requires_audio_labels=flag("requiresAudioLabels"),
            bandwidth=int(bandwidth) if bandwidth else None,
            additional_transfer_protocols=tuple(
                t.strip() for t in items("additionalTransferProtocols", "protocol")
            ),
        ),
    )
