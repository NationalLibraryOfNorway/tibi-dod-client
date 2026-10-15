"""Ephemeral logon: the Initialisation sequence followed by `logOff` (ADR 0005).

Ephemeral mode never persists anything. This is the first use case; it will
move behind the session manager when that exists. Use cases do not print and
do not exit: they return the Replies unchanged and presentation renders them.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
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


def default_reading_system() -> ReadingSystemAttributes:
    """What `dod` tells a Service about itself in `setReadingSystemAttributes`."""
    try:
        release = version("dod-client")
    except PackageNotFoundError:
        release = "0"
    return ReadingSystemAttributes(
        manufacturer="National Library of Norway",
        model="dod",
        version=release,
        config=ReadingSystemConfig(
            supports_multiple_selections=False,
            preferred_ui_language="en",
            supported_content_formats=("Daisy 2.02",),
            supported_content_protection_formats=(),
            supported_mime_types=("audio/mpeg",),
            supported_input_types=("TEXT_NUMERIC",),
            requires_audio_labels=False,
        ),
    )


def logon_ephemeral(
    open_port: OpenPort,
    url: str,
    username: str,
    password: Password,
    *,
    insecure: bool = False,
    reading_system: ReadingSystemAttributes | None = None,
) -> LogonReport:
    """Run `logOn`, `getServiceAttributes`, `setReadingSystemAttributes`, `logOff`.

    Stops at the first step that does not succeed, but still ends a Session
    that `logOn` started, so no half-finished Session is left behind.

    Raises `EndpointError` before anything is sent when the address is refused,
    and `TransportError` when a call got no usable answer.
    """
    check_endpoint(url, insecure=insecure)
    attributes = reading_system or default_reading_system()
    port = open_port(url)
    steps: list[Step] = []
    try:
        steps.append(Step("logOn", port.log_on(username, password)))
        if steps[-1].succeeded:
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
            steps.append(Step("logOff", port.log_off()))
        return LogonReport(tuple(steps))
    finally:
        port.close()


def _log_off_quietly(port: ServicePort) -> None:
    with contextlib.suppress(TransportError):
        port.log_off()
