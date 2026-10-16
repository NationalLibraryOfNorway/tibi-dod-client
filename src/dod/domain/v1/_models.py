"""DODP v1 models, close to the types of the specification (no XML types)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReadingSystemConfig:
    """The `config` part of `readingSystemAttributes` (specification 6.9)."""

    supports_multiple_selections: bool
    preferred_ui_language: str
    supported_content_formats: tuple[str, ...]
    supported_content_protection_formats: tuple[str, ...]
    supported_mime_types: tuple[str, ...]
    supported_input_types: tuple[str, ...]
    requires_audio_labels: bool
    bandwidth: int | None = None
    additional_transfer_protocols: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadingSystemAttributes:
    """What the Reading System tells the Service about itself (specification 6.9)."""

    manufacturer: str
    model: str
    version: str
    config: ReadingSystemConfig
    serial_number: str | None = None


@dataclass(frozen=True)
class ServiceAttributes:
    """What the Service tells about itself (specification 6.11), read leniently.

    Anything the Service left out is `None` or empty; schema violations are
    reported on the `Reply`, not here.
    """

    service_provider_id: str | None = None
    service_id: str | None = None
    supported_content_selection_methods: tuple[str, ...] = ()
    supports_server_side_back: bool | None = None
    supports_search: bool | None = None
    supported_uplink_audio_codecs: tuple[str, ...] = ()
    supports_audio_labels: bool | None = None
    supported_optional_operations: tuple[str, ...] = ()

    @property
    def supports_announcements(self) -> bool:
        """Whether the Service declares the announcement operations."""
        return "SERVICE_ANNOUNCEMENTS" in self.supported_optional_operations


@dataclass(frozen=True)
class Announcement:
    """One announcement from the Service (specification 6.3), read leniently.

    The text is whatever the Service sent and must be treated as untrusted
    wherever it is shown (ADR 0008).
    """

    id: str
    text: str
    lang: str | None = None
    type: str = "INFORMATION"
    priority: int = 3


@dataclass(frozen=True)
class ContentItem:
    """One entry of a content list (specification 6.4), read leniently.

    The label is whatever the Service sent and must be treated as untrusted
    wherever it is shown (ADR 0008).
    """

    id: str
    label: str
    lang: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class ContentList:
    """A content list or a segment of one (specification 6.4), read leniently.

    `id` is what the Service answered, which should equal the id asked for.
    `first_item` and `last_item` are what the Service says about the segment.
    """

    id: str
    total_items: int
    items: tuple[ContentItem, ...] = ()
    label: str | None = None
    first_item: int | None = None
    last_item: int | None = None


@dataclass(frozen=True)
class ContentMetadata:
    """The metadata of one content item (specification 6.5), read leniently.

    Dublin Core terms are kept as the text the Service sent; anything the
    Service left out is `None` or empty. Elements `dod` does not know are not
    modelled; they remain in the raw Exchange.
    """

    title: str | None = None
    identifier: str | None = None
    format: str | None = None
    size: int | None = None
    requires_return: bool | None = None
    category: str | None = None
    sample_id: str | None = None
    publisher: str | None = None
    date: str | None = None
    source: str | None = None
    types: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    rights: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    descriptions: tuple[str, ...] = ()
    creators: tuple[str, ...] = ()
    coverage: tuple[str, ...] = ()
    contributors: tuple[str, ...] = ()
    narrators: tuple[str, ...] = ()
    meta: tuple[tuple[str, str], ...] = ()
