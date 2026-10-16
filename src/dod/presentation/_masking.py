"""Masking of secrets in a presented Exchange (ADR 0007).

`mask` is the only function that decides what is secret; stderr diagnostics,
`--save-exchanges` files and later the conformance reports all go through it.
A masked value is replaced by `***[ab12cd]`, a short fingerprint of the value,
so that two Exchanges can be seen to share a Session without revealing it.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from urllib.parse import urlsplit, urlunsplit

from dod.domain.service import Exchange

HIGHLIGHT_START = ""
HIGHLIGHT_END = ""
"""Private-use characters (valid in XML) around a value that was left unmasked.

Only the stderr renderer turns them into terminal colour; everything else sees
`MaskPolicy()` and so never meets them.
"""

_SALT = secrets.token_bytes(16)
"""Fingerprints of values that may be guessable (passwords, userinfo) are salted
per run, so a fingerprint cannot be used to check a guess offline."""

_COOKIE_HEADERS = {"cookie", "set-cookie"}
_AUTH_HEADERS = {"authorization", "proxy-authorization"}
_URL_HEADERS = {"location", "referer", "content-location"}
_PASSWORD_ELEMENT = re.compile(
    r"(<(?:[\w.-]+:)?password(?:\s[^>]*)?>)([^<]*)(</(?:[\w.-]+:)?password\s*>)",
    re.IGNORECASE,
)
_URL_USERINFO = re.compile(
    r"(\b[A-Za-z][A-Za-z0-9+.-]*://)([^/\s@\"'<>]+)@",
)
_CREDENTIAL_PARAMETER = re.compile(
    r"pass|token|secret|auth|cred|session|signature|api[-_]?key", re.IGNORECASE
)
_CREDENTIAL_PARAMETER_NAMES = {"key", "sid", "sig", "pwd"}


@dataclass(frozen=True)
class MaskPolicy:
    """What stays visible. The default hides everything secret."""

    unmask: bool = False
    """Show cookies and headers (`--unmask`)."""
    unmask_password: bool = False
    """Show the `logOn` password (`--unmask-password`)."""


def mask(exchange: Exchange, policy: MaskPolicy | None = None) -> Exchange:
    """Return the Exchange with its secrets replaced by fingerprints."""
    policy = policy or MaskPolicy()
    reveal = _revealer(policy.unmask)
    return replace(
        exchange,
        url=mask_url(exchange.url, reveal=reveal),
        request_headers=_headers(exchange.request_headers, reveal),
        request_body=_mask_userinfo(
            _mask_password(exchange.request_body, policy.unmask_password), reveal
        ),
        response_headers=_headers(exchange.response_headers, reveal),
        response_body=_mask_userinfo(
            _mask_password(exchange.response_body, policy.unmask_password), reveal
        ),
    )


def mask_url(url: str, *, reveal: Callable[[str, str], str] | None = None) -> str:
    """Hide userinfo and the values of credential-like query parameters."""
    show = reveal or _revealer(False)
    try:
        parts = urlsplit(url)
        host = parts.netloc.rsplit("@", 1)[1] if "@" in parts.netloc else None
    except ValueError:
        return url
    changed = False
    netloc = parts.netloc
    if host is not None:
        userinfo = parts.netloc.rsplit("@", 1)[0]
        netloc = f"{show(userinfo, 'salted')}@{host}"
        changed = True
    pairs = []
    for pair in parts.query.split("&") if parts.query else []:
        name, equals, value = pair.partition("=")
        if equals and _is_credential_parameter(name):
            pair = f"{name}={show(value, 'salted')}"
            changed = True
        pairs.append(pair)
    if not changed:
        return url
    return urlunsplit(parts._replace(netloc=netloc, query="&".join(pairs)))


def _is_credential_parameter(name: str) -> bool:
    lowered = name.lower()
    return lowered in _CREDENTIAL_PARAMETER_NAMES or bool(
        _CREDENTIAL_PARAMETER.search(lowered)
    )


def _fingerprint(value: str, kind: str) -> str:
    data = value.encode("utf-8")
    if kind == "salted":
        data = _SALT + data
    return f"***[{hashlib.sha256(data).hexdigest()[:6]}]"


def _revealer(unmask: bool) -> Callable[[str, str], str]:
    def show(value: str, kind: str) -> str:
        if unmask:
            return f"{HIGHLIGHT_START}{value}{HIGHLIGHT_END}"
        return _fingerprint(value, kind)

    return show


def _mask_userinfo(body: str, reveal: Callable[[str, str], str]) -> str:
    """Userinfo of an address inside a body, such as a resource `uri` attribute."""
    return _URL_USERINFO.sub(
        lambda match: f"{match.group(1)}{reveal(match.group(2), 'salted')}@", body
    )


def _mask_password(body: str, unmask: bool) -> str:
    def replace_value(match: re.Match[str]) -> str:
        value = match.group(2)
        shown = (
            f"{HIGHLIGHT_START}{value}{HIGHLIGHT_END}"
            if unmask
            else _fingerprint(value, "salted")
        )
        return f"{match.group(1)}{shown}{match.group(3)}"

    return _PASSWORD_ELEMENT.sub(replace_value, body)


def _headers(
    headers: tuple[tuple[str, str], ...], reveal: Callable[[str, str], str]
) -> tuple[tuple[str, str], ...]:
    return tuple((name, _header_value(name, value, reveal)) for name, value in headers)


def _header_value(name: str, value: str, reveal: Callable[[str, str], str]) -> str:
    key = name.lower()
    if key == "cookie":
        return "; ".join(_pair(part, reveal) for part in value.split("; "))
    if key == "set-cookie":
        first, separator, rest = value.partition(";")
        return _pair(first, reveal) + separator + rest
    if key in _AUTH_HEADERS:
        scheme, space, credentials = value.partition(" ")
        if not space:
            return reveal(value, "salted")
        return f"{scheme} {reveal(credentials, 'salted')}"
    if key in _URL_HEADERS:
        return mask_url(value, reveal=reveal)
    return value


def _pair(pair: str, reveal: Callable[[str, str], str]) -> str:
    name, equals, value = pair.partition("=")
    return f"{name}={reveal(value, 'stable')}" if equals else pair
