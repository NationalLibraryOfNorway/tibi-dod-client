"""Diagnostics of one run: `--debug`, `--save-exchanges` and Observations.

Every Exchange passes through `mask` before it is written anywhere. The
`ServicePort` handed to a command is wrapped so that commands need to know
nothing about diagnostics. Diagnostics only ever go to stderr or to files, so
stdout stays reserved for the result.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path

import typer
from lxml import etree

from dod.application import OpenPort, OpenRawChannel
from dod.domain.service import (
    Exchange,
    Observation,
    Password,
    Reply,
    SessionState,
    TransportError,
)
from dod.domain.v1 import (
    Announcement,
    BookmarkSet,
    ByteRange,
    ContentList,
    ContentMetadata,
    ContentResources,
    KeyExchangeObject,
    RawChannel,
    ReadingSystemAttributes,
    ResourceSink,
    ServiceAttributes,
    ServicePort,
)
from dod.presentation._masking import (
    HIGHLIGHT_END,
    HIGHLIGHT_START,
    MaskPolicy,
    mask,
)

_HIGHLIGHT_ON = "\x1b[1;31m"
_HIGHLIGHT_OFF = "\x1b[0m"
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
EXIT_UNUSABLE = 2


class Diagnostics:
    """Collects the Exchanges and Observations of a run and presents them."""

    def __init__(
        self,
        *,
        debug: bool = False,
        save_to: str | None = None,
        policy: MaskPolicy | None = None,
        colour: bool = False,
    ) -> None:
        self._debug = debug
        self._save_to = Path(save_to) if save_to else None
        self._policy = policy or MaskPolicy()
        self._colour = colour
        self._seen: set[Observation] = set()
        self.masked_exchanges: list[Exchange] = []
        if self._save_to is not None:
            try:
                self._save_to.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                self._abort(f"cannot use --save-exchanges directory: {error}")

    def wrap(self, open_port: OpenPort) -> OpenPort:
        """An `OpenPort` whose ports report what they send and receive."""

        def open_recorded(url: str) -> ServicePort:
            return _RecordingPort(open_port(url), self)

        return open_recorded

    def wrap_raw(self, open_raw: OpenRawChannel) -> OpenRawChannel:
        """An `OpenRawChannel` whose channels report what they send and receive."""

        def open_recorded(url: str) -> RawChannel:
            return _RecordingRawChannel(open_raw(url), self)

        return open_recorded

    def observe(self, observations: tuple[Observation, ...]) -> None:
        """Write each Observation once per run on stderr."""
        for observation in observations:
            if observation not in self._seen:
                self._seen.add(observation)
                typer.echo(
                    f"observation {observation.id}: {observation.message}", err=True
                )

    def record(self, exchange: Exchange) -> None:
        masked = mask(exchange, self._policy)
        # The stored copy is always fully masked: it feeds stdout and files.
        self.masked_exchanges.append(mask(exchange))
        number = len(self.masked_exchanges)
        if self._debug:
            self._write_block(masked, number)
        if self._save_to is not None:
            self._save(mask(exchange), number)

    def _write_block(self, masked: Exchange, number: int) -> None:
        lines = [f"== exchange {number}: {masked.method} {masked.url}"]
        lines += [f"{name}: {value}" for name, value in masked.request_headers]
        lines += ["", _pretty(masked.request_body), ""]
        lines.append(
            f"-- {masked.status} in {round(masked.duration_seconds * 1000)} ms"
        )
        lines += [f"{name}: {value}" for name, value in masked.response_headers]
        lines += ["", _pretty(masked.response_body)]
        if masked.response_truncated:
            lines.append("[the body is cut here; the rest went to a file]")
        lines.append("")
        text = "\n".join(lines)
        if self._colour:
            text = text.replace(HIGHLIGHT_START, _HIGHLIGHT_ON).replace(
                HIGHLIGHT_END, _HIGHLIGHT_OFF
            )
        else:
            text = text.replace(HIGHLIGHT_START, "").replace(HIGHLIGHT_END, "")
        typer.echo(text, err=True, color=self._colour)

    def _save(self, masked: Exchange, number: int) -> None:
        assert self._save_to is not None
        stem = f"{number:03d}-{_operation(masked)}"
        summary: dict[str, object] = {
            "method": masked.method,
            "url": masked.url,
            "status": masked.status,
            "duration_seconds": round(masked.duration_seconds, 3),
            "request_headers": [list(pair) for pair in masked.request_headers],
            "response_headers": [list(pair) for pair in masked.response_headers],
        }
        if masked.response_truncated:
            summary["response_body_truncated"] = True
        try:
            for suffix, content in (
                ("request.xml", masked.request_body),
                ("response.xml", masked.response_body),
                ("json", json.dumps(summary, indent=2) + "\n"),
            ):
                (self._save_to / f"{stem}.{suffix}").write_text(
                    content, encoding="utf-8", newline="\n"
                )
        except OSError as error:
            self._abort(f"cannot write --save-exchanges files: {error}")

    @staticmethod
    def _abort(message: str) -> None:
        typer.echo(f"error: {message}", err=True)
        raise typer.Exit(EXIT_UNUSABLE)


def _operation(exchange: Exchange) -> str:
    for name, value in exchange.request_headers:
        if name.lower() == "soapaction":
            return _UNSAFE.sub("", value.strip('"/')) or "call"
    return "call"


def _pretty(body: str) -> str:
    """Indent an XML document for reading; anything else is shown as it is."""
    try:
        root = etree.fromstring(
            body.encode("utf-8"),
            etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError:
        return body
    return etree.tostring(root, pretty_print=True, encoding="unicode").rstrip("\n")


class _RecordingPort:
    """Reports every Exchange of the wrapped port, then returns its answer."""

    def __init__(self, port: ServicePort, diagnostics: Diagnostics) -> None:
        self._port = port
        self._diagnostics = diagnostics

    @property
    def session(self) -> SessionState | None:
        return self._port.session

    def resume(self, session: SessionState) -> None:
        self._port.resume(session)

    def _call[T](self, call: Callable[[], Reply[T]]) -> Reply[T]:
        try:
            reply = call()
        except TransportError as error:
            if error.exchange is not None:
                self._diagnostics.record(error.exchange)
            raise
        self._diagnostics.record(reply.exchange)
        self._diagnostics.observe(reply.observations)
        return reply

    def log_on(self, username: str, password: Password) -> Reply[bool]:
        return self._call(lambda: self._port.log_on(username, password))

    def log_off(self) -> Reply[bool]:
        return self._call(self._port.log_off)

    def get_service_attributes(self) -> Reply[ServiceAttributes]:
        return self._call(self._port.get_service_attributes)

    def set_reading_system_attributes(
        self, attributes: ReadingSystemAttributes
    ) -> Reply[bool]:
        return self._call(lambda: self._port.set_reading_system_attributes(attributes))

    def get_service_announcements(self) -> Reply[tuple[Announcement, ...]]:
        return self._call(self._port.get_service_announcements)

    def mark_announcements_as_read(self, ids: Sequence[str]) -> Reply[bool]:
        return self._call(lambda: self._port.mark_announcements_as_read(ids))

    def issue_content(self, content_id: str) -> Reply[bool]:
        return self._call(lambda: self._port.issue_content(content_id))

    def return_content(self, content_id: str) -> Reply[bool]:
        return self._call(lambda: self._port.return_content(content_id))

    def get_bookmarks(self, content_id: str) -> Reply[BookmarkSet]:
        return self._call(lambda: self._port.get_bookmarks(content_id))

    def set_bookmarks(self, content_id: str, bookmark_set: str) -> Reply[bool]:
        return self._call(lambda: self._port.set_bookmarks(content_id, bookmark_set))

    def get_key_exchange_object(
        self, requested_key_name: str
    ) -> Reply[KeyExchangeObject]:
        return self._call(
            lambda: self._port.get_key_exchange_object(requested_key_name)
        )

    def get_content_list(
        self, id: str, first_item: int, last_item: int
    ) -> Reply[ContentList]:
        return self._call(
            lambda: self._port.get_content_list(id, first_item, last_item)
        )

    def get_content_metadata(self, content_id: str) -> Reply[ContentMetadata]:
        return self._call(lambda: self._port.get_content_metadata(content_id))

    def get_content_resources(self, content_id: str) -> Reply[ContentResources]:
        return self._call(lambda: self._port.get_content_resources(content_id))

    def fetch_resource(
        self, uri: str, sink: ResourceSink, byte_range: ByteRange | None = None
    ) -> Reply[int]:
        return self._call(lambda: self._port.fetch_resource(uri, sink, byte_range))

    def close(self) -> None:
        self._port.close()


class _RecordingRawChannel:
    """Reports every Exchange of the wrapped raw channel, then returns its answer."""

    def __init__(self, channel: RawChannel, diagnostics: Diagnostics) -> None:
        self._channel = channel
        self._diagnostics = diagnostics

    def send_raw(self, operation: str, body: str) -> Reply[str]:
        try:
            reply = self._channel.send_raw(operation, body)
        except TransportError as error:
            if error.exchange is not None:
                self._diagnostics.record(error.exchange)
            raise
        self._diagnostics.record(reply.exchange)
        self._diagnostics.observe(reply.observations)
        return reply

    def resume(self, session: SessionState) -> None:
        self._channel.resume(session)

    def close(self) -> None:
        self._channel.close()
