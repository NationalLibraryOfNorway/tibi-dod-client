"""Version-neutral shared kernel (ADR 0004)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Password:
    """A secret that never shows its value in `repr`, `str` or tracebacks."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        """Return the secret itself; call it only where it goes on the wire."""
        return self._value

    def __repr__(self) -> str:
        return "Password(***)"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Password) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)


@dataclass(frozen=True)
class Exchange:
    """The raw request and response of one call, unmasked (see GLOSSARY.md)."""

    method: str
    url: str
    request_headers: tuple[tuple[str, str], ...]
    request_body: str
    status: int
    response_headers: tuple[tuple[str, str], ...]
    response_body: str
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class Observation:
    """Something noticed about a Service that is not a Conformance test Outcome."""

    id: str
    message: str


@dataclass(frozen=True)
class SchemaViolation:
    """One way in which a Service answer does not conform to the schemas."""

    line: int
    message: str


SPEC_URL = "http://www.daisy.org/projects/daisy-online-delivery/drafts/20100402/do-spec-20100402.html"
"""The published HTML version of the specification, which the local copy mirrors."""


@dataclass(frozen=True)
class SpecReference:
    """A pointer to the part of the specification a FAIL or Deviation contradicts.

    `anchor` is the id of the section heading in the HTML version and `rule` an
    optional short statement of the requirement, in our own words.
    """

    section: str
    title: str
    anchor: str
    rule: str | None = None

    @property
    def url(self) -> str:
        """A link to the section in the published HTML version."""
        return f"{SPEC_URL}#{self.anchor}"


@dataclass(frozen=True, kw_only=True)
class _Answer:
    exchange: Exchange
    observations: tuple[Observation, ...] = ()
    schema_violations: tuple[SchemaViolation, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Ok[T](_Answer):
    """The Service answered with a result."""

    value: T


class FaultKind(StrEnum):
    """The DODP v1 faults, named as the fault elements without the suffix."""

    INTERNAL_SERVER_ERROR = "internalServerError"
    INVALID_OPERATION = "invalidOperation"
    INVALID_PARAMETER = "invalidParameter"
    OPERATION_NOT_SUPPORTED = "operationNotSupported"
    NO_ACTIVE_SESSION = "noActiveSession"


@dataclass(frozen=True, kw_only=True)
class Fault(_Answer):
    """The Service answered with a DODP fault."""

    kind: FaultKind
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class Deviation(_Answer):
    """The Service answered, but contrary to the specification."""

    description: str
    spec_reference: SpecReference


type Reply[T] = Ok[T] | Fault | Deviation


@dataclass(frozen=True)
class SessionState:
    """An opaque, serialisable handle on a Session; the cookie values stay hidden."""

    cookies: tuple[tuple[str, str], ...]

    def __repr__(self) -> str:
        return f"SessionState(cookies=<{len(self.cookies)} hidden>)"


class TransportError(Exception):
    """The call got no usable answer at all (no answer, not SOAP, bad redirect)."""

    def __init__(self, message: str, *, exchange: Exchange | None = None) -> None:
        super().__init__(message)
        self.exchange = exchange
