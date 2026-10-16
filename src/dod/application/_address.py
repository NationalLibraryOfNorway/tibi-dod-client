"""Finding the Service endpoint from what the user named (ADR 0002).

The endpoint comes only from an explicit `--url`, a `--wsdl` or an
Environment holding one of them; nothing is probed during login. `discover`
is the one place that guesses, and it sends no credentials. A WSDL is fetched
through the `Fetcher` seam, which carries neither cookies nor a password.
Use cases do not print and do not exit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from dod.application._config import Connection
from dod.domain.service import TransportError

MAX_WSDL_BYTES = 1024 * 1024
"""The largest WSDL that is read (1 MiB)."""

_MAX_REDIRECTS = 5
_MAX_PORTS_LISTED = 10
_DEFAULT_PORTS = {"http": 80, "https": 443}

KNOWN_PATHS = ("/service", "/dodp", "/daisy-online", "/DaisyOnline")
"""Paths `dod discover` tries, each with `?wsdl`, when the address itself fails."""


class EndpointError(Exception):
    """The Service address may not be used as given (a security rejection)."""


class WsdlError(Exception):
    """A document is not a usable Service WSDL; the message never quotes it."""


@dataclass(frozen=True)
class FetchResponse:
    """One answer to a plain GET; header names are lower case."""

    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes


class Fetcher(Protocol):
    """GET a document without credentials or cookies; never follows redirects."""

    def get(self, url: str, *, max_bytes: int) -> FetchResponse:
        """Raise `TransportError` without an answer or when over `max_bytes`."""
        ...


@dataclass(frozen=True)
class WsdlPort:
    """One `port` of a WSDL and what could be told about it."""

    name: str
    address: str
    is_dodp: bool
    """Bound to the DODP portType."""
    is_soap11: bool
    """A SOAP 1.1 binding and address."""


type WsdlParser = Callable[[bytes], tuple[WsdlPort, ...]]
"""Safely reads the ports of a WSDL document; raises `WsdlError`."""


@dataclass(frozen=True)
class Endpoint:
    """Where to send SOAP calls, and the WSDL it was read from, if any."""

    url: str
    wsdl: str | None = None


def check_endpoint(url: str, *, insecure: bool) -> None:
    """Refuse an address that is not `https` unless `insecure` is given.

    `http` needs `insecure` even on loopback, so credentials are never sent in
    clear text by accident.
    """
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme not in ("http", "https") or not parts.hostname:
        raise EndpointError(
            f"the address must be an https:// address with a host (got {url!r})"
        )
    if scheme == "http" and not insecure:
        raise EndpointError(
            "the address uses unencrypted http; pass --insecure to use it anyway"
        )


def origin(url: str) -> tuple[str, str, int | None]:
    """Scheme, host and port, with the default port made explicit."""
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return (
        scheme,
        (parts.hostname or "").lower(),
        parts.port or _DEFAULT_PORTS.get(scheme),
    )


def _origin_text(url: str) -> str:
    scheme, host, port = origin(url)
    return f"{scheme}://{host}:{port}"


def _describe(response: FetchResponse) -> str:
    kind = response.headers.get("content-type", "no content type")
    return f"HTTP {response.status}, {kind}, {len(response.body)} bytes"


def _fetch_wsdl(url: str, fetcher: Fetcher) -> FetchResponse:
    """GET following redirects only within the origin the user named."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        response = fetcher.get(current, max_bytes=MAX_WSDL_BYTES)
        if not 300 <= response.status < 400:
            return response
        location = response.headers.get("location")
        if not location:
            raise EndpointError(f"redirect without a Location ({_describe(response)})")
        target = urljoin(current, location)
        if origin(target) != origin(url):
            raise EndpointError(
                f"redirected from {_origin_text(url)} to {_origin_text(target)}; "
                "redirects across a host, port or scheme are refused"
            )
        current = target
    raise EndpointError(f"more than {_MAX_REDIRECTS} redirects")


def _read_port(wsdl_url: str, fetcher: Fetcher, parse_wsdl: WsdlParser) -> WsdlPort:
    """Fetch the WSDL and pick the one SOAP 1.1 port bound to the DODP portType."""
    try:
        response = _fetch_wsdl(wsdl_url, fetcher)
    except TransportError as error:
        raise EndpointError(f"cannot fetch the WSDL: {error}") from None
    if response.status != 200:
        raise EndpointError(f"the WSDL address answered {_describe(response)}")
    try:
        ports = parse_wsdl(response.body)
    except WsdlError as error:
        raise EndpointError(
            f"not a usable WSDL ({_describe(response)}): {error}"
        ) from None
    matching = [port for port in ports if port.is_dodp and port.is_soap11]
    if len(matching) == 1:
        return matching[0]
    listing = "".join(
        f"\n  {port.name}: {port.address} "
        f"({'DODP' if port.is_dodp else 'not DODP'}, "
        f"{'SOAP 1.1' if port.is_soap11 else 'not SOAP 1.1'})"
        for port in ports[:_MAX_PORTS_LISTED]
    )
    more = len(ports) - _MAX_PORTS_LISTED
    if more > 0:
        listing += f"\n  ... and {more} more"
    raise EndpointError(
        f"expected exactly one SOAP 1.1 port bound to the DODP portType, "
        f"found {len(matching)} among {len(ports)} ports:{listing or ' none'}\n"
        "Pass the SOAP endpoint directly with --url."
    )


def _check_address_host(wsdl_url: str, address: str, *, trust_host: bool) -> None:
    if origin(address) == origin(wsdl_url) or trust_host:
        return
    raise EndpointError(
        f"the WSDL at {_origin_text(wsdl_url)} names the endpoint "
        f"{_origin_text(address)}, another host, port or scheme; credentials "
        "would be sent there. Pass --trust-host if you trust it, or use --url."
    )


def resolve_endpoint(
    connection: Connection, fetcher: Fetcher, parse_wsdl: WsdlParser
) -> Endpoint | None:
    """The endpoint to talk to, or `None` when no address was named.

    A `--url` is used as it is. A WSDL is fetched without credentials every time
    (no cache) and its `soap:address` is used, but only on the host, port and
    scheme the WSDL itself came from unless `trust_host` is set. Raises
    `EndpointError` before anything with credentials is sent.
    """
    insecure = connection.insecure.value
    if connection.url is not None:
        check_endpoint(connection.url.value, insecure=insecure)
        return Endpoint(connection.url.value)
    if connection.wsdl is None:
        return None
    wsdl_url = connection.wsdl.value
    check_endpoint(wsdl_url, insecure=insecure)
    port = _read_port(wsdl_url, fetcher, parse_wsdl)
    _check_address_host(wsdl_url, port.address, trust_host=connection.trust_host.value)
    check_endpoint(port.address, insecure=insecure)
    return Endpoint(port.address, wsdl_url)


@dataclass(frozen=True)
class Attempt:
    """One address `discover` tried and what came of it."""

    url: str
    outcome: str
    port: WsdlPort | None = None

    @property
    def found(self) -> bool:
        return self.port is not None


@dataclass(frozen=True)
class Discovery:
    """What `discover` tried, in order; the last attempt is the one that worked."""

    attempts: tuple[Attempt, ...]

    @property
    def found(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts and self.attempts[-1].found else None


def discovery_candidates(address: str) -> tuple[str, ...]:
    """`?wsdl` on the address, then on the known paths of its origin."""
    parts = urlsplit(address)
    if parts.query:
        return (address,)
    candidates = [parts._replace(path=parts.path or "/", query="wsdl").geturl()]
    for path in KNOWN_PATHS:
        candidates.append(parts._replace(path=path, query="wsdl", fragment="").geturl())
    return tuple(dict.fromkeys(candidates))


def discover(
    address: str, fetcher: Fetcher, parse_wsdl: WsdlParser, *, insecure: bool
) -> Discovery:
    """Look for a WSDL at and around `address`; sends no credentials, stores nothing.

    Raises `EndpointError` when the address itself may not be used.
    """
    check_endpoint(address, insecure=insecure)
    attempts: list[Attempt] = []
    for candidate in discovery_candidates(address):
        try:
            port = _read_port(candidate, fetcher, parse_wsdl)
        except EndpointError as error:
            attempts.append(Attempt(candidate, str(error).split("\n")[0]))
            continue
        attempts.append(Attempt(candidate, "WSDL with one DODP port", port))
        break
    return Discovery(tuple(attempts))
