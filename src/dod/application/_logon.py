"""The Initialisation sequence and the ephemeral logon (ADR 0005).

The sequence is shared with the session manager. Use cases do not print and
do not exit: they return the Replies unchanged and presentation renders them.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, metadata, version
from typing import Any

from dod.application._address import check_endpoint
from dod.domain.service import Observation, Ok, Password, Reply, TransportError
from dod.domain.v1 import ReadingSystemAttributes, ReadingSystemConfig, ServicePort

type OpenPort = Callable[[str], ServicePort]
"""Opens a port towards the Service at a URL; supplied by the composition root."""


@dataclass(frozen=True)
class Step:
    """One call made while logging on, and what the Service answered."""

    operation: str
    reply: Reply[Any]

    @property
    def succeeded(self) -> bool:
        # `logOn` and friends answer a boolean; false means the Service said no.
        return isinstance(self.reply, Ok) and self.reply.value is not False


@dataclass(frozen=True)
class LogonReport:
    """The calls of one ephemeral logon, in the order they were made."""

    steps: tuple[Step, ...]

    @property
    def succeeded(self) -> bool:
        return all(step.succeeded for step in self.steps)

    @property
    def observations(self) -> tuple[Observation, ...]:
        """All Observations, each only once per run."""
        seen: dict[Observation, None] = {}
        for step in self.steps:
            seen.update(dict.fromkeys(step.reply.observations))
        return tuple(seen)


_PRODUCER = "National Library of Norway"


def default_reading_system() -> ReadingSystemAttributes:
    """What `dod` tells a Service about itself in `setReadingSystemAttributes`.

    Producer and version come from the installed package; DAISY 2.02 and
    EPUB 3, `audio/mpeg` and `audio/wav` and the text and numeric input types
    are what `dod` can act on. A file or an Environment's `reading_system`
    replaces all of it.
    """
    try:
        release = version("dod-client")
        producer = metadata("dod-client").get("Author") or _PRODUCER
    except PackageNotFoundError:
        release = "0"
        producer = _PRODUCER
    return ReadingSystemAttributes(
        manufacturer=producer,
        model="dod",
        version=release,
        config=ReadingSystemConfig(
            supports_multiple_selections=False,
            preferred_ui_language="en",
            supported_content_formats=("Daisy 2.02", "EPUB 3"),
            supported_content_protection_formats=(),
            supported_mime_types=("audio/mpeg", "audio/wav"),
            supported_input_types=("TEXT_NUMERIC", "TEXT_ALPHANUMERIC"),
            requires_audio_labels=False,
        ),
    )


def initialise(
    port: ServicePort,
    username: str,
    password: Password,
    attributes: ReadingSystemAttributes,
) -> list[Step]:
    """Run `logOn`, `getServiceAttributes`, `setReadingSystemAttributes`.

    Stops at the first step that does not succeed. A Session that `logOn`
    started is ended again when a later step fails or gets no usable answer, so
    no half-finished Session is left behind; when every step succeeded the
    Session is alive and the caller decides what happens to it.

    Raises `TransportError` when a call got no usable answer.
    """
    steps = [Step("logOn", port.log_on(username, password))]
    if not steps[-1].succeeded:
        return steps
    try:
        for operation, call in (
            ("getServiceAttributes", port.get_service_attributes),
            (
                "setReadingSystemAttributes",
                lambda: port.set_reading_system_attributes(attributes),
            ),
        ):
            steps.append(Step(operation, call()))
            if not steps[-1].succeeded:
                break
    except TransportError:
        _log_off_quietly(port)
        raise
    if not steps[-1].succeeded:
        with contextlib.suppress(TransportError):
            steps.append(Step("logOff", port.log_off()))
    return steps


def logon_ephemeral(
    open_port: OpenPort,
    url: str,
    username: str,
    password: Password,
    *,
    insecure: bool = False,
    reading_system: ReadingSystemAttributes | None = None,
) -> LogonReport:
    """Run the Initialisation sequence followed by `logOff`.

    Raises `EndpointError` before anything is sent when the address is refused,
    and `TransportError` when a call got no usable answer.
    """
    check_endpoint(url, insecure=insecure)
    attributes = reading_system or default_reading_system()
    port = open_port(url)
    try:
        steps = initialise(port, username, password, attributes)
        if all(step.succeeded for step in steps):
            steps.append(Step("logOff", port.log_off()))
        return LogonReport(tuple(steps))
    finally:
        port.close()


def _log_off_quietly(port: ServicePort) -> None:
    with contextlib.suppress(TransportError):
        port.log_off()
