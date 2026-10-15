"""Configuration values and the error that rejects them."""

from __future__ import annotations

from dataclasses import dataclass, field

from dod.domain.service import Password


class ConfigError(Exception):
    """A configuration problem, with where it is and why.

    The message never contains the value of a password.
    """

    def __init__(
        self,
        reason: str,
        *,
        path: str | None = None,
        key: str | None = None,
        line: int | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.path = path
        self.key = key
        self.line = line

    def __str__(self) -> str:
        parts = [part for part in (self.path, self.key) if part]
        parts.append(self.reason)
        text = ": ".join(parts)
        return f"{text} (line {self.line})" if self.line is not None else text


@dataclass(frozen=True)
class Environment:
    """One named Service address with optional credentials and switches."""

    name: str
    url: str | None = None
    wsdl: str | None = None
    username: str | None = None
    password: Password | None = None
    insecure: bool = False
    trust_host: bool = False
    protected: bool = False
    quirks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    """The whole configuration file."""

    environments: dict[str, Environment] = field(default_factory=dict)
    default_environment: str | None = None
