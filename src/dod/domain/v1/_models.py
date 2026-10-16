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
