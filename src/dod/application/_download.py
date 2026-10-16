"""Resources and download: everything a `resources` answer names is untrusted.

`localURI` values, resource addresses and sizes come from the Service and are
checked before the first byte is fetched or written (ADR 0008). Use cases do
not print and do not exit; they return what happened and presentation renders
it. The whole download runs inside one `SessionManager.call` (ADR 0005), and a
resource GET never triggers a relogin.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from dod.application._address import EndpointError, check_endpoint, origin
from dod.application._session import SessionManager
from dod.domain.book import local_uri_segments
from dod.domain.service import Deviation, Observation, Ok, Reply
from dod.domain.v1 import (
    SPEC_REFS,
    ContentResource,
    ContentResources,
    ServicePort,
    SinkRefused,
)

_RESERVED_NAME = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)
_SAFE_SEGMENT_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)
_LONG_SEGMENT = 100
_PART = ".part"


class ResourceRefused(Exception):
    """A resource address `dod` will not fetch; the message says what to do."""


@dataclass(frozen=True)
class ResolvedResource:
    """An absolute resource address and what was noticed resolving it."""

    url: str
    observations: tuple[Observation, ...] = ()


def safe_segment(text: str) -> str:
    """Encode `text` as one path segment that is safe on every platform.

    Anything but ASCII letters, digits, `-`, `_` and an interior `.` is
    percent-encoded (UTF-8), so a separator, a drive letter, `..` or a
    reserved device name cannot come out of it, and two texts never give the
    same segment. A segment that would be too long is shortened to a prefix and
    a hash, marked by `~`, which the encoding itself never produces.
    """
    if not text:
        return "%"
    encoded: list[str] = []
    last = len(text) - 1
    for index, character in enumerate(text):
        if character in _SAFE_SEGMENT_CHARACTERS or (
            character == "." and 0 < index < last
        ):
            encoded.append(character)
        else:
            encoded.append("".join(f"%{byte:02X}" for byte in character.encode()))
    segment = "".join(encoded)
    if _RESERVED_NAME.match(segment):
        segment = "".join(f"%{byte:02X}" for byte in segment[0].encode()) + segment[1:]
    if len(segment) > _LONG_SEGMENT:
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        segment = f"{segment[:60].rstrip('%')}~{digest}"
    return segment


def book_directory(data_dir: Path, environment: str, content_id: str) -> Path:
    """`<data>/<environment>/books/<contentID>`, each name as one safe segment."""
    return data_dir / safe_segment(environment) / "books" / safe_segment(content_id)


def _shown(text: str) -> str:
    return repr(text if len(text) <= 60 else text[:57] + "...")


def validate_resources(resources: Sequence[ContentResource]) -> tuple[str, ...]:
    """What is wrong with the `localURI`s and sizes of a whole list; empty if fine.

    Every entry is checked, also those a download will not fetch: one bad
    entry in the list means the Service cannot be trusted with the rest.
    """
    problems: list[str] = []
    seen: dict[str, str] = {}
    keys: list[tuple[str, str]] = []
    for item in resources:
        segments, problem = local_uri_segments(item.local_uri)
        if problem is not None:
            problems.append(f"localURI {_shown(item.local_uri)}: {problem}")
            continue
        assert segments is not None
        if item.size is None or item.size < 0:
            problems.append(
                f"localURI {_shown(item.local_uri)}: its size is missing or negative"
            )
        key = unicodedata.normalize("NFC", "/".join(segments)).casefold()
        if key in seen:
            problems.append(
                f"localURI {_shown(item.local_uri)}: it names the same file as "
                f"{_shown(seen[key])}"
            )
            continue
        seen[key] = item.local_uri
        keys.append((key, item.local_uri))
    finals = {key for key, _ in keys}
    for key, local_uri in keys:
        if key + _PART in finals:
            problems.append(
                f"localURI {_shown(local_uri)}: its partial file {key + _PART!r} is "
                "another entry"
            )
        if any(other.startswith(key + "/") for other in finals):
            problems.append(
                f"localURI {_shown(local_uri)}: it is both a file and a directory"
            )
    return tuple(problems)


def resolve_resource_uri(
    uri: str, service_url: str, *, trust_host: bool, insecure: bool
) -> ResolvedResource:
    """The absolute address to fetch, or `ResourceRefused`.

    A relative address is resolved against the Service URL (Observation
    `interoperability`). Another origin than the Service's needs `trust_host`
    (Observation `host-boundary`; ADR 0002), and `https` is required unless
    `insecure`. Userinfo in the address is kept: it is the Service Delegate's
    own credential and is only ever sent to that host.
    """
    if not uri.strip():
        raise ResourceRefused("a resource has an empty address")
    observations: list[Observation] = []
    parts = urlsplit(uri)
    if parts.scheme == "" and parts.netloc == "":
        observations.append(
            Observation(
                id="interoperability",
                message=(
                    "a resource address is relative; it was resolved against the "
                    "Service URL"
                ),
            )
        )
    url = urljoin(service_url, uri)
    shown = _for_message(url)
    try:
        check_endpoint(url, insecure=insecure)
    except EndpointError as error:
        raise ResourceRefused(f"the resource {shown}: {error}") from None
    if origin(url) != origin(service_url):
        host = urlsplit(url).hostname
        if not trust_host:
            raise ResourceRefused(
                f"the resource {shown} is not on the Service's own host, port and "
                "scheme (a Service Delegate); pass --trust-host to fetch it"
            )
        observations.append(
            Observation(
                id="host-boundary",
                message=(
                    f"a resource is on another host ({host}) than the Service; "
                    "fetched because of --trust-host, without the Session cookie "
                    "or the password"
                ),
            )
        )
    return ResolvedResource(url, tuple(observations))


def _for_message(url: str) -> str:
    """An address for a message: no userinfo and no query, which may hold secrets."""
    parts = urlsplit(url)
    host = parts.netloc.rsplit("@", 1)[-1]
    return f"{parts.scheme}://{host}{parts.path}"


class FileOutcome(StrEnum):
    DOWNLOADED = "downloaded"
    FAILED = "failed"


@dataclass(frozen=True)
class FileResult:
    """What became of one file."""

    local_uri: str
    path: Path
    outcome: FileOutcome
    size: int = 0
    """The bytes written (downloaded) or received before the file was discarded."""
    problem: Reply[int] | str | None = None
    """Why a file failed: the Service's answer, or `dod`'s own reason."""


@dataclass(frozen=True)
class DownloadRequest:
    content_id: str
    directory: Path
    service_url: str
    files: tuple[str, ...] = ()
    """The `localURI`s to fetch; none means every file."""
    force: bool = False
    trust_host: bool = False
    insecure: bool = False


@dataclass(frozen=True)
class DownloadReport:
    """The outcome of `download`; nothing was written unless `files` says so."""

    resources: Reply[ContentResources]
    """What `getContentResources` answered, unchanged."""
    deviation: Deviation | None = None
    """The list names something that cannot be trusted; nothing was fetched."""
    refusal: str | None = None
    """`dod` would not run the download as asked; nothing was fetched."""
    files: tuple[FileResult, ...] = ()
    observations: tuple[Observation, ...] = ()

    @property
    def succeeded(self) -> bool:
        return (
            isinstance(self.resources, Ok)
            and self.deviation is None
            and self.refusal is None
            and all(f.outcome is FileOutcome.DOWNLOADED for f in self.files)
        )


def download(manager: SessionManager, request: DownloadRequest) -> DownloadReport:
    """List the resources of issued content and fetch the wanted ones.

    Never issues content (ADR 0008): `getContentResources` on content that is
    not issued is reported as the Service answered it. Files are fetched one at
    a time, and the first file that fails ends the run.
    """
    reports: list[DownloadReport] = []

    def operation(port: ServicePort) -> Reply[ContentResources]:
        reply = port.get_content_resources(request.content_id)
        reports.append(
            _fetch_all(port, reply, request)
            if isinstance(reply, Ok)
            else DownloadReport(reply)
        )
        return reply

    manager.call(operation)
    return reports[-1]


def _fetch_all(
    port: ServicePort, reply: Ok[ContentResources], request: DownloadRequest
) -> DownloadReport:
    resources = reply.value.resources
    problems = validate_resources(resources)
    if problems:
        shown = "; ".join(problems[:5])
        more = f" (and {len(problems) - 5} more)" if len(problems) > 5 else ""
        return DownloadReport(
            reply,
            deviation=Deviation(
                description=(
                    "the resource list is not safe to download, so nothing was "
                    f"fetched: {shown}{more}"
                ),
                spec_reference=SPEC_REFS["type.resources"],
                exchange=reply.exchange,
                observations=reply.observations,
            ),
        )
    selected = _select(resources, request.files)
    if isinstance(selected, str):
        return DownloadReport(reply, refusal=selected)
    plan: list[tuple[ContentResource, str, Path]] = []
    observations: dict[Observation, None] = {}
    for item in selected:
        try:
            resolved = resolve_resource_uri(
                item.uri,
                request.service_url,
                trust_host=request.trust_host,
                insecure=request.insecure,
            )
        except ResourceRefused as error:
            return DownloadReport(reply, refusal=str(error))
        observations.update(dict.fromkeys(resolved.observations))
        plan.append((item, resolved.url, _destination(request.directory, item)))
    if not request.force:
        existing = [str(path) for _, _, path in plan if os.path.lexists(path)]
        if existing:
            return DownloadReport(
                reply,
                refusal=(
                    f"{existing[0]} already exists"
                    + (f" (and {len(existing) - 1} more)" if len(existing) > 1 else "")
                    + "; nothing was fetched, pass --force to overwrite"
                ),
            )
    results: list[FileResult] = []
    for item, url, path in plan:
        result = _fetch_one(port, item, url, path, request)
        results.append(result)
        if result.outcome is FileOutcome.FAILED:
            break
    return DownloadReport(reply, files=tuple(results), observations=tuple(observations))


def _select(
    resources: Sequence[ContentResource], wanted: tuple[str, ...]
) -> list[ContentResource] | str:
    if not wanted:
        return list(resources)
    by_name = {item.local_uri: item for item in resources}
    unknown = [name for name in wanted if name not in by_name]
    if unknown:
        return (
            f"--file {_shown(unknown[0])} is not a localURI in the resource list; "
            "nothing was fetched (see `dod resources`)"
        )
    return [by_name[name] for name in dict.fromkeys(wanted)]


def _destination(directory: Path, item: ContentResource) -> Path:
    segments, problem = local_uri_segments(item.local_uri)
    assert segments is not None and problem is None
    return directory.joinpath(*segments)


def _fetch_one(
    port: ServicePort,
    item: ContentResource,
    url: str,
    target: Path,
    request: DownloadRequest,
) -> FileResult:
    assert item.size is not None
    part = target.with_name(target.name + _PART)
    expected = item.size
    received = 0
    try:
        _prepare(request.directory, target)
        part.unlink(missing_ok=True)  # also a link someone left in its place
        with part.open("xb") as handle:

            def sink(chunk: bytes) -> None:
                nonlocal received
                received += len(chunk)
                if received > expected:
                    raise SinkRefused(f"more than the {expected} bytes announced")
                handle.write(chunk)

            reply = port.fetch_resource(url, sink)
        if not isinstance(reply, Ok):
            return _discard(part, item, target, received, reply)
        if received != expected:
            return _discard(
                part,
                item,
                target,
                received,
                f"{received} bytes received, the Service announced {expected}",
            )
        if not request.force and os.path.lexists(target):
            return _discard(
                part, item, target, received, f"{target} appeared meanwhile"
            )
        os.replace(part, target)
    except OSError as error:
        return _discard(
            part, item, target, received, f"cannot write {target}: {error.strerror}"
        )
    return FileResult(item.local_uri, target, FileOutcome.DOWNLOADED, received)


def _prepare(directory: Path, target: Path) -> None:
    """Create the parents; refuse a path that leaves the book directory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    root = directory.resolve()
    if not target.parent.resolve().is_relative_to(root):
        raise OSError(0, "the path leaves the target directory")
    if target.is_dir():
        raise OSError(0, "it is a directory")


def _discard(
    part: Path,
    item: ContentResource,
    target: Path,
    received: int,
    problem: Reply[int] | str,
) -> FileResult:
    with contextlib.suppress(OSError):
        part.unlink()
    return FileResult(item.local_uri, target, FileOutcome.FAILED, received, problem)
